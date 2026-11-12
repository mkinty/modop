"""Tests des extraits BAN et parcelles.

Aucun acces reseau : le telechargement est remplace par des contenus
construits ici.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import zipfile
from xml.etree import ElementTree

import pytest

from modop.services import referentiels
from modop.services.qgis_datasource import compute_bounds, parse_datasource
from modop.services.qgis_project import QgisProject
from modop.services.referentiels import (
    BAN_LAYER,
    PARCELLES_LAYER,
    ReferentielError,
    convert_ban,
    convert_parcelles,
    fetch_referentiels,
    parcelles_url,
    renderer_element,
    to_lambert93,
)

from .conftest import INSEE, LOT

# Extrait reel de la BAN (73001), deux positions d'une meme adresse : la BAN
# fournit a la fois lon/lat et x/y, ce qui sert de reference a la projection.
BAN_BAL = (
    "uid_adresse;cle_interop;commune_insee;commune_nom;commune_deleguee_insee;"
    "commune_deleguee_nom;voie_nom;lieudit_complement_nom;numero;suffixe;position;"
    "x;y;long;lat;cad_parcelles;source;date_der_maj;certification_commune\n"
    '" @a:538ed87b";73001_0001_00548;73001;Aiguebelette-le-Lac;;;Chemin du Boyat;;548;;'
    "entrée;919238.38;6499113.7;5.810736;45.556397;730010000A1864;commune;2023-01-24;1\n"
    '" @a:538ed87b";73001_0001_00548;73001;Aiguebelette-le-Lac;;;Chemin du Boyat;;548;bis;'
    "bâtiment;919216.04;6499151.35;5.810467;45.556743;730010000A1864;commune;2023-01-24;1\n"
    '" @a:aaaa";73999_0001_00001;73999;Ailleurs;;;Rue X;;1;;'
    "entrée;900000;6400000;5.5;45.5;;commune;2023-01-24;1\n"
).encode("utf-8")


def _parcelles_geojson(compress: bool = True) -> bytes:
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "730010000A0070", "commune": "73001", "prefixe": "000",
                               "section": "A", "numero": "70", "contenance": 44030},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [5.81, 45.55], [5.82, 45.55], [5.82, 45.56], [5.81, 45.55],
                ]]},
            },
            {
                "type": "Feature",
                "properties": {"id": "730010000A0071", "commune": "73001"},
                "geometry": {"type": "MultiPolygon", "coordinates": [[[
                    [5.80, 45.54], [5.805, 45.54], [5.805, 45.545], [5.80, 45.54],
                ]]]},
            },
            {"type": "Feature", "properties": {"id": "sans geometrie"}, "geometry": None},
        ],
    }
    payload = json.dumps(data).encode("utf-8")
    return gzip.compress(payload) if compress else payload


# -- Projection ---------------------------------------------------------------


def test_origine_lambert93():
    x, y = to_lambert93(3.0, 46.5)
    assert x == pytest.approx(700000, abs=1e-6)
    assert y == pytest.approx(6600000, abs=1e-6)


@pytest.mark.parametrize("lon, lat, x, y", [
    (5.810736, 45.556397, 919238.38, 6499113.7),     # BAN 73001
    (5.810467, 45.556743, 919216.04, 6499151.35),
])
def test_projection_concorde_avec_la_ban(lon, lat, x, y):
    """La BAN publie lon/lat et x/y : la projection doit les relier.

    Tolerance de 0,5 m : lon/lat sont arrondis a 6 decimales (~8 cm).
    """
    px, py = to_lambert93(lon, lat)
    assert px == pytest.approx(x, abs=0.5)
    assert py == pytest.approx(y, abs=0.5)


# -- URL ----------------------------------------------------------------------


@pytest.mark.parametrize("insee, dossier", [
    ("73001", "/73/73001/"), ("2A004", "/2A/2A004/"), ("97101", "/971/97101/"),
])
def test_url_parcelles_par_departement(insee, dossier):
    assert dossier in parcelles_url(insee)


# -- BAN ---------------------------------------------------------------------


def test_convert_ban_filtre_la_commune_et_ajoute_le_libelle(tmp_path):
    target = tmp_path / "ban.csv"
    assert convert_ban(BAN_BAL, "73001", str(target)) == 2

    with open(target, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))

    assert [row["adresse"] for row in rows] == ["548 Chemin du Boyat", "548 bis Chemin du Boyat"]
    assert {row["commune_insee"] for row in rows} == {"73001"}
    assert "uid_adresse" not in rows[0]


def test_convert_ban_sans_adresse(tmp_path):
    with pytest.raises(ReferentielError, match="aucune adresse"):
        convert_ban(BAN_BAL, "45001", str(tmp_path / "ban.csv"))


def test_convert_ban_sans_coordonnees(tmp_path):
    with pytest.raises(ReferentielError, match="x / y"):
        convert_ban(b"<html>erreur</html>", "73001", str(tmp_path / "ban.csv"))


def test_extrait_ban_lisible_par_la_couche(tmp_path):
    """L'URI de la couche doit retrouver les colonnes du fichier ecrit."""
    target = tmp_path / f"{BAN_LAYER.name}.csv"
    convert_ban(BAN_BAL, "73001", str(target))

    datasource = parse_datasource(BAN_LAYER.datasource)
    assert datasource.path == f"./{BAN_LAYER.name}.csv"
    bounds = compute_bounds(BAN_LAYER.datasource, str(tmp_path))
    assert bounds == pytest.approx((919216.04, 6499113.7, 919238.38, 6499151.35))


# -- Parcelles -----------------------------------------------------------------


@pytest.mark.parametrize("compress", [True, False])
def test_convert_parcelles(tmp_path, compress):
    target = tmp_path / "parcelles.csv"
    assert convert_parcelles(_parcelles_geojson(compress), str(target)) == 2

    with open(target, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))

    assert rows[0]["id"] == "730010000A0070"
    assert rows[0]["contenance"] == "44030"
    assert all(row["geometrie"].startswith("MULTIPOLYGON (((") for row in rows)


def test_parcelles_projetees_en_lambert93(tmp_path):
    """L'emprise doit etre en metres, pas en degres."""
    target = tmp_path / f"{PARCELLES_LAYER.name}.csv"
    convert_parcelles(_parcelles_geojson(), str(target))

    xmin, ymin, xmax, ymax = compute_bounds(PARCELLES_LAYER.datasource, str(tmp_path))
    # Sommet le plus a l'ouest et le plus au sud : (5.80, 45.54).
    assert (xmin, ymin) == pytest.approx(to_lambert93(5.80, 45.54), abs=0.01)
    assert 900000 < xmin < xmax < 1000000
    assert 6400000 < ymin < ymax < 6600000


@pytest.mark.parametrize("payload", [b"pas du json", gzip.compress(b"{}"),
                                     json.dumps({"features": []}).encode()])
def test_convert_parcelles_contenu_invalide(tmp_path, payload):
    target = tmp_path / "parcelles.csv"
    with pytest.raises(ReferentielError):
        convert_parcelles(payload, str(target))
    assert not target.exists()


# -- Point d'entree --------------------------------------------------------------


@pytest.fixture
def fake_download(monkeypatch):
    """Remplace le telechargement. Renvoie le dictionnaire url -> contenu."""
    contenus: dict[str, bytes | Exception] = {}
    appels: list[str] = []

    def _download(url, timeout=None):
        appels.append(url)
        for motif, contenu in contenus.items():
            if motif in url:
                if isinstance(contenu, Exception):
                    raise contenu
                return contenu
        raise ReferentielError(f"HTTP 404 sur {url}")

    monkeypatch.setattr(referentiels, "_download", _download)
    contenus["appels"] = appels  # type: ignore[assignment]
    return contenus


def test_fetch_referentiels_ecrit_les_deux_fichiers(bureau, fake_download):
    from modop.path_manager import _ban_csv_path, _parcelles_csv_path, _workspace_path

    os.makedirs(_workspace_path())
    fake_download["csv-bal"] = BAN_BAL
    fake_download["parcelles"] = _parcelles_geojson()

    bilan = fetch_referentiels("73001", verbose=False)

    assert (bilan.adresses, bilan.parcelles) == (2, 2)
    assert bilan.layers == [BAN_LAYER, PARCELLES_LAYER]
    assert not bilan.warnings
    assert os.path.isfile(_ban_csv_path())
    assert os.path.isfile(_parcelles_csv_path())
    # Un fichier par commune : aucune URL departementale.
    assert all("73001" in url for url in fake_download["appels"])


def test_fetch_referentiels_independants(bureau, fake_download):
    """La BAN indisponible n'empeche pas les parcelles."""
    from modop.path_manager import _workspace_path

    os.makedirs(_workspace_path())
    fake_download["csv-bal"] = ReferentielError("telechargement impossible (timeout)")
    fake_download["parcelles"] = _parcelles_geojson()

    bilan = fetch_referentiels("73001", verbose=False)

    assert bilan.layers == [PARCELLES_LAYER]
    assert len(bilan.warnings) == 1
    assert "carto BAN" in bilan.warnings[0]


def test_download_signale_une_erreur_reseau(monkeypatch):
    import urllib.error

    def _urlopen(*_args, **_kwargs):
        raise urllib.error.URLError("hors ligne")

    monkeypatch.setattr(referentiels.urllib.request, "urlopen", _urlopen)
    with pytest.raises(ReferentielError, match="hors ligne"):
        referentiels._download("https://exemple.invalid/x")


# -- Ajout au projet QGIS ---------------------------------------------------------


def _basemap_layers(default_layers):
    return [
        *default_layers,
        {"id": "osm_001", "name": "OpenStreetMap", "source": "type=xyz&url=x",
         "provider": "wms", "extent": (-1e7, -1e7, 1e7, 1e7)},
    ]


def test_add_vector_layer_declare_la_couche(tmp_path, make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", _basemap_layers(default_layers)))

    layer_id = project.add_vector_layer(BAN_LAYER.name, BAN_LAYER.datasource,
                                        "delimitedtext", "Point", renderer_element(BAN_LAYER))

    assert layer_id.startswith("carto_BAN_")
    layer = project.find_layer("carto BAN")
    assert layer is not None and layer.provider == "delimitedtext"
    assert layer.source == BAN_LAYER.datasource

    # Arbre des couches : au-dessus du fond de plan.
    tree = [node.get("name") for node in project._root.iter("layer-tree-layer")]
    assert tree.index("carto BAN") == tree.index("OpenStreetMap") - 1


def test_add_vector_layer_respecte_la_couche_du_modele(tmp_path, make_qgz, default_layers):
    layers = [*default_layers, {"id": "ban_perso", "name": "carto BAN",
                                "source": "file:./carto%20BAN.csv", "provider": "delimitedtext"}]
    project = QgisProject.open(make_qgz("p.qgz", layers))

    assert project.add_vector_layer("carto BAN", BAN_LAYER.datasource, "delimitedtext",
                                    "Point", renderer_element(BAN_LAYER)) == ""
    assert [layer.id for layer in project.layers if layer.name == "carto BAN"] == ["ban_perso"]


def test_couches_ajoutees_survivent_a_l_enregistrement(tmp_path, make_qgz, default_layers):
    """Apres save_as, le projet relu contient les couches et des sources valides."""
    convert_ban(BAN_BAL, "73001", str(tmp_path / f"{BAN_LAYER.name}.csv"))
    convert_parcelles(_parcelles_geojson(), str(tmp_path / f"{PARCELLES_LAYER.name}.csv"))

    project = QgisProject.open(make_qgz("p.qgz", _basemap_layers(default_layers)))
    for spec in (BAN_LAYER, PARCELLES_LAYER):
        project.add_vector_layer(spec.name, spec.datasource, "delimitedtext",
                                 spec.geometry, renderer_element(spec))
    saved = project.save_as(str(tmp_path / "carte_audit 73001.qgz"))

    reread = QgisProject.open(saved)
    assert reread.has_layer("carto BAN") and reread.has_layer("carto parcelles")
    assert not [layer.name for layer in reread.missing_sources()
                if layer.name.startswith("carto ")]

    with zipfile.ZipFile(saved) as archive:
        root = ElementTree.fromstring(archive.read("carte_audit 73001.qgs"))
    symbols = {layer.findtext("layername"): layer.find("./renderer-v2/symbols/symbol").get("type")
               for layer in root.iter("maplayer") if layer.find("renderer-v2") is not None}
    assert symbols == {"carto BAN": "marker", "carto parcelles": "fill"}


# -- Workflow ----------------------------------------------------------------------


def test_workflow_embarque_les_referentiels(commune_files, fake_download):
    from modop.services.workflow import prepare_commune_deliverable

    fake_download["csv-bal"] = BAN_BAL.replace(b"73001", INSEE.encode())
    fake_download["parcelles"] = _parcelles_geojson()

    result = prepare_commune_deliverable(LOT, INSEE, zoom_layer="communes", sort_excel=False,
                                         add_referentiels=True, verbose=False)

    assert (result.adresses_ban, result.parcelles) == (2, 2)
    with zipfile.ZipFile(result.archive_file) as archive:
        names = set(archive.namelist())
    assert {"carto BAN.csv", "carto parcelles.csv"} <= names

    project = QgisProject.open(result.project_file)
    assert project.has_layer("carto BAN") and project.has_layer("carto parcelles")


def test_workflow_sans_reseau_produit_le_livrable(commune_files, fake_download):
    from modop.services.workflow import prepare_commune_deliverable

    result = prepare_commune_deliverable(LOT, INSEE, zoom_layer="communes", sort_excel=False,
                                         add_referentiels=True, verbose=False)

    assert result.ok
    assert len([w for w in result.warnings if "non produite" in w]) == 2
    project = QgisProject.open(result.project_file)
    assert not project.has_layer("carto BAN")


def test_workflow_desactive_par_defaut(commune_files, fake_download):
    from modop.services.workflow import prepare_commune_deliverable

    prepare_commune_deliverable(LOT, INSEE, zoom_layer="communes", sort_excel=False,
                                verbose=False)
    assert fake_download["appels"] == []
