"""Préservation des extensions xlsx qu'openpyxl ne sait pas gérer.

openpyxl ignore les blocs `<extLst>` des feuilles et les supprime à
l'enregistrement, en émettant l'avertissement :

    UserWarning: Data Validation extension is not supported and will be removed

Ces blocs portent des fonctionnalités courantes dans un fichier d'audit :
listes déroulantes dont la source est sur une autre feuille, mises en forme
conditionnelles avancées, plages protégées. Les perdre silencieusement rendrait
le fichier livré différent de l'original.

Ce module réinjecte ces blocs dans le fichier enregistré, par manipulation
directe de l'archive. Le tri, lui, ne touche qu'aux valeurs et aux styles : les
extensions désignent des plages de cellules, qui restent valides.

Le procédé est volontairement défensif : à la moindre difficulté, le fichier
enregistré par openpyxl est conservé tel quel.
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from xml.etree import ElementTree

#: Extensions connues, par identifiant. Reprend la table d'openpyxl, traduite.
EXTENSION_LABELS = {
    "{CCE6A557-97BC-4B89-ADB6-D9C93CAAB3DF}": "listes déroulantes",
    "{78C0D931-6437-407D-A8EE-F0AAD7539E65}": "mise en forme conditionnelle",
    "{05C60535-1F16-4FD2-B633-F4F36F0B64E0}": "graphiques sparkline",
    "{FC87AEE6-9EDD-4A0A-B7FB-166176984837}": "plages protégées",
    "{01252117-D84E-4E92-8308-4BE1C098FCBB}": "erreurs ignorées",
    "{A8765BA9-456A-4DAB-B4F3-ACF838C121DE}": "segments",
    "{3A4CF648-6AED-40F4-86FF-DC5316D8AED3}": "segments",
    "{7E03D99C-DC04-49D9-9315-930204A7B6E9}": "chronologies",
    "{F7C9EE02-42E1-4005-9D12-6889AFFD525C}": "extensions web",
}

#: Balise XML, ouvrante, fermante ou auto-fermante.
_TAG_RE = re.compile(r"<(/?)([\w:.-]+)([^>]*?)(/?)>", re.DOTALL)

#: Déclarations d'espaces de noms portées par la balise <worksheet>.
_XMLNS_RE = re.compile(r'\sxmlns:(\w+)="[^"]*"')

#: Identifiant d'une extension.
_URI_RE = re.compile(r'<ext\s[^>]*uri="([^"]+)"', re.IGNORECASE)

#: Préfixes utilisés dans un fragment, pour ne rappeler que les déclarations
#: réellement nécessaires.
_PREFIX_RE = re.compile(r"<(\w+):")


def _toplevel_extlst(xml: str) -> str | None:
    """Extrait le bloc <extLst> enfant direct de <worksheet>.

    Un balayage de profondeur est indispensable : une feuille peut contenir
    plusieurs <extLst> imbriqués — une barre de données en porte un dans son
    <cfRule>. Une recherche textuelle partirait du premier rencontré et
    engloberait tout ce qui le sépare du dernier, produisant un fragment qui,
    réinjecté, duplique des éléments et rend le fichier illisible.

    Le texte d'origine est renvoyé tel quel, sans réécriture : les préfixes et
    l'ordre des attributs sont préservés à l'octet près.

    Returns:
        Le fragment, ou None si la feuille n'en contient pas.
    """
    profondeur = 0
    debut = None
    niveau_extlst = None

    for balise in _TAG_RE.finditer(xml):
        fermante, nom, _attributs, auto_fermante = balise.groups()

        # Les instructions de traitement et commentaires ne sont pas des
        # éléments : ils n'entrent pas dans le calcul de profondeur.
        if nom.startswith(("?", "!")):
            continue

        if fermante:
            profondeur -= 1
            if debut is not None and profondeur == niveau_extlst:
                return xml[debut:balise.end()]
            continue

        if auto_fermante:
            # <extLst/> vide : rien à conserver.
            continue

        # Profondeur 1 = enfant direct de <worksheet>, qui occupe le niveau 0.
        if nom == "extLst" and profondeur == 1 and debut is None:
            debut = balise.start()
            niveau_extlst = profondeur

        profondeur += 1

    return None


def _sheet_files(archive: zipfile.ZipFile) -> list[str]:
    """Feuilles de l'archive, dans l'ordre du classeur."""
    return sorted(
        name for name in archive.namelist()
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
    )


def _namespaces(worksheet_xml: str) -> dict[str, str]:
    """Espaces de noms déclarés sur la balise <worksheet>."""
    entete = worksheet_xml[:worksheet_xml.find(">") + 1]
    return {
        prefixe: declaration
        for prefixe, declaration in (
            (m.group(1), m.group(0).strip()) for m in _XMLNS_RE.finditer(entete)
        )
    }


def _with_namespaces(fragment: str, namespaces: dict[str, str]) -> str:
    """Rend un fragment autonome en y rappelant les espaces de noms utiles.

    Un `<extLst>` déplacé perd les déclarations portées par la balise racine
    de la feuille d'origine : sans elles, le XML produit serait invalide.
    """
    manquants = [
        declaration for prefixe, declaration in namespaces.items()
        if prefixe in set(_PREFIX_RE.findall(fragment))
        and f"xmlns:{prefixe}=" not in fragment
    ]
    if not manquants:
        return fragment

    return fragment.replace("<extLst>", "<extLst " + " ".join(manquants) + ">", 1)


def find_extensions(path: str) -> dict[str, str]:
    """Relève les blocs d'extension d'un classeur.

    Args:
        path: chemin du fichier .xlsx ou .xlsm.

    Returns:
        Un dictionnaire {nom de feuille dans l'archive: fragment XML}. Vide si
        le fichier n'en contient aucun ou n'est pas lisible.
    """
    trouves: dict[str, str] = {}

    try:
        with zipfile.ZipFile(path) as archive:
            for nom in _sheet_files(archive):
                xml = archive.read(nom).decode("utf-8")
                fragment = _toplevel_extlst(xml)
                if fragment:
                    trouves[nom] = _with_namespaces(fragment, _namespaces(xml))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError):
        return {}

    return trouves


def describe_extensions(extensions: dict[str, str]) -> list[str]:
    """Libellés lisibles des extensions relevées, sans doublon.

    >>> describe_extensions({"s": '<extLst><ext uri="{CCE6A557-97BC-4B89-ADB6-D9C93CAAB3DF}"/></extLst>'})
    ['listes déroulantes']
    """
    libelles: list[str] = []

    for fragment in extensions.values():
        for uri in _URI_RE.findall(fragment):
            libelle = EXTENSION_LABELS.get(uri.upper(), "extension non identifiée")
            if libelle not in libelles:
                libelles.append(libelle)

    return libelles


def _is_valid_workbook(path: str, sheets: list[str]) -> bool:
    """Verifie qu'un classeur reste exploitable apres reinjection.

    Un fragment mal delimite produit un XML syntaxiquement correct mais dont
    les elements sont dupliques ou hors ordre : Excel refuse alors d'ouvrir le
    fichier, sans que Python ne signale quoi que ce soit. On controle donc la
    bonne formation de chaque feuille modifiee, ainsi que la presence des
    entrees essentielles.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            noms = set(archive.namelist())
            if "[Content_Types].xml" not in noms or "xl/workbook.xml" not in noms:
                return False

            for nom in sheets:
                if nom not in noms:
                    return False
                ElementTree.fromstring(archive.read(nom))

    except (OSError, zipfile.BadZipFile, ElementTree.ParseError):
        return False

    return True


def restore_extensions(target: str, extensions: dict[str, str]) -> bool:
    """Réinjecte des blocs d'extension dans un classeur enregistré.

    L'archive est réécrite entièrement : le format zip ne permet pas de
    remplacer une entrée en place.

    Args:
        target: classeur à compléter, modifié sur place.
        extensions: fragments relevés par `find_extensions`.

    Returns:
        True si au moins un bloc a été réinjecté. False si rien n'a pu l'être,
        auquel cas le fichier reste inchangé.
    """
    if not extensions:
        return False

    temporaire = f"{target}.ext.tmp"
    reinjectes = 0

    try:
        with zipfile.ZipFile(target) as source:
            entrees = [(item, source.read(item.filename)) for item in source.infolist()]

        with zipfile.ZipFile(temporaire, "w", zipfile.ZIP_DEFLATED) as sortie:
            for item, contenu in entrees:
                fragment = extensions.get(item.filename)

                # Une feuille qui possède déjà un extLst a été écrite par un
                # outil qui les gère : on n'y touche pas.
                if fragment and b"<extLst>" not in contenu:
                    xml = contenu.decode("utf-8")
                    if "</worksheet>" in xml:
                        contenu = xml.replace(
                            "</worksheet>", fragment + "</worksheet>", 1
                        ).encode("utf-8")
                        reinjectes += 1

                sortie.writestr(item, contenu)

        if not reinjectes:
            return False

        # Le fichier n'est remplace que s'il est verifie : mieux vaut perdre
        # les listes deroulantes qu'un livrable illisible.
        if not _is_valid_workbook(temporaire, list(extensions)):
            return False

        shutil.move(temporaire, target)
        return True

    except (OSError, zipfile.BadZipFile, UnicodeDecodeError):
        pass

    finally:
        # Le fichier temporaire ne doit jamais subsister.
        try:
            if os.path.exists(temporaire):
                os.remove(temporaire)
        except OSError:
            pass

    return False