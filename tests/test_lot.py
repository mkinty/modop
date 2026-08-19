"""Tests du traitement d'un lot de plusieurs communes."""

from __future__ import annotations

import os
import zipfile

import pytest

from modop.path_manager import _deliverable_archive_path, _workspace_path
from modop.services.files import list_communes, purge_workspace
from modop.services.workflow import prepare_lot_deliverables
from tests.conftest import LOT


# ---------------------------------------------------------------------------
# Decouverte des communes
# ---------------------------------------------------------------------------

def test_list_communes(lot_communes):
    assert list_communes(LOT) == ["45001", "45002"]


def test_list_communes_lot_inconnu(bureau):
    assert list_communes("LotX") == []


# ---------------------------------------------------------------------------
# Purge du repertoire de travail
# ---------------------------------------------------------------------------

@pytest.fixture
def dossier(tmp_path):
    """Repertoire isole, pour ne pas compter les dossiers des autres fixtures."""
    cible = tmp_path / "travail"
    cible.mkdir()
    return cible


def test_purge_vide_le_repertoire(dossier):
    for nom in ("a.csv", "b.csv"):
        (dossier / nom).write_text("x", encoding="utf-8")

    assert purge_workspace(str(dossier), verbose=False) == 2
    assert os.listdir(dossier) == []


def test_purge_preserve_le_modele(dossier):
    modele = dossier / "modele.qgz"
    modele.write_text("x", encoding="utf-8")
    (dossier / "a.csv").write_text("x", encoding="utf-8")

    purge_workspace(str(dossier), keep=(str(modele),), verbose=False)
    assert os.listdir(dossier) == ["modele.qgz"]


def test_purge_supprime_les_sous_dossiers(dossier):
    (dossier / "styles").mkdir()
    (dossier / "styles" / "s.qml").write_text("x", encoding="utf-8")

    purge_workspace(str(dossier), verbose=False)
    assert os.listdir(dossier) == []


def test_purge_repertoire_absent(dossier):
    assert purge_workspace(str(dossier / "absent"), verbose=False) == 0


# ---------------------------------------------------------------------------
# Traitement du lot
# ---------------------------------------------------------------------------

def test_lot_produit_tous_les_livrables(lot_communes):
    bilan = prepare_lot_deliverables(LOT, ["45001", "45002"], verbose=False)

    assert bilan.ok
    assert bilan.succeeded == ["45001", "45002"]
    assert bilan.failed == []
    for insee in ("45001", "45002"):
        assert os.path.isfile(_deliverable_archive_path(insee))


def test_lot_accepte_des_entiers(lot_communes):
    """L'appel naturel passe des entiers : [45001, 45002]."""
    bilan = prepare_lot_deliverables(LOT, [45001, 45002], verbose=False)
    assert bilan.succeeded == ["45001", "45002"]


def test_lot_decouvre_les_communes(lot_communes):
    bilan = prepare_lot_deliverables(LOT, verbose=False)
    assert bilan.processed == ["45001", "45002"]


def test_pas_de_contamination_entre_communes(lot_communes):
    """L'archive de 45002 ne doit pas contenir les fichiers de 45001."""
    prepare_lot_deliverables(LOT, ["45001", "45002"], verbose=False)

    with zipfile.ZipFile(_deliverable_archive_path("45002")) as archive:
        noms = archive.namelist()

    assert "specifique_45001.csv" not in noms
    assert "adresses.csv" in noms


def test_chaque_archive_a_son_propre_projet(lot_communes):
    prepare_lot_deliverables(LOT, ["45001", "45002"], verbose=False)

    for insee in ("45001", "45002"):
        with zipfile.ZipFile(_deliverable_archive_path(insee)) as archive:
            projets = [n for n in archive.namelist() if n.endswith(".qgz")]
        assert len(projets) == 1
        assert insee in projets[0]


def test_donnees_de_la_bonne_commune(lot_communes):
    """Le contenu des CSV livres doit etre celui de la commune traitee."""
    prepare_lot_deliverables(LOT, ["45001", "45002"], verbose=False)

    with zipfile.ZipFile(_deliverable_archive_path("45002")) as archive:
        contenu = archive.read("adresses.csv").decode("utf-8")

    assert "2;B" in contenu


def test_une_commune_en_echec_nempeche_pas_les_autres(lot_communes):
    bilan = prepare_lot_deliverables(LOT, ["45001", "99999", "45002"], verbose=False)

    assert bilan.succeeded == ["45001", "45002"]
    assert bilan.failed == ["99999"]
    assert "FileNotFoundError" in bilan.errors["99999"]
    assert not bilan.ok


def test_stop_on_error_interrompt_le_lot(lot_communes):
    with pytest.raises(FileNotFoundError):
        prepare_lot_deliverables(
            LOT, ["99999", "45001"], stop_on_error=True, verbose=False
        )


def test_lot_vide(bureau):
    with pytest.raises(ValueError, match="Aucune commune"):
        prepare_lot_deliverables(LOT, [], verbose=False)


def test_lot_sans_commune_detectee(bureau):
    with pytest.raises(ValueError, match="Aucune commune"):
        prepare_lot_deliverables("LotX", verbose=False)


def test_avertissements_par_commune(lot_communes):
    """Les audits sont absents : chaque commune le signale."""
    bilan = prepare_lot_deliverables(LOT, ["45001", "45002"], verbose=False)

    assert set(bilan.warnings) == {"45001", "45002"}
    assert all("audit absent" in m for messages in bilan.warnings.values()
               for m in messages)


def test_lot_reproductible(lot_communes):
    premier = prepare_lot_deliverables(LOT, ["45001", "45002"], verbose=False)
    second = prepare_lot_deliverables(LOT, ["45001", "45002"], verbose=False)

    assert premier.succeeded == second.succeeded


def test_le_modele_survit_au_lot(lot_communes):
    """La purge ne doit jamais emporter le projet modele."""
    prepare_lot_deliverables(LOT, ["45001", "45002"], verbose=False)
    assert os.path.isfile(lot_communes["project"])


def test_journalisation_du_lot(lot_communes, capsys):
    prepare_lot_deliverables(LOT, ["45001", "45002"], verbose=True)
    sortie = capsys.readouterr().out

    assert "commune 45001" in sortie
    assert "commune 45002" in sortie
    assert "2/2 livrable(s) produit(s)" in sortie
    assert "[purge]" in sortie


# ---------------------------------------------------------------------------
# Callbacks de progression (utilises par l'interface)
# ---------------------------------------------------------------------------

def test_on_start_appele_pour_chaque_commune(lot_communes):
    appels = []
    prepare_lot_deliverables(
        LOT, ["45001", "45002"],
        on_start=lambda position, total, insee: appels.append((position, total, insee)),
        verbose=False,
    )

    assert appels == [(1, 2, "45001"), (2, 2, "45002")]


def test_on_result_recoit_le_resultat(lot_communes):
    recus = {}
    prepare_lot_deliverables(
        LOT, ["45001", "45002"],
        on_result=lambda insee, result, error: recus.__setitem__(insee, (result, error)),
        verbose=False,
    )

    assert set(recus) == {"45001", "45002"}
    for result, error in recus.values():
        assert result is not None and result.ok
        assert error == ""


def test_on_result_signale_un_echec(lot_communes):
    recus = {}
    prepare_lot_deliverables(
        LOT, ["99999"],
        on_result=lambda insee, result, error: recus.__setitem__(insee, (result, error)),
        verbose=False,
    )

    result, error = recus["99999"]
    assert result is None
    assert "FileNotFoundError" in error


def test_callbacks_optionnels(lot_communes):
    """L'absence de callback ne doit rien changer."""
    bilan = prepare_lot_deliverables(LOT, ["45001"], verbose=False)
    assert bilan.ok