"""Tests de la persistance des preferences et de l'analyse de saisie."""

from __future__ import annotations

import json

import pytest

from modop.services.config_io import (
    DEFAULT_CONFIG,
    load_config,
    parse_insee_codes,
    save_config,
)


# ---------------------------------------------------------------------------
# Saisie des codes INSEE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "saisie, attendu",
    [
        ("45001, 45002", ["45001", "45002"]),
        ("45001 45002", ["45001", "45002"]),
        ("45001;45002", ["45001", "45002"]),
        ("45001\n45002", ["45001", "45002"]),
        ("[45001, 45002]", ["45001", "45002"]),          # liste copiee du code
        ("['45001', '45002']", ["45001", "45002"]),
        ("  45001  ", ["45001"]),
        ("45001, 45001, 45002", ["45001", "45002"]),      # doublon retire
        ("", []),
        ("   ", []),
    ],
)
def test_parse_insee_codes(saisie, attendu):
    assert parse_insee_codes(saisie) == attendu


def test_parse_conserve_l_ordre_de_saisie():
    assert parse_insee_codes("45002, 45001") == ["45002", "45001"]


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

def test_config_absente_renvoie_les_defauts(tmp_path):
    assert load_config(str(tmp_path / "absent.json")) == DEFAULT_CONFIG


def test_aller_retour(tmp_path):
    chemin = str(tmp_path / "config.json")
    config = dict(DEFAULT_CONFIG, lot_name="Lot9", insee_codes="45001")

    assert save_config(config, chemin)
    assert load_config(chemin)["lot_name"] == "Lot9"
    assert load_config(chemin)["insee_codes"] == "45001"


def test_config_illisible_renvoie_les_defauts(tmp_path):
    """Un fichier corrompu ne doit pas empecher l'application de demarrer."""
    chemin = tmp_path / "config.json"
    chemin.write_text("{ ceci n'est pas du json", encoding="utf-8")

    assert load_config(str(chemin)) == DEFAULT_CONFIG


def test_config_partielle_completee(tmp_path):
    chemin = tmp_path / "config.json"
    chemin.write_text(json.dumps({"lot_name": "Lot3"}), encoding="utf-8")

    config = load_config(str(chemin))
    assert config["lot_name"] == "Lot3"
    assert config["sort_excel"] == DEFAULT_CONFIG["sort_excel"]


def test_cles_inconnues_ignorees(tmp_path):
    """Une config d'une version anterieure ne pollue pas l'application."""
    chemin = tmp_path / "config.json"
    chemin.write_text(json.dumps({"lot_name": "Lot3", "obsolete": 1}), encoding="utf-8")

    assert "obsolete" not in load_config(str(chemin))


def test_sauvegarde_filtre_les_cles_inconnues(tmp_path):
    chemin = str(tmp_path / "config.json")
    save_config({"lot_name": "Lot3", "parasite": "x"}, chemin)

    with open(chemin, encoding="utf-8") as handle:
        assert "parasite" not in json.load(handle)


def test_sauvegarde_cree_le_repertoire(tmp_path):
    chemin = str(tmp_path / "nouveau" / "config.json")
    assert save_config(DEFAULT_CONFIG, chemin)


# ---------------------------------------------------------------------------
# PPT vierges : template et case a cocher
# ---------------------------------------------------------------------------

def test_pptx_template_path_vide_par_defaut():
    assert DEFAULT_CONFIG["pptx_template_path"] == ""


def test_generate_ppts_decoche_par_defaut():
    """La case doit etre vide par defaut : les PPT ne sont generes qu'a la
    demande explicite de l'utilisateur."""
    assert DEFAULT_CONFIG["generate_ppts"] is False


def test_pptx_template_persiste(tmp_path):
    chemin = str(tmp_path / "config.json")
    config = dict(DEFAULT_CONFIG, pptx_template_path=str(tmp_path / "modele.pptx"),
                  generate_ppts=True)

    save_config(config, chemin)
    relu = load_config(chemin)

    assert relu["pptx_template_path"] == str(tmp_path / "modele.pptx")
    assert relu["generate_ppts"] is True


def test_apply_paths_pose_le_template(bureau, tmp_path):
    from modop import path_manager
    from modop.services.config_io import apply_paths

    apply_paths({"pptx_template_path": str(tmp_path / "modele.pptx")})
    assert path_manager.pptx_template_path() == str(tmp_path / "modele.pptx")

    path_manager.reset_paths()