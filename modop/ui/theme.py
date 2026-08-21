"""Theme de l'interface : couleurs, polices et libelles d'etapes.

Toute la charte graphique est ici. L'application n'y fait que reference : pour
changer l'apparence, ce fichier est le seul a modifier.
"""

# ── Couleurs de fond ──────────────────────────────────────────────
C_BG = "#0a0e16"          # fond general
C_PANEL = "#121926"       # bandeau d'en-tete
C_PANEL2 = "#18202f"      # fonds secondaires (champs, en-tetes de tableau)
C_CARD = "#141b28"        # fond des cartes
C_BORDER = "#212a3a"      # bordure de carte
C_BORDER2 = "#2d3850"     # bordure appuyee (champ actif)

# ── Couleurs de texte ─────────────────────────────────────────────
C_TEXT = "#eef1f6"        # texte principal
C_TEXT2 = "#c2cad8"       # texte secondaire
C_MUTED = "#6d7889"       # legendes, aides

# ── Couleurs d'accent ─────────────────────────────────────────────
C_ACCENT = "#5b9cff"      # couleur primaire, actions
C_GREEN = "#3ddc9a"       # succes
C_AMBER = "#ffbe55"       # avertissement
C_RED = "#ff6b7a"         # erreur
C_PURPLE = "#b58cf0"      # etape QGIS
C_CYAN = "#4fe0d0"        # etape archive

# ── Page journal ──────────────────────────────────────────────────
C_LOG_BG = "#05080f"      # fond du journal
C_LOG_HEAD = "#150b1e"    # bandeau du journal
C_LOG_TITLE = "#d79aff"   # titre du journal

# ── Polices ───────────────────────────────────────────────────────
# Segoe UI est la police systeme sous Windows, cible principale.
F_TITLE = "Segoe UI Semibold"
F_BODY = "Segoe UI"
F_MONO = "Consolas"

# ── Etapes du traitement, dans l'ordre du mode operatoire ─────────
# Les cles correspondent aux prefixes journalises par les services :
# une ligne "[qgis] ..." allume l'etape "qgis".
PHASES = [
    ("dossier", "Dossiers", C_TEXT2),
    ("excel", "Audit", C_ACCENT),
    ("purge", "Purge", C_MUTED),
    ("copie", "Copie", C_GREEN),
    ("qgis", "QGIS", C_PURPLE),
    ("zip", "Archive", C_CYAN),
]

# ── Correspondance prefixe de journal → couleur d'affichage ──────
LOG_COLORS = {
    "[dossier]": C_TEXT2,
    "[excel]": C_ACCENT,
    "[purge]": C_MUTED,
    "[copie]": C_GREEN,
    "[qgis]": C_PURPLE,
    "[zip]": C_CYAN,
    "[ok]": C_GREEN,
    "[ko]": C_RED,
    "[lot]": C_AMBER,
    "=====": C_TEXT,
}

#: Couleur par defaut d'une ligne de journal.
C_LOG_DEFAULT = C_TEXT2

#: Couleur d'une ligne portant un avertissement, quel que soit son prefixe.
C_LOG_WARNING = C_AMBER


def log_color(line: str) -> str:
    """Couleur d'affichage d'une ligne de journal.

    >>> log_color("[qgis] projet ouvert")
    '#b58cf0'
    >>> log_color("[copie] ⚠ fichier verrouille") == C_LOG_WARNING
    True
    """
    if "⚠" in line or "❌" in line:
        return C_LOG_WARNING

    for prefix, color in LOG_COLORS.items():
        if line.lstrip().startswith(prefix):
            return color

    return C_LOG_DEFAULT