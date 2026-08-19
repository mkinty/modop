"""Tests des chemins parametrables et de leur persistance."""

from __future__ import annotations

import os

import pytest

from modop import path_manager
from modop.services.config_io import (
    DEFAULT_CONFIG,
    apply_paths,
    load_and_apply,
    load_config,
    save_config,
)


@pytest.fixture(autouse=True)
def chemins_par_defaut():
    """Retablit les chemins par defaut apres chaque test.

    Les surcharges sont des variables de module : sans ce nettoyage, un test
    contaminerait les suivants.
    """
    yield
    path_manager.reset_paths()


# ---------------------------------------------------------------------------
# Surcharge des racines
# ---------------------------------------------------------------------------

def test_valeurs_par_defaut_sur_le_bureau(bureau):
    assert path_manager._audit_sna_path() == os.path.join(str(bureau), "AUDIT_SNA")
    assert path_manager._workspace_path() == os.path.join(str(bureau), "WORKSPACE")


def test_set_paths_remplace_les_racines(bureau, tmp_path):
    audit, work = str(tmp_path / "audit"), str(tmp_path / "travail")
    path_manager.set_paths(audit_sna=audit, workspace=work)

    assert path_manager._audit_sna_path() == audit
    assert path_manager._workspace_path() == work


def test_chaine_vide_retablit_le_defaut(bureau, tmp_path):
    path_manager.set_paths(audit_sna=str(tmp_path / "audit"))
    path_manager.set_paths(audit_sna="")

    assert path_manager._audit_sna_path() == path_manager.default_audit_sna_path()


def test_espaces_seuls_retablissent_le_defaut(bureau):
    path_manager.set_paths(workspace="   ")
    assert path_manager._workspace_path() == path_manager.default_workspace_path()


def test_reset_paths(bureau, tmp_path):
    path_manager.set_paths(str(tmp_path / "a"), str(tmp_path / "b"))
    path_manager.reset_paths()

    assert path_manager._audit_sna_path() == path_manager.default_audit_sna_path()
    assert path_manager._workspace_path() == path_manager.default_workspace_path()


def test_les_chemins_derives_suivent(bureau, tmp_path):
    """Tous les chemins construits a partir des racines doivent suivre."""
    audit, work = str(tmp_path / "audit"), str(tmp_path / "travail")
    path_manager.set_paths(audit_sna=audit, workspace=work)

    assert path_manager._get_lot_path("Lot7").startswith(audit)
    assert path_manager._insee_qgis_path("Lot7", "45001").startswith(audit)
    assert path_manager._excel_source_file_path("Lot7", "45001").startswith(audit)
    assert path_manager._insee_dep_path("45001").startswith(audit)
    assert path_manager._qgis_project_path().startswith(work)
    assert path_manager._qgis_saved_project_path("45001").startswith(work)


def test_les_deux_racines_sont_independantes(bureau, tmp_path):
    path_manager.set_paths(workspace=str(tmp_path / "travail"))

    assert path_manager._workspace_path() == str(tmp_path / "travail")
    assert path_manager._audit_sna_path() == path_manager.default_audit_sna_path()


# ---------------------------------------------------------------------------
# Persistance
# ---------------------------------------------------------------------------

def test_les_chemins_figurent_dans_la_config():
    assert "audit_sna_path" in DEFAULT_CONFIG
    assert "workspace_path" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["audit_sna_path"] == ""


def test_apply_paths(bureau, tmp_path):
    apply_paths({"audit_sna_path": str(tmp_path / "a"),
                 "workspace_path": str(tmp_path / "b")})

    assert path_manager._audit_sna_path() == str(tmp_path / "a")
    assert path_manager._workspace_path() == str(tmp_path / "b")


def test_apply_paths_tolere_les_cles_absentes(bureau):
    apply_paths({})
    assert path_manager._audit_sna_path() == path_manager.default_audit_sna_path()


def test_persistance_entre_deux_sessions(bureau, tmp_path):
    """Le scenario complet : on enregistre, on repart de zero, on recharge."""
    fichier = str(tmp_path / "config.json")
    audit, work = str(tmp_path / "audit"), str(tmp_path / "travail")

    save_config(dict(DEFAULT_CONFIG, audit_sna_path=audit, workspace_path=work),
                fichier)
    path_manager.reset_paths()
    assert path_manager._audit_sna_path() == path_manager.default_audit_sna_path()

    load_and_apply(fichier)
    assert path_manager._audit_sna_path() == audit
    assert path_manager._workspace_path() == work


def test_load_and_apply_renvoie_la_config(bureau, tmp_path):
    fichier = str(tmp_path / "config.json")
    save_config(dict(DEFAULT_CONFIG, lot_name="Lot9"), fichier)

    assert load_and_apply(fichier)["lot_name"] == "Lot9"


def test_config_absente_laisse_les_defauts(bureau, tmp_path):
    load_and_apply(str(tmp_path / "absent.json"))
    assert path_manager._audit_sna_path() == path_manager.default_audit_sna_path()


def test_le_traitement_utilise_les_chemins_choisis(bureau, tmp_path, commune_files):
    """Un traitement complet doit se derouler dans les dossiers configures."""
    from modop.services.files import list_communes

    # Avant surcharge, le lot est visible.
    assert list_communes("Lot7") == ["45001"]

    # Apres surcharge vers un dossier vide, il ne l'est plus.
    apply_paths({"audit_sna_path": str(tmp_path / "ailleurs")})
    assert list_communes("Lot7") == []