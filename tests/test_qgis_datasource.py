"""Tests du module modop.services.qgis_datasource."""

from __future__ import annotations

import pytest

from modop.services.qgis_datasource import (
    _wkt_points,
    compute_bounds,
    parse_datasource,
)


# ---------------------------------------------------------------------------
# Analyse de l'URI de source
# ---------------------------------------------------------------------------

def test_parse_uri_xy():
    uri = "file:./carto%20DGFIP.csv?type=csv&delimiter=;&decimalPoint=,&xField=X%20DGFIP&yField=Y%20DGFIP&crs=EPSG:2154"
    datasource = parse_datasource(uri)

    assert datasource.path == "./carto DGFIP.csv"
    assert datasource.delimiter == ";"
    assert datasource.x_field == "X DGFIP"
    assert datasource.y_field == "Y DGFIP"
    assert datasource.decimal_point == ","
    assert datasource.crs == "EPSG:2154"
    assert datasource.has_geometry


def test_parse_uri_wkt():
    datasource = parse_datasource("file:./zones.csv?delimiter=;&wktField=zone")

    assert datasource.wkt_field == "zone"
    assert datasource.has_geometry


def test_parse_uri_sans_geometrie():
    assert not parse_datasource("file:./x.csv?delimiter=;").has_geometry


def test_parse_source_non_locale():
    assert parse_datasource("crs=EPSG:3857&type=xyz&url=https://exemple.fr") is None


# ---------------------------------------------------------------------------
# Extraction WKT
# ---------------------------------------------------------------------------

def test_wkt_points():
    assert _wkt_points("LINESTRING (1 2, 3 4)") == [(1.0, 2.0), (3.0, 4.0)]


def test_wkt_points_multilinestring():
    points = _wkt_points("MULTILINESTRING ((682678.47 6737228.91, 683678.47 6738228.91))")
    assert points == [(682678.47, 6737228.91), (683678.47, 6738228.91)]


def test_wkt_points_vide():
    assert _wkt_points("") == []


# ---------------------------------------------------------------------------
# Calcul d'emprise
# ---------------------------------------------------------------------------

def _ecrire(tmp_path, nom, contenu, encoding="utf-8"):
    chemin = tmp_path / nom
    chemin.write_text(contenu, encoding=encoding)
    return str(tmp_path)


def test_bounds_depuis_colonnes_xy(tmp_path):
    base = _ecrire(tmp_path, "points.csv", "id;X;Y\n1;100;200\n2;300;500\n")
    uri = "file:./points.csv?delimiter=;&xField=X&yField=Y"

    assert compute_bounds(uri, base) == (100.0, 200.0, 300.0, 500.0)


def test_bounds_separateur_decimal_virgule(tmp_path):
    base = _ecrire(tmp_path, "p.csv", "id;X;Y\n1;100,5;200,5\n2;300,5;500,5\n")
    uri = "file:./p.csv?delimiter=;&decimalPoint=,&xField=X&yField=Y"

    assert compute_bounds(uri, base) == (100.5, 200.5, 300.5, 500.5)


def test_bounds_ignore_les_lignes_sans_coordonnees(tmp_path):
    """Adresses non geocodees : colonnes vides, frequent dans les exports."""
    base = _ecrire(tmp_path, "p.csv", "id;X;Y\n1;100;200\n2;;\n3;300;500\n")
    uri = "file:./p.csv?delimiter=;&xField=X&yField=Y"

    assert compute_bounds(uri, base) == (100.0, 200.0, 300.0, 500.0)


def test_bounds_depuis_wkt(tmp_path):
    base = _ecrire(
        tmp_path, "zones.csv",
        "nom;zone\nZone 1;MULTILINESTRING ((10 20, 30 40, 10 20))\n",
    )
    uri = "file:./zones.csv?delimiter=;&wktField=zone"

    assert compute_bounds(uri, base) == (10.0, 20.0, 30.0, 40.0)


def test_bounds_encodage_cp1252(tmp_path):
    """Les exports Excel francais ne sont pas en UTF-8."""
    base = _ecrire(tmp_path, "p.csv", "libellé;X;Y\nrue de l'Église;100;200\n",
                   encoding="cp1252")
    uri = "file:./p.csv?delimiter=;&xField=X&yField=Y"

    assert compute_bounds(uri, base) == (100.0, 200.0, 100.0, 200.0)


def test_bounds_colonne_inexistante(tmp_path):
    base = _ecrire(tmp_path, "p.csv", "id;X;Y\n1;100;200\n")
    assert compute_bounds("file:./p.csv?delimiter=;&xField=LON&yField=LAT", base) is None


def test_bounds_fichier_absent(tmp_path):
    assert compute_bounds("file:./absent.csv?xField=X&yField=Y", str(tmp_path)) is None


def test_bounds_source_non_locale(tmp_path):
    assert compute_bounds("type=xyz&url=https://exemple.fr", str(tmp_path)) is None


def test_bounds_fichier_sans_donnees(tmp_path):
    base = _ecrire(tmp_path, "p.csv", "id;X;Y\n")
    assert compute_bounds("file:./p.csv?delimiter=;&xField=X&yField=Y", base) is None