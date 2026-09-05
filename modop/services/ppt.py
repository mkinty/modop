"""Génération des PPT vierges à partir du template (substitution de variables).

Repris tel quel du programme BPA (services/ppt.py) : même mécanisme de
substitution, pour que les PPT produits par les deux programmes soient
strictement identiques à jeu de variables égal.

Robustesse au découpage PowerPoint : dans un .pptx, un même texte saisi (ex.
« Street View IA ») peut être éclaté par PowerPoint en plusieurs fragments XML
``<a:t>`` (à cause du correcteur orthographique ou d'un changement de mise en
forme). Un simple remplacement de chaîne sur le XML brut échouerait alors. On
travaille donc **paragraphe par paragraphe** : on fusionne le texte de tous les
fragments d'un paragraphe, on applique les remplacements sur le texte complet,
puis — uniquement si quelque chose a changé — on réinjecte le résultat dans le
premier fragment (les autres sont vidés). Les paragraphes sans variable ne sont
pas touchés, ce qui préserve leur mise en forme.
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile

from modop.constants import VARIABLES

_PARAGRAPHE = re.compile(r"<a:p\b[^>]*>.*?</a:p>", re.S)
_RUN_TEXTE = re.compile(r"(<a:t\b[^>]*>)(.*?)(</a:t>)", re.S)


def _echapper_xml(valeur: str) -> str:
    return (
        valeur.replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


def _substituer_paragraphe(bloc: str, row: dict) -> str:
    """Applique les substitutions de variables sur un paragraphe <a:p>…</a:p>."""
    fragments = _RUN_TEXTE.findall(bloc)
    if not fragments:
        return bloc

    texte_complet = "".join(f[1] for f in fragments)
    nouveau = texte_complet
    # Variables les plus longues d'abord (évite les collisions, ex. « Street
    # View IA » avant « Street View »).
    for var in sorted(VARIABLES.keys(), key=len, reverse=True):
        valeur = str(row.get(VARIABLES[var], "") or "").strip()
        nouveau = nouveau.replace(var, _echapper_xml(valeur))

    if nouveau == texte_complet:
        return bloc  # rien à changer → paragraphe intact (mise en forme préservée)

    # Réinjecte tout le texte dans le 1er fragment ; vide les suivants.
    compteur = {"i": 0}

    def _remplacer(m):
        i = compteur["i"]
        compteur["i"] += 1
        interne = nouveau if i == 0 else ""
        return f"{m.group(1)}{interne}{m.group(3)}"

    return _RUN_TEXTE.sub(_remplacer, bloc)


def generate_ppt(row: dict, output_path: str, pptx_template_path: str) -> None:
    """Génère un PPT en remplaçant les variables du template par les données de la ligne."""
    tmp = output_path + ".tmp.pptx"
    shutil.copy2(pptx_template_path, tmp)

    with zipfile.ZipFile(tmp, "r") as z:
        xml = z.read("ppt/slides/slide1.xml").decode("utf-8")

    xml = _PARAGRAPHE.sub(lambda m: _substituer_paragraphe(m.group(0), row), xml)

    with zipfile.ZipFile(tmp, "r") as zi, \
            zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in zi.infolist():
            contenu = (
                xml.encode("utf-8")
                if item.filename == "ppt/slides/slide1.xml"
                else zi.read(item.filename)
            )
            zo.writestr(item, contenu)

    os.remove(tmp)
