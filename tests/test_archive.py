"""Tests du module modop.services.archive."""

from __future__ import annotations

import os
import zipfile

import pytest

from modop.path_manager import _deliverable_archive_path, _workspace_path
from modop.services.archive import (
    build_deliverable_archive,
    collect_deliverable_files,
    create_zip,
)
from modop.services.files import copy_commune_files
from tests.conftest import INSEE, LOT


# ---------------------------------------------------------------------------
# create_zip
# ---------------------------------------------------------------------------

def test_create_zip_a_plat(tmp_path):
    fichiers = []
    for nom in ("a.csv", "b.csv"):
        chemin = tmp_path / "data" / nom
        chemin.parent.mkdir(exist_ok=True)
        chemin.write_text("x", encoding="utf-8")
        fichiers.append(str(chemin))

    archive_path = str(tmp_path / "livrable.zip")
    create_zip(archive_path, fichiers, verbose=False)

    with zipfile.ZipFile(archive_path) as archive:
        assert sorted(archive.namelist()) == ["a.csv", "b.csv"]


def test_create_zip_liste_vide(tmp_path):
    with pytest.raises(ValueError, match="Aucun fichier"):
        create_zip(str(tmp_path / "v.zip"), [], verbose=False)


def test_create_zip_fichier_absent(tmp_path):
    with pytest.raises(FileNotFoundError, match="introuvable"):
        create_zip(str(tmp_path / "v.zip"), [str(tmp_path / "absent.csv")], verbose=False)


def test_create_zip_refuse_les_homonymes(tmp_path):
    """Une archive a plat ecraserait silencieusement le doublon."""
    fichiers = []
    for dossier in ("d1", "d2"):
        chemin = tmp_path / dossier / "a.csv"
        chemin.parent.mkdir()
        chemin.write_text("x", encoding="utf-8")
        fichiers.append(str(chemin))

    with pytest.raises(ValueError, match="double"):
        create_zip(str(tmp_path / "v.zip"), fichiers, verbose=False)


def test_create_zip_cree_le_repertoire(tmp_path):
    source = tmp_path / "a.csv"
    source.write_text("x", encoding="utf-8")
    cible = str(tmp_path / "sous" / "dossier" / "v.zip")

    create_zip(cible, [str(source)], verbose=False)
    assert os.path.isfile(cible)


# ---------------------------------------------------------------------------
# collect_deliverable_files
# ---------------------------------------------------------------------------

def test_collecte_les_csv_et_le_projet(commune_files, make_qgz, default_layers):
    copy_commune_files(LOT, INSEE, verbose=False)
    projet = make_qgz("carte_audit_45001.qgz", default_layers,
                      directory=_workspace_path())

    fichiers = collect_deliverable_files(projet, _workspace_path())
    noms = sorted(os.path.basename(p) for p in fichiers)

    assert noms == ["adresses.csv", "carte_audit_45001.qgz", "maillage.csv"]


def test_collecte_exclut_les_autres_extensions(commune_files, make_qgz, default_layers):
    """Le .gpkg et le .txt ne font pas partie du livrable."""
    copy_commune_files(LOT, INSEE, verbose=False)
    projet = make_qgz("carte_audit_45001.qgz", default_layers,
                      directory=_workspace_path())

    noms = [os.path.basename(p) for p in collect_deliverable_files(projet, _workspace_path())]
    assert "communes.gpkg" not in noms
    assert "notes.txt" not in noms


def test_collecte_projet_absent(bureau, tmp_path):
    with pytest.raises(FileNotFoundError, match="introuvable"):
        collect_deliverable_files(str(tmp_path / "absent.qgz"), str(tmp_path))


def test_collecte_sans_doublon_si_le_projet_est_deja_liste(commune_files, tmp_path):
    """Le projet ne doit pas apparaitre deux fois s'il est aussi collecte."""
    projet = tmp_path / "carte_audit_45001.csv"
    projet.write_text("x", encoding="utf-8")

    fichiers = collect_deliverable_files(str(projet), str(tmp_path))
    assert fichiers.count(str(projet)) == 1


# ---------------------------------------------------------------------------
# build_deliverable_archive
# ---------------------------------------------------------------------------

def test_archive_deposee_dans_le_dossier_carte(commune_files, make_qgz, default_layers):
    copy_commune_files(LOT, INSEE, verbose=False)
    projet = make_qgz("carte_audit_45001.qgz", default_layers,
                      directory=_workspace_path())

    resultat = build_deliverable_archive(INSEE, projet, _workspace_path(), verbose=False)
    nom = os.path.basename(resultat)

    assert resultat == _deliverable_archive_path(INSEE)
    assert os.path.isfile(resultat)
    assert os.path.basename(os.path.dirname(resultat)) == "Carte"

    # Le libellé est fixé par path_manager ; on vérifie le contrat : le nom
    # porte le code INSEE et l'extension d'archive.
    assert INSEE in nom
    assert nom.endswith(".zip")


def test_archive_intermediaire_suit_le_meme_nom(commune_files, make_qgz, default_layers):
    """L'archive de transit ne doit pas garder un nom d'une autre convention."""
    copy_commune_files(LOT, INSEE, verbose=False)
    projet = make_qgz("carte_audit 45001.qgz", default_layers,
                      directory=_workspace_path())

    resultat = build_deliverable_archive(INSEE, projet, _workspace_path(), verbose=False)
    transit = os.path.join(_workspace_path(), os.path.basename(resultat))

    assert os.path.isfile(transit)
    # Aucune archive orpheline sous un autre nom.
    archives = [n for n in os.listdir(_workspace_path()) if n.endswith(".zip")]
    assert archives == [os.path.basename(resultat)]


def test_contenu_de_l_archive(commune_files, make_qgz, default_layers):
    copy_commune_files(LOT, INSEE, verbose=False)
    projet = make_qgz("carte_audit_45001.qgz", default_layers,
                      directory=_workspace_path())

    resultat = build_deliverable_archive(INSEE, projet, _workspace_path(), verbose=False)

    with zipfile.ZipFile(resultat) as archive:
        assert sorted(archive.namelist()) == [
            "adresses.csv", "carte_audit_45001.qgz", "maillage.csv",
        ]


def test_archive_destination_personnalisee(commune_files, make_qgz, default_layers, tmp_path):
    copy_commune_files(LOT, INSEE, verbose=False)
    projet = make_qgz("carte_audit_45001.qgz", default_layers,
                      directory=_workspace_path())
    cible = str(tmp_path / "ailleurs" / "livrable.zip")

    assert build_deliverable_archive(
        INSEE, projet, _workspace_path(), destination=cible, verbose=False
    ) == cible
    assert os.path.isfile(cible)