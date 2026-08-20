"""Lecture et modification d'un projet QGIS (.qgz / .qgs).

Un .qgz est une archive ZIP contenant un fichier .qgs, qui est du XML. Ce
module manipule ce XML directement : aucune installation de QGIS n'est
requise, et le code reste testable hors environnement PyQGIS.

Operations couvertes :
  - lister les couches et verifier que leurs sources existent ;
  - centrer la carte sur l'emprise d'une couche (zoom) ;
  - enregistrer le projet sous un nouveau nom.

Limite : le zoom modifie l'emprise enregistree du canevas, telle que QGIS la
restaure a l'ouverture. Il n'y a pas de rendu graphique.
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from modop.services.qgis_datasource import compute_bounds, parse_datasource

# Providers dont la source designe un fichier sur le disque.
_FILE_PROVIDERS = frozenset({"ogr", "gdal", "delimitedtext", "spatialite", "gpx"})


@dataclass(frozen=True)
class Extent:
    """Emprise rectangulaire, dans l'unite du projet."""

    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def is_valid(self) -> bool:
        """Vrai si l'emprise a une surface non nulle."""
        return self.xmax > self.xmin and self.ymax > self.ymin

    def buffered(self, ratio: float = 0.05) -> "Extent":
        """Elargit l'emprise d'une marge proportionnelle.

        >>> Extent(0, 0, 10, 10).buffered(0.1)
        Extent(xmin=-1.0, ymin=-1.0, xmax=11.0, ymax=11.0)
        """
        margin_x = (self.xmax - self.xmin) * ratio
        margin_y = (self.ymax - self.ymin) * ratio
        return Extent(
            self.xmin - margin_x,
            self.ymin - margin_y,
            self.xmax + margin_x,
            self.ymax + margin_y,
        )


@dataclass(frozen=True)
class Layer:
    """Couche du projet, telle que decrite dans le XML."""

    id: str
    name: str
    source: str
    provider: str
    extent: Extent | None

    @property
    def is_file_based(self) -> bool:
        """Vrai si la source designe un fichier verifiable sur le disque."""
        return self.provider.lower() in _FILE_PROVIDERS


def _read_float(element, tag: str) -> float | None:
    """Lit un sous-element numerique. None si absent ou illisible."""
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    try:
        return float(child.text)
    except ValueError:
        return None


def _parse_extent(element) -> Extent | None:
    """Construit une Extent a partir d'un bloc <extent>."""
    if element is None:
        return None

    values = [_read_float(element, tag) for tag in ("xmin", "ymin", "xmax", "ymax")]
    if any(value is None for value in values):
        return None

    return Extent(*values)


class QgisProject:
    """Projet QGIS charge en memoire.

    Usage :
        project = QgisProject.open("modele.qgz")
        project.zoom_to_layer("communes")
        project.save_as("commune_45001.qgz")
    """

    def __init__(self, path: str, tree: ElementTree.ElementTree,
                 qgs_name: str, extra_files: dict[str, bytes]):
        self.path = path
        self._tree = tree
        self._root = tree.getroot()
        self._qgs_name = qgs_name
        # Fichiers annexes de l'archive (.qgd notamment), conserves tels quels.
        self._extra_files = extra_files

    # -- Ouverture ---------------------------------------------------------

    @classmethod
    def open(cls, path: str) -> "QgisProject":
        """Charge un projet .qgz ou .qgs.

        Raises:
            FileNotFoundError: fichier absent.
            ValueError: archive .qgz ne contenant aucun .qgs.
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Projet QGIS introuvable : {path}")

        if path.lower().endswith(".qgs"):
            tree = ElementTree.parse(path)
            return cls(path, tree, os.path.basename(path), {})

        extra_files: dict[str, bytes] = {}
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            qgs_names = [name for name in names if name.lower().endswith(".qgs")]
            if not qgs_names:
                raise ValueError(f"Aucun fichier .qgs dans l'archive : {path}")

            qgs_name = qgs_names[0]
            tree = ElementTree.ElementTree(
                ElementTree.fromstring(archive.read(qgs_name))
            )
            # Le .qgd (stockage auxiliaire) doit suivre le projet.
            for name in names:
                if name != qgs_name:
                    extra_files[name] = archive.read(name)

        return cls(path, tree, qgs_name, extra_files)

    # -- Lecture -----------------------------------------------------------

    @property
    def title(self) -> str:
        """Titre du projet, ou chaine vide."""
        element = self._root.find("title")
        return (element.text or "") if element is not None else ""

    @property
    def layers(self) -> list[Layer]:
        """Couches declarees dans <projectlayers>."""
        result = []

        for element in self._root.iterfind("./projectlayers/maplayer"):
            result.append(
                Layer(
                    id=_element_text(element, "id"),
                    name=_element_text(element, "layername"),
                    source=_element_text(element, "datasource"),
                    provider=_element_text(element, "provider"),
                    extent=_parse_extent(element.find("extent")),
                )
            )

        return result

    def find_layer(self, name: str) -> Layer | None:
        """Cherche une couche par nom exact, puis par correspondance partielle.

        La recherche est insensible a la casse : les noms de couches varient
        d'un lot a l'autre.
        """
        target = name.strip().lower()

        for layer in self.layers:
            if layer.name.strip().lower() == target:
                return layer

        for layer in self.layers:
            if target in layer.name.strip().lower():
                return layer

        return None

    def missing_sources(self) -> list[Layer]:
        """Couches fichier dont la source est introuvable sur le disque.

        Les sources relatives sont resolues depuis le dossier du projet, comme
        le fait QGIS.
        """
        base_dir = os.path.dirname(os.path.abspath(self.path))
        missing = []

        for layer in self.layers:
            if not layer.is_file_based:
                continue

            # delimitedtext utilise une URI "file:chemin?options" ;
            # ogr ajoute des options apres un "|" (ex. layername=).
            datasource = parse_datasource(layer.source)
            raw = datasource.path if datasource else layer.source.split("|")[0].strip()
            if not raw:
                continue

            resolved = raw if os.path.isabs(raw) else os.path.join(base_dir, raw)
            if not os.path.exists(resolved):
                missing.append(layer)

        return missing

    def check(self) -> list[str]:
        """Controle le projet et retourne la liste des anomalies.

        Liste vide = projet coherent.
        """
        problems = []

        if not self.layers:
            problems.append("Le projet ne contient aucune couche.")

        for layer in self.missing_sources():
            problems.append(f"Source introuvable pour la couche '{layer.name}' : {layer.source}")

        for layer in self.layers:
            # Une emprise absente est normale pour une couche vectorielle :
            # QGIS la recalcule. Seule une emprise degeneree est signalee.
            if layer.extent is not None and not layer.extent.is_valid:
                if self.layer_extent(layer) is None:
                    problems.append(f"Emprise vide pour la couche '{layer.name}'.")

        return problems

    # -- Modification ------------------------------------------------------

    @property
    def canvas_extent(self) -> Extent | None:
        """Emprise actuellement enregistree pour le canevas."""
        canvas = self._root.find("mapcanvas")
        return None if canvas is None else _parse_extent(canvas.find("extent"))

    def set_canvas_extent(self, extent: Extent) -> None:
        """Ecrit l'emprise du canevas, en creant les balises manquantes."""
        canvas = self._root.find("mapcanvas")
        if canvas is None:
            canvas = ElementTree.SubElement(self._root, "mapcanvas")
            canvas.set("name", "theMapCanvas")

        node = canvas.find("extent")
        if node is None:
            node = ElementTree.SubElement(canvas, "extent")

        for tag, value in (
            ("xmin", extent.xmin), ("ymin", extent.ymin),
            ("xmax", extent.xmax), ("ymax", extent.ymax),
        ):
            child = node.find(tag)
            if child is None:
                child = ElementTree.SubElement(node, tag)
            child.text = repr(float(value))

    def layer_extent(self, layer: Layer) -> Extent | None:
        """Emprise exploitable d'une couche.

        QGIS n'enregistre pas l'emprise des couches vectorielles : elle est
        recalculee en lisant les donnees. On procede de meme quand le bloc
        <extent> est absent ou degenere.
        """
        if layer.extent is not None and layer.extent.is_valid:
            return layer.extent

        base_dir = os.path.dirname(os.path.abspath(self.path))
        bounds = compute_bounds(layer.source, base_dir)
        if bounds is None:
            return None

        computed = Extent(*bounds)
        return computed if computed.is_valid else None

    def pick_zoom_layer(self, candidates: Sequence[str] = ()) -> str:
        """Choisit la couche sur laquelle centrer la carte.

        Les candidats sont essayes dans l'ordre ; le premier dont l'emprise
        est exploitable est retenu. A defaut, on prend la premiere couche de
        donnees utilisable : les fonds de plan (wms, xyz) sont ecartes, leur
        emprise couvrant le monde entier.

        Args:
            candidates: noms de couches par ordre de preference, exacts ou
                partiels.

        Returns:
            Le nom de la couche retenue.

        Raises:
            LookupError: aucune couche n'a d'emprise exploitable.
        """
        for candidate in candidates:
            layer = self.find_layer(candidate)
            if layer is not None and self.layer_extent(layer) is not None:
                return layer.name

        for layer in self.layers:
            if layer.is_file_based and self.layer_extent(layer) is not None:
                return layer.name

        raise LookupError("Aucune couche du projet ne possede d'emprise exploitable.")

    def zoom_to_layer(self, name: str, margin: float = 0.05) -> Extent:
        """Centre la carte sur l'emprise d'une couche.

        L'emprise est lue dans le projet si elle y figure, sinon calculee
        depuis le fichier source de la couche.

        Args:
            name: nom de la couche, exact ou partiel.
            margin: marge autour de l'emprise, en proportion.

        Returns:
            L'emprise appliquee au canevas.

        Raises:
            LookupError: couche absente du projet.
            ValueError: la couche n'a pas d'emprise exploitable.
        """
        layer = self.find_layer(name)
        if layer is None:
            available = ", ".join(sorted(item.name for item in self.layers))
            raise LookupError(f"Couche '{name}' absente. Couches disponibles : {available}")

        base = self.layer_extent(layer)
        if base is None:
            raise ValueError(f"La couche '{layer.name}' n'a pas d'emprise exploitable.")

        extent = base.buffered(margin)
        self.set_canvas_extent(extent)
        return extent

    def set_title(self, title: str) -> None:
        """Met a jour le titre du projet et l'attribut projectname."""
        element = self._root.find("title")
        if element is None:
            element = ElementTree.SubElement(self._root, "title")

        element.text = title
        self._root.set("projectname", title)

    # -- Enregistrement ----------------------------------------------------

    def save_as(self, path: str, update_title: bool = True) -> str:
        """Enregistre le projet sous un nouveau nom.

        Les sources relatives ne restent valides que si la destination est dans
        le meme repertoire que les donnees.

        Args:
            path: chemin cible (.qgz ou .qgs).
            update_title: aligne le titre sur le nom du fichier.

        Returns:
            Le chemin ecrit.
        """
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)

        stem = os.path.splitext(os.path.basename(path))[0]
        if update_title:
            self.set_title(stem)

        payload = ElementTree.tostring(self._root, encoding="utf-8", xml_declaration=True)

        if path.lower().endswith(".qgs"):
            with open(path, "wb") as handle:
                handle.write(payload)
        else:
            # Le .qgs interne prend le nom de l'archive, comme le fait QGIS.
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(f"{stem}.qgs", payload)
                for name, content in self._extra_files.items():
                    archive.writestr(name, content)

        self.path = path
        return path


def _element_text(parent, tag: str) -> str:
    """Texte d'un sous-element, ou chaine vide."""
    child = parent.find(tag)
    return (child.text or "").strip() if child is not None else ""


if __name__ == "__main__":
    # Inspection d'un projet :
    #     uv run python -m modop.services.qgis_project
    #
    # Les imports sont locaux au bloc : le module reste utilisable sur
    # n'importe quel .qgz, sans dependre de l'arborescence AUDIT_SNA.
    import sys

    from modop.constants import ZOOM_LAYER_CANDIDATES
    from modop.path_manager import _qgis_project_path, _qgis_saved_project_path

    INSEE = "45001"
    # Couche de centrage : passee en argument, sinon detectee automatiquement.
    #     python -m modop.services.qgis_project "carto SNA OK"
    ZOOM_LAYER = sys.argv[1] if len(sys.argv) > 1 else None

    project = QgisProject.open(_qgis_project_path())
    titre = project.title or os.path.basename(project.path)
    print(f"[qgis] projet : {titre} ({len(project.layers)} couche(s))")

    # 1. Inventaire, avec l'emprise reelle de chaque couche.
    #    Les couches vectorielles n'en stockent pas : elle est calculee en
    #    lisant le fichier source, ce qui peut prendre un instant.
    for layer in project.layers:
        extent = project.layer_extent(layer)
        if extent is None:
            mesure = "emprise non calculable"
        else:
            mesure = (f"{extent.xmin:12.0f}, {extent.ymin:12.0f} -> "
                      f"{extent.xmax:12.0f}, {extent.ymax:12.0f}"
                      f"   ({extent.xmax - extent.xmin:.0f} x "
                      f"{extent.ymax - extent.ymin:.0f} m)")
        print(f"  - {layer.name:36} [{layer.provider:14}] {mesure}")

    # 2. Controle de coherence
    anomalies = project.check()
    if anomalies:
        for anomalie in anomalies:
            print(f"[qgis] ⚠ {anomalie}")
    else:
        print("[qgis] controle OK : toutes les sources sont accessibles")

    # 3. Centrage sur la commune
    couche = ZOOM_LAYER or project.pick_zoom_layer(ZOOM_LAYER_CANDIDATES)
    print(f"[qgis] emprise avant zoom : {project.canvas_extent}")
    extent = project.zoom_to_layer(couche)
    print(f"[qgis] centrage sur '{couche}' : "
          f"({extent.xmin:.0f}, {extent.ymin:.0f}) -> "
          f"({extent.xmax:.0f}, {extent.ymax:.0f})")

    # 4. Enregistrement selon la convention de nommage
    print(f"[qgis] enregistre : {project.save_as(_qgis_saved_project_path(INSEE))}")