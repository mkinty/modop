"""Calcul de l'emprise reelle d'une couche a partir de sa source de donnees.

QGIS n'enregistre pas l'emprise des couches vectorielles dans le .qgs : il la
recalcule en lisant les donnees a l'ouverture du projet. Seules les couches
raster et WMS portent un bloc <extent>.

Ce module reproduit ce calcul pour les couches delimitedtext (CSV), en
exploitant les parametres de l'URI de source :

    file:./carto SNA OK.csv?type=csv&delimiter=;&xField=X_lambert93&...

Deux modes de geometrie sont pris en charge :
    - colonnes X / Y   (xField, yField) ;
    - colonne WKT      (wktField), pour les traits et les zones du maillage.

Limite : aucune reprojection. Si le CRS d'une couche differe de celui du
projet, l'emprise calculee est dans le CRS de la couche.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

#: Nombres extraits d'une geometrie WKT (entiers, decimaux, notation exposant).
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

#: Taille max du champ CSV : les WKT de zones depassent la limite par defaut.
csv.field_size_limit(10_000_000)


@dataclass(frozen=True)
class DataSource:
    """URI de source decomposee."""

    path: str
    delimiter: str = ";"
    x_field: str = ""
    y_field: str = ""
    wkt_field: str = ""
    decimal_point: str = "."
    crs: str = ""

    @property
    def has_geometry(self) -> bool:
        """Vrai si la source declare de quoi construire une geometrie."""
        return bool(self.wkt_field) or bool(self.x_field and self.y_field)


def parse_datasource(source: str) -> DataSource | None:
    """Decompose l'URI de source d'une couche delimitedtext.

    Args:
        source: contenu de <datasource>, par exemple
            "file:./carto DGFIP.csv?type=csv&delimiter=;&xField=X DGFIP&...".

    Returns:
        Un DataSource, ou None si l'URI ne designe pas un fichier local.

    Examples:
        >>> ds = parse_datasource("file:./a.csv?delimiter=;&xField=X&yField=Y")
        >>> ds.path, ds.x_field, ds.y_field
        ('./a.csv', 'X', 'Y')
    """
    if not source.startswith("file:"):
        return None

    parsed = urlparse(source)
    params = parse_qs(parsed.query)

    def first(name: str, default: str = "") -> str:
        # parse_qs decode deja les %20 ; les valeurs sont des listes.
        values = params.get(name)
        return values[0] if values else default

    return DataSource(
        path=unquote(parsed.path),
        delimiter=first("delimiter", ";"),
        x_field=first("xField"),
        y_field=first("yField"),
        wkt_field=first("wktField"),
        decimal_point=first("decimalPoint", "."),
        crs=first("crs"),
    )


def _to_float(text: str, decimal_point: str) -> float | None:
    """Convertit une coordonnee texte, en tenant compte du separateur decimal."""
    cleaned = text.strip()
    if not cleaned:
        return None

    if decimal_point == ",":
        cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        return None


def _wkt_points(wkt: str) -> list[tuple[float, float]]:
    """Extrait les couples de coordonnees d'une geometrie WKT 2D.

    >>> _wkt_points("LINESTRING (1 2, 3 4)")
    [(1.0, 2.0), (3.0, 4.0)]
    """
    numbers = [float(value) for value in _NUMBER_RE.findall(wkt)]
    # Les coordonnees vont par paires ; un nombre isole en fin est ignore.
    return list(zip(numbers[0::2], numbers[1::2]))


def _resolve(path: str, base_dir: str) -> str:
    """Resout un chemin relatif depuis le dossier du projet, comme QGIS."""
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))


def compute_bounds(source: str, base_dir: str) -> tuple[float, float, float, float] | None:
    """Calcule l'emprise d'une couche en lisant son fichier source.

    Args:
        source: contenu de <datasource>.
        base_dir: dossier du projet, pour resoudre les chemins relatifs.

    Returns:
        (xmin, ymin, xmax, ymax), ou None si l'emprise n'est pas calculable :
        source non locale, fichier absent, colonnes declarees introuvables,
        ou aucune coordonnee exploitable.
    """
    datasource = parse_datasource(source)
    if datasource is None or not datasource.has_geometry:
        return None

    path = _resolve(datasource.path, base_dir)
    if not os.path.isfile(path):
        return None

    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    found = False

    with _open_csv(path) as handle:
        reader = csv.DictReader(handle, delimiter=datasource.delimiter)

        for row in reader:
            for x, y in _row_points(row, datasource):
                found = True
                xmin, xmax = min(xmin, x), max(xmax, x)
                ymin, ymax = min(ymin, y), max(ymax, y)

    return (xmin, ymin, xmax, ymax) if found else None


def _open_csv(path: str):
    """Ouvre un CSV en devinant son encodage.

    utf-8-sig couvre les exports UTF-8 avec BOM ; cp1252 prend le relais pour
    les exports Excel francais, dont les accents feraient echouer la lecture
    des noms de colonnes.
    """
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            handle = open(path, newline="", encoding=encoding)
            handle.read(8192)
            handle.seek(0)
            return handle
        except UnicodeDecodeError:
            handle.close()

    return open(path, newline="", encoding="utf-8", errors="replace")


def _row_points(row: dict, datasource: DataSource) -> list[tuple[float, float]]:
    """Coordonnees portees par une ligne du CSV."""
    if datasource.wkt_field:
        wkt = row.get(datasource.wkt_field) or ""
        return _wkt_points(wkt) if wkt.strip() else []

    x = _to_float(row.get(datasource.x_field) or "", datasource.decimal_point)
    y = _to_float(row.get(datasource.y_field) or "", datasource.decimal_point)

    # Les lignes sans coordonnees sont frequentes (adresse non geocodee).
    return [(x, y)] if x is not None and y is not None else []