"""Tests du module modop.services.files."""

from __future__ import annotations

import os

import pytest

from modop.path_manager import _insee_qgis_path, _workspace_path
from modop.services.files import copy_commune_files, find_files
from tests.conftest import INSEE, LOT


def test_copie_tous_les_fichiers(commune_files):
    copies = copy_commune_files(LOT, INSEE, verbose=False)

    noms = sorted(os.path.basename(path) for path in copies)
    assert noms == ["adresses.csv", "communes.gpkg", "maillage.csv", "notes.txt"]
    assert all(os.path.isfile(path) for path in copies)


def test_copie_vers_le_workspace_par_defaut(commune_files):
    copies = copy_commune_files(LOT, INSEE, verbose=False)
    workspace = _workspace_path()

    assert all(os.path.dirname(path) == workspace for path in copies)


def test_ecrase_les_fichiers_existants(commune_files):
    """Les versions preparees remplacent celles deja presentes."""
    cible = os.path.join(_workspace_path(), "adresses.csv")
    with open(cible, "w", encoding="utf-8") as handle:
        handle.write("ancienne version")

    copy_commune_files(LOT, INSEE, verbose=False)

    with open(cible, encoding="utf-8") as handle:
        assert handle.read() == "id;zone\n1;A\n"


def test_overwrite_false_conserve_l_existant(commune_files):
    cible = os.path.join(_workspace_path(), "adresses.csv")
    with open(cible, "w", encoding="utf-8") as handle:
        handle.write("ancienne version")

    copies = copy_commune_files(LOT, INSEE, overwrite=False, verbose=False)

    assert cible not in copies
    with open(cible, encoding="utf-8") as handle:
        assert handle.read() == "ancienne version"


def test_reproduit_les_sous_dossiers(commune_files):
    sous_dossier = os.path.join(_insee_qgis_path(LOT, INSEE), "styles")
    os.makedirs(sous_dossier, exist_ok=True)
    with open(os.path.join(sous_dossier, "style.qml"), "w", encoding="utf-8") as handle:
        handle.write("<qgis/>")

    copy_commune_files(LOT, INSEE, verbose=False)

    assert os.path.isfile(os.path.join(_workspace_path(), "styles", "style.qml"))


def test_destination_personnalisee(commune_files, tmp_path):
    cible = tmp_path / "ailleurs"
    copies = copy_commune_files(LOT, INSEE, destination=str(cible), verbose=False)

    assert all(str(cible) in path for path in copies)


def test_source_absente_leve_une_erreur(bureau):
    with pytest.raises(FileNotFoundError, match="introuvable"):
        copy_commune_files(LOT, "99999", verbose=False)


def test_source_intacte_apres_copie(commune_files):
    source_dir = _insee_qgis_path(LOT, INSEE)
    avant = sorted(os.listdir(source_dir))

    copy_commune_files(LOT, INSEE, verbose=False)

    assert sorted(os.listdir(source_dir)) == avant


# ---------------------------------------------------------------------------
# find_files
# ---------------------------------------------------------------------------

def test_find_files_filtre_sur_l_extension(commune_files):
    copy_commune_files(LOT, INSEE, verbose=False)
    trouves = find_files(_workspace_path(), (".csv",))

    assert sorted(os.path.basename(p) for p in trouves) == ["adresses.csv", "maillage.csv"]


def test_find_files_insensible_a_la_casse(bureau, tmp_path):
    (tmp_path / "A.CSV").write_text("x", encoding="utf-8")
    assert len(find_files(str(tmp_path), (".csv",))) == 1


def test_find_files_repertoire_absent(tmp_path):
    assert find_files(str(tmp_path / "nexiste_pas"), (".csv",)) == []


def test_find_files_ignore_les_dossiers(tmp_path):
    os.makedirs(tmp_path / "dossier.csv")
    assert find_files(str(tmp_path), (".csv",)) == []