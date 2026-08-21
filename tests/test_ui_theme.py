"""Tests du theme de l'interface.

Le theme est teste sans Tkinter : c'est tout l'interet de l'avoir isole de
l'application. Les tests tournent donc en integration continue, sans affichage.
"""

from __future__ import annotations

import re

import pytest

from modop.ui import theme


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_toutes_les_couleurs_sont_valides():
    couleurs = {n: v for n, v in vars(theme).items() if n.startswith("C_")}
    assert couleurs
    for nom, valeur in couleurs.items():
        assert HEX_COLOR.match(valeur), f"{nom} = {valeur}"


def test_les_polices_sont_definies():
    assert theme.F_TITLE and theme.F_BODY and theme.F_MONO


def test_les_phases_suivent_le_mode_operatoire():
    cles = [key for key, _label, _color in theme.PHASES]
    assert cles == ["dossier", "excel", "purge", "copie", "qgis", "zip"]


def test_chaque_phase_a_une_couleur_valide():
    for _key, label, color in theme.PHASES:
        assert label
        assert HEX_COLOR.match(color)


@pytest.mark.parametrize(
    "ligne, attendue",
    [
        ("[qgis] projet ouvert", theme.C_PURPLE),
        ("[copie] 4 fichier(s)", theme.C_GREEN),
        ("[zip] archive", theme.C_CYAN),
        ("[ok] livrable", theme.C_GREEN),
        ("[ko] echec", theme.C_RED),
        ("[lot] bilan", theme.C_AMBER),
        ("texte sans prefixe", theme.C_LOG_DEFAULT),
    ],
)
def test_couleur_par_prefixe(ligne, attendue):
    assert theme.log_color(ligne) == attendue


def test_un_avertissement_prime_sur_le_prefixe():
    """Une alerte doit se voir, quelle que soit l'etape qui l'emet."""
    assert theme.log_color("[qgis] ⚠ source introuvable") == theme.C_LOG_WARNING
    assert theme.log_color("❌ colonne absente") == theme.C_LOG_WARNING


def test_ligne_indentee():
    assert theme.log_color("   [qgis] indente") == theme.C_PURPLE


def test_chaque_phase_a_une_couleur_de_journal():
    """Toute etape affichee doit pouvoir colorer ses lignes de journal."""
    for key, _label, _color in theme.PHASES:
        assert f"[{key}]" in theme.LOG_COLORS