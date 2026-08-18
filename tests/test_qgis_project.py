"""Tests du module modop.services.qgis_project."""

from __future__ import annotations

import os
import zipfile

import pytest

from modop.services.qgis_project import Extent, QgisProject


# ---------------------------------------------------------------------------
# Extent
# ---------------------------------------------------------------------------

def test_extent_valide():
    assert Extent(0, 0, 10, 10).is_valid
    assert not Extent(0, 0, 0, 10).is_valid       # largeur nulle
    assert not Extent(10, 0, 0, 10).is_valid      # bornes inversees


def test_extent_buffered():
    assert Extent(0, 0, 10, 10).buffered(0.1) == Extent(-1.0, -1.0, 11.0, 11.0)


def test_extent_buffered_sans_marge():
    origine = Extent(0, 0, 10, 10)
    assert origine.buffered(0) == origine


# ---------------------------------------------------------------------------
# Ouverture
# ---------------------------------------------------------------------------

def test_ouvre_un_qgz(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))

    assert project.title == "carte_audit_maillage"
    assert [layer.name for layer in project.layers] == ["communes", "adresses_45001"]


def test_lit_les_attributs_de_couche(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    couche = project.layers[0]

    assert couche.id == "communes_001"
    assert couche.provider == "ogr"
    assert couche.extent == Extent(600000, 6700000, 610000, 6710000)
    assert couche.is_file_based


def test_fichier_absent(tmp_path):
    with pytest.raises(FileNotFoundError, match="introuvable"):
        QgisProject.open(str(tmp_path / "absent.qgz"))


def test_archive_sans_qgs(tmp_path):
    path = tmp_path / "vide.qgz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("lisezmoi.txt", "rien")

    with pytest.raises(ValueError, match="Aucun fichier"):
        QgisProject.open(str(path))


# ---------------------------------------------------------------------------
# Recherche de couche
# ---------------------------------------------------------------------------

def test_find_layer_nom_exact(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    assert project.find_layer("communes").id == "communes_001"


def test_find_layer_insensible_a_la_casse(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    assert project.find_layer("COMMUNES") is not None


def test_find_layer_correspondance_partielle(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    assert project.find_layer("adresses").name == "adresses_45001"


def test_find_layer_absente(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    assert project.find_layer("parcelles") is None


# ---------------------------------------------------------------------------
# Controles
# ---------------------------------------------------------------------------

def test_check_signale_les_sources_manquantes(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    problemes = project.check()

    assert len(problemes) == 2
    assert all("Source introuvable" in message for message in problemes)


def test_check_ok_quand_les_sources_existent(make_qgz, default_layers, tmp_path):
    for nom in ("communes.gpkg", "adresses.csv"):
        (tmp_path / nom).write_text("x", encoding="utf-8")

    project = QgisProject.open(make_qgz("p.qgz", default_layers, directory=tmp_path))
    assert project.check() == []


def test_check_ignore_les_providers_distants(make_qgz, tmp_path):
    couches = [{
        "id": "wms_1", "name": "fond", "provider": "wms",
        "source": "url=https://exemple.fr/wms", "extent": (0, 0, 10, 10),
    }]
    project = QgisProject.open(make_qgz("p.qgz", couches, directory=tmp_path))

    assert project.check() == []


def test_check_ignore_les_options_ogr(make_qgz, tmp_path):
    """La source ogr peut porter des options apres un '|'."""
    (tmp_path / "data.gpkg").write_text("x", encoding="utf-8")
    couches = [{
        "id": "c1", "name": "communes", "provider": "ogr",
        "source": "./data.gpkg|layername=communes", "extent": (0, 0, 10, 10),
    }]
    project = QgisProject.open(make_qgz("p.qgz", couches, directory=tmp_path))

    assert project.check() == []


def test_check_projet_sans_couche(make_qgz):
    project = QgisProject.open(make_qgz("p.qgz", []))
    assert "aucune couche" in project.check()[0].lower()


def test_check_signale_une_emprise_vide(make_qgz, tmp_path):
    (tmp_path / "data.gpkg").write_text("x", encoding="utf-8")
    couches = [{
        "id": "c1", "name": "communes", "provider": "ogr",
        "source": "./data.gpkg", "extent": (0, 0, 0, 0),
    }]
    project = QgisProject.open(make_qgz("p.qgz", couches, directory=tmp_path))

    assert "Emprise vide" in project.check()[0]


# ---------------------------------------------------------------------------
# Zoom
# ---------------------------------------------------------------------------

def test_zoom_applique_l_emprise_de_la_couche(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    emprise = project.zoom_to_layer("communes", margin=0)

    assert emprise == Extent(600000, 6700000, 610000, 6710000)
    assert project.canvas_extent == emprise


def test_zoom_applique_la_marge(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    emprise = project.zoom_to_layer("communes", margin=0.1)

    assert emprise.xmin == pytest.approx(599000)
    assert emprise.xmax == pytest.approx(611000)


def test_zoom_couche_absente(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))

    with pytest.raises(LookupError, match="parcelles"):
        project.zoom_to_layer("parcelles")


def test_zoom_couche_sans_emprise(make_qgz):
    couches = [{"id": "c1", "name": "communes", "provider": "ogr",
                "source": "./x.gpkg", "extent": None}]
    project = QgisProject.open(make_qgz("p.qgz", couches))

    with pytest.raises(ValueError, match="emprise"):
        project.zoom_to_layer("communes")


def test_zoom_cree_le_bloc_extent_absent(make_qgz, default_layers, tmp_path):
    """Le canevas peut n'avoir aucune emprise enregistree."""
    path = make_qgz("p.qgz", default_layers)
    project = QgisProject.open(path)
    project._root.remove(project._root.find("mapcanvas"))

    project.zoom_to_layer("communes", margin=0)
    assert project.canvas_extent == Extent(600000, 6700000, 610000, 6710000)


# ---------------------------------------------------------------------------
# Enregistrement
# ---------------------------------------------------------------------------

def test_save_as_respecte_la_convention_de_nommage(make_qgz, default_layers, tmp_path):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    cible = str(tmp_path / "carte_audit_45001.qgz")

    assert project.save_as(cible) == cible
    assert os.path.isfile(cible)


def test_save_as_nomme_le_qgs_interne_comme_l_archive(make_qgz, default_layers, tmp_path):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    cible = str(tmp_path / "carte_audit_45001.qgz")
    project.save_as(cible)

    with zipfile.ZipFile(cible) as archive:
        assert "carte_audit_45001.qgs" in archive.namelist()


def test_save_as_met_a_jour_le_titre(make_qgz, default_layers, tmp_path):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    cible = str(tmp_path / "carte_audit_45001.qgz")
    project.save_as(cible)

    assert QgisProject.open(cible).title == "carte_audit_45001"


def test_save_as_conserve_le_titre_si_demande(make_qgz, default_layers, tmp_path):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    cible = str(tmp_path / "carte_audit_45001.qgz")
    project.save_as(cible, update_title=False)

    assert QgisProject.open(cible).title == "carte_audit_maillage"


def test_save_as_conserve_les_fichiers_annexes(make_qgz, default_layers, tmp_path):
    """Le .qgd (stockage auxiliaire) doit suivre le projet."""
    source = make_qgz("p.qgz", default_layers, extra={"p.qgd": b"donnees auxiliaires"})
    project = QgisProject.open(source)
    cible = str(tmp_path / "carte_audit_45001.qgz")
    project.save_as(cible)

    with zipfile.ZipFile(cible) as archive:
        assert archive.read("p.qgd") == b"donnees auxiliaires"


def test_save_as_relit_le_zoom(make_qgz, default_layers, tmp_path):
    """Aller-retour complet : le zoom survit a l'enregistrement."""
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    project.zoom_to_layer("communes", margin=0)
    cible = str(tmp_path / "carte_audit_45001.qgz")
    project.save_as(cible)

    assert QgisProject.open(cible).canvas_extent == Extent(600000, 6700000, 610000, 6710000)


def test_save_as_conserve_les_couches(make_qgz, default_layers, tmp_path):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    cible = str(tmp_path / "carte_audit_45001.qgz")
    project.save_as(cible)

    relu = QgisProject.open(cible)
    assert [c.name for c in relu.layers] == ["communes", "adresses_45001"]
    assert relu.layers[0].source == "./communes.gpkg"


def test_save_as_cree_le_repertoire(make_qgz, default_layers, tmp_path):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    cible = str(tmp_path / "nouveau" / "dossier" / "carte_audit_45001.qgz")

    project.save_as(cible)
    assert os.path.isfile(cible)


def test_save_as_ne_modifie_pas_la_source(make_qgz, default_layers, tmp_path):
    source = make_qgz("p.qgz", default_layers)
    empreinte = os.path.getsize(source)

    project = QgisProject.open(source)
    project.zoom_to_layer("communes")
    project.save_as(str(tmp_path / "carte_audit_45001.qgz"))

    assert os.path.getsize(source) == empreinte
    assert QgisProject.open(source).canvas_extent == Extent(0, 0, 1, 1)


# ---------------------------------------------------------------------------
# Choix de la couche de centrage
# ---------------------------------------------------------------------------

def test_pick_zoom_layer_respecte_l_ordre_des_candidats(make_qgz, default_layers):
    project = QgisProject.open(make_qgz("p.qgz", default_layers))
    assert project.pick_zoom_layer(("adresses", "communes")) == "adresses_45001"


def test_pick_zoom_layer_ignore_un_candidat_sans_emprise(make_qgz, default_layers, tmp_path):
    couches = [
        {"id": "v1", "name": "vide", "provider": "ogr", "source": "./x.gpkg", "extent": None},
        *default_layers,
    ]
    project = QgisProject.open(make_qgz("p.qgz", couches, directory=tmp_path))

    assert project.pick_zoom_layer(("vide", "communes")) == "communes"


def test_pick_zoom_layer_ecarte_les_fonds_de_plan(make_qgz, tmp_path):
    """Un fond de plan couvre le monde : il ne doit jamais servir de repli."""
    (tmp_path / "data.csv").write_text("id;X;Y\n1;100;200\n2;300;500\n", encoding="utf-8")
    couches = [
        {"id": "w1", "name": "Google Satellite", "provider": "wms",
         "source": "type=xyz&url=https://exemple.fr",
         "extent": (-20037508, -20037508, 20037508, 20037508)},
        {"id": "d1", "name": "carto SNA OK", "provider": "delimitedtext",
         "source": "file:./data.csv?delimiter=;&xField=X&yField=Y", "extent": None},
    ]
    project = QgisProject.open(make_qgz("p.qgz", couches, directory=tmp_path))

    assert project.pick_zoom_layer() == "carto SNA OK"


def test_pick_zoom_layer_calcule_l_emprise_si_absente(make_qgz, tmp_path):
    """Les couches vectorielles ne stockent pas d'emprise : elle est calculee."""
    (tmp_path / "zones.csv").write_text(
        "nom;zone\nZ1;MULTILINESTRING ((10 20, 30 40))\n", encoding="utf-8")
    couches = [{
        "id": "m1", "name": "carto maillage principal", "provider": "delimitedtext",
        "source": "file:./zones.csv?delimiter=;&wktField=zone", "extent": None,
    }]
    project = QgisProject.open(make_qgz("p.qgz", couches, directory=tmp_path))

    assert project.pick_zoom_layer(("carto maillage principal",)) == "carto maillage principal"
    assert project.zoom_to_layer("carto maillage principal", margin=0) == Extent(10, 20, 30, 40)


def test_pick_zoom_layer_aucune_couche_exploitable(make_qgz, tmp_path):
    couches = [{"id": "v1", "name": "vide", "provider": "ogr",
                "source": "./absent.gpkg", "extent": None}]
    project = QgisProject.open(make_qgz("p.qgz", couches, directory=tmp_path))

    with pytest.raises(LookupError, match="emprise exploitable"):
        project.pick_zoom_layer()