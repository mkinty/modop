"""Chemins par défaut et emplacements des fichiers de configuration/suivi.

Gère deux modes :
    - développement (script Python)         → config à la racine du projet ;
    - application packagée (PyInstaller)     → config dans le dossier de
      données utilisateur de l'OS, car le dossier du programme est en lecture
      seule / temporaire.
"""

import os
import sys
from urllib.parse import quote

from .constants import PPT_SHAREPOINT_BASE_URL

APP_NAME = "MODOP"

# Bureau du PC (fallback français "Bureau")
BUREAU = os.path.join(os.path.expanduser("~"), "Desktop")
if not os.path.isdir(BUREAU):
    _alt = os.path.join(os.path.expanduser("~"), "Bureau")
    if os.path.isdir(_alt):
        BUREAU = _alt


def _get_data_folder():
    """Dossier où est stoker la configuration adaptée au mode d'exécution"""
    if getattr(sys, "frozen", False):
        # Application packagée : dossier de données propre à l'utilisateur
        if sys.platform.startswith("win"):
            base = os.environ.get("APPDATA") or os.path.expanduser("")
        elif sys.platform == "darwin":
            base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        folder = os.path.join(base, APP_NAME)
        os.makedirs(folder, exist_ok=True)
        return folder
    # Mode développement : racine du projet (dossier contenant le fichier main.py)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Chemins des fichiers de configuration et de suivi des livrables faites (communes faites)
CONFIG_FILE = os.path.join(_get_data_folder(), "config.json")
TRACKING_FILE = os.path.join(BUREAU, "livrables_communes_faites.txt")


# -----------------------------------------------------------------------
# ------ CHEMINS PARAMÉTRABLES ------------------------------------------
# -----------------------------------------------------------------------
# Deux racines peuvent être redéfinies par l'utilisateur : le dossier
# AUDIT_SNA et le répertoire de travail. Tant qu'aucune valeur n'est fixée,
# les emplacements par défaut sur le Bureau s'appliquent.
#
# La substitution passe par des variables de module plutôt que par une
# lecture directe du fichier de configuration : path_manager reste sans
# dépendance, et les tests continuent d'isoler l'ensemble en redirigeant
# BUREAU.

#: Noms des dossiers par défaut. Les deux premiers sont relatifs au Bureau,
#: le troisième au dossier AUDIT_SNA.
DEFAULT_AUDIT_SNA_DIR = "AUDIT_SNA"
DEFAULT_WORKSPACE_DIR = "WORKSPACE"
DEFAULT_DELIVERABLE_DIR = "LIVRABLE"

_audit_sna_override: str | None = None
_workspace_override: str | None = None
_deliverable_override: str | None = None
_pptx_template_override: str | None = None


def _clean(valeur: str | None) -> str | None:
    """Normalise une surcharge : une saisie vide vaut absence de surcharge."""
    return valeur.strip() if valeur and valeur.strip() else None


def set_paths(audit_sna: str | None = None, workspace: str | None = None,
              deliverable: str | None = None, pptx_template: str | None = None) -> None:
    """Redéfinit les racines du programme.

    Une valeur vide ou None rétablit l'emplacement par défaut.

    Args:
        audit_sna: dossier AUDIT_SNA choisi par l'utilisateur.
        workspace: répertoire de travail choisi par l'utilisateur.
        deliverable: dossier de préparation des livrables. Par défaut, un
            sous-dossier d'AUDIT_SNA ; il peut être ailleurs, par exemple sur
            un partage réseau.
        pptx_template: chemin du template PPT vierge choisi par
            l'utilisateur, utilisé pour générer les PPT du dossier Analyse.
            Aucun défaut : une valeur vide désactive la génération.
    """
    global _audit_sna_override, _workspace_override, _deliverable_override
    global _pptx_template_override
    _audit_sna_override = _clean(audit_sna)
    _workspace_override = _clean(workspace)
    _deliverable_override = _clean(deliverable)
    _pptx_template_override = _clean(pptx_template)


def reset_paths() -> None:
    """Rétablit tous les emplacements par défaut."""
    set_paths(None, None, None, None)


def pptx_template_path() -> str:
    """Chemin du template PPT vierge choisi par l'utilisateur.

    Chaîne vide si aucun template n'a été configuré : la génération des PPT
    est alors désactivée, sans que ce soit une erreur.
    """
    return _pptx_template_override or ""


def default_audit_sna_path() -> str:
    """Emplacement par défaut du dossier AUDIT_SNA."""
    return os.path.join(BUREAU, DEFAULT_AUDIT_SNA_DIR)


def default_workspace_path() -> str:
    """Emplacement par défaut du répertoire de travail."""
    return os.path.join(BUREAU, DEFAULT_WORKSPACE_DIR)


def default_prepare_deliverable_path() -> str:
    """Emplacement par défaut du dossier de préparation des livrables.

    Dépend du dossier AUDIT_SNA courant : redéfinir celui-ci déplace aussi
    celui-là, tant qu'aucune surcharge propre n'est fixée.
    """
    return os.path.join(_audit_sna_path(), DEFAULT_DELIVERABLE_DIR)


# -----------------------------------------------------------------------
# ------ RÉPERTOIRE DE L'AUDIT SNA' -------------------------------------
# -----------------------------------------------------------------------
# Chemin du dossier Audit SNA
def _audit_sna_path() -> str:
    """Chemin du dossier Audit SNA.

    Renvoie le chemin choisi par l'utilisateur s'il en a fixé un, sinon
    l'emplacement par défaut sur le Bureau.
    """
    return _audit_sna_override or default_audit_sna_path()


# -----------------------------------------------------------------------
# ------ RÉPERTOIRE DE LA PRÉPARATION DES LIVRABLES ---------------------
# -----------------------------------------------------------------------
def _prepare_deliverable_path() -> str:
    """Chemin du dossier de préparation des livrables.

    Renvoie le chemin choisi par l'utilisateur s'il en a fixé un, sinon le
    sous-dossier LIVRABLE du dossier AUDIT_SNA.
    """
    return _deliverable_override or default_prepare_deliverable_path()


# Chemin du lot de préparation livrable
def _get_lot_path(name: str) -> str:
    """Chemin du lot concerné par la préparation des livrables"""
    return os.path.join(_prepare_deliverable_path(), str(name))


# Chemin du dossier QGIS dans la préparation des livrables
def _insee_qgis_path(lot_name: str, insee: str) -> str:
    """Chemin pour récupérer tous les fichiers du dossier QGIS"""
    return os.path.join(_get_lot_path(lot_name), "QGIS", str(insee))


def _excel_source_file_path(lot_name: str, insee: str) -> str:
    """Chemin du fichier excel audit de la commune (préparations des livrables"""
    return os.path.join(_get_lot_path(lot_name), "Excel", f"audit_{insee}.xlsx")


def _tracking_prepare_path() -> str:
    """Chemin du fichier de préparation suivi"""
    return os.path.join(_prepare_deliverable_path(), "Préparation suivi.xlsx")


# -----------------------------------------------------------------------
# ------ RÉPERTOIRE DE TRAVAIL ------------------------------------------
# -----------------------------------------------------------------------
def _workspace_path() -> str:
    """Chemin vers le répertoire de travail.

    Renvoie le chemin choisi par l'utilisateur s'il en a fixé un, sinon
    l'emplacement par défaut sur le Bureau.
    """
    return _workspace_override or default_workspace_path()


def _qgis_project_path() -> str:
    """Chemin du projet QGIS"""
    return os.path.join(_workspace_path(), "carte_audit maillage.qgz")


# -------------------------------------------------------------------------------------------
# ------ RÉPERTOIRE DÉPARTEMENT -------------------------------------------------------------
# -------------------------------------------------------------------------------------------

def _ensure_dir(path: str) -> str:
    """Crée ``path`` (et ses parents) et renvoie le chemin.

    ``os.makedirs`` échoue ici par un ``[WinError 2/3]`` peu parlant quand la
    racine AUDIT_SNA configurée n'est pas un dossier local inscriptible — cas
    fréquent d'un ``Documents`` redirigé vers OneDrive et non synchronisé sur
    le poste, d'un lecteur réseau déconnecté, ou d'un chemin mal saisi. On
    reformule alors en pointant le paramètre à corriger.
    """
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as error:
        raise OSError(
            f"Impossible de créer le dossier « {path} » ({error.strerror}). "
            f"Vérifiez le paramètre « Dossier AUDIT_SNA » "
            f"(actuellement « {_audit_sna_path()} ») : le dossier doit être "
            f"local et inscriptible — un dossier OneDrive non synchronisé ou "
            f"un lecteur réseau déconnecté déclenche cette erreur."
        ) from error
    return path


def verifier_racine_audit_sna() -> str:
    """Vérifie que la racine AUDIT_SNA configurée est utilisable.

    À appeler une fois avant un traitement par lot, pour échouer tout de
    suite avec un message clair plutôt que de buter sur ``[WinError 2]`` à
    chaque commune (voir ``_ensure_dir``). Crée la racine si elle est absente
    mais que son parent est inscriptible.

    Returns:
        Le chemin de la racine, garanti inscriptible.

    Raises:
        OSError: racine ni créable ni inscriptible.
    """
    racine = _audit_sna_path()
    _ensure_dir(racine)
    temoin = os.path.join(racine, ".modop_write_test")
    try:
        with open(temoin, "w"):
            pass
        os.remove(temoin)
    except OSError as error:
        raise OSError(
            f"Le dossier AUDIT_SNA « {racine} » n'est pas inscriptible "
            f"({error.strerror}). Choisissez un dossier local dans le "
            f"paramètre « Dossier AUDIT_SNA » (un dossier OneDrive non "
            f"synchronisé ou un lecteur réseau déconnecté ne convient pas)."
        ) from error
    return racine


def _department_path(insee: str) -> str:
    """Chemin du dossier du département de la commune ``insee``, créé au besoin."""
    dep_code = str(insee).strip()[:2]
    return _ensure_dir(os.path.join(_audit_sna_path(), f"Dep{dep_code}"))


def _insee_dep_path(insee: str) -> str:
    """Chemin du dossier de la commune ``insee``, créé au besoin."""
    return _ensure_dir(os.path.join(_department_path(insee), str(insee)))

def _excel_destination_file_path(insee: str) -> str:
    """Chemin du fichier excel audit de la commune (préparations des livrables"""
    return os.path.join(_insee_dep_path(insee), f"audit_{insee}.xlsx")

def _insee_carte_path(insee: str) -> str:
    """Chemin du dossier Carte de la commune concernée par le code insee"""
    return _ensure_dir(os.path.join(_insee_dep_path(insee), "Carte"))


def _insee_analyse_path(insee: str) -> str:
    """Chemin du dossier Analyse de la commune concernée par le code insee"""
    return _ensure_dir(os.path.join(_insee_dep_path(insee), "Analyse"))

def _insee_ppt_sharepoint_base_url(insee: str) -> str:
    """URL SharePoint du dossier Analyse de la commune (base des liens PPT).

    Reprend la même arborescence que ``_insee_analyse_path``
    (``Dep<xx>/<insee>/Analyse``), mais sous forme d'URL : segments joints par
    ``/`` et encodés (``quote``). Ne pas utiliser ``os.path.join`` ici — sur
    Windows il produirait des ``\\`` et casserait le lien.
    """
    insee = str(insee).strip()
    dep_code = insee[:2]
    segments = (f"Dep{dep_code}", insee, "Analyse")
    return "/".join([PPT_SHAREPOINT_BASE_URL.rstrip("/"), *(quote(s) for s in segments)])

# -----------------------------------------------------------------------
# ------ LIVRABLE QGIS --------------------------------------------------
# -----------------------------------------------------------------------

def _qgis_saved_project_path(insee: str) -> str:
    """Chemin du projet QGIS enregistre au nom de la commune."""
    return os.path.join(_workspace_path(), f"carte_audit {insee}.qgz")


def _deliverable_archive_path(insee: str) -> str:
    """Chemin de l'archive ZIP du livrable, dans le dossier Carte."""
    return os.path.join(_insee_carte_path(insee), f"Livrable Carto {insee}.zip")


# Configuration par défaut (chemins et options)
DEFAULT_CONFIG = {

}