"""Chemins par défaut et emplacements des fichiers de configuration/suivi.

Gère deux modes :
    - développement (script Python)         → config à la racine du projet ;
    - application packagée (PyInstaller)     → config dans le dossier de
      données utilisateur de l'OS, car le dossier du programme est en lecture
      seule / temporaire.
"""

import os
import sys

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
# ------ RÉPERTOIRE DE L'AUDIT SNA' -------------------------------------
# -----------------------------------------------------------------------
# Chemin du dossier Audit SNA
def _audit_sna_path() -> str:
    """Chemin du dossier Audit SNA"""
    # return r"C:\Users\u269775\Altice Campus SFR\Swap Adresse - Etude Cible\audit_SNA"
    return os.path.join(BUREAU, "AUDIT_SNA")


# -----------------------------------------------------------------------
# ------ RÉPERTOIRE DE LA PRÉPARATION DES LIVRABLES ---------------------
# -----------------------------------------------------------------------
def _prepare_deliverable_path() -> str:
    """Chemins du dossier 'préparation livrable'"""
    # return os.path.join(_audit_sna_path(), "préparation livrable")
    return os.path.join(_audit_sna_path(), "LIVRABLE")


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
    """Chemin vers le répertoire de travail"""
    return os.path.join(BUREAU, "workspace")


def _qgis_project_path() -> str:
    """Chemin du projet QGIS"""
    return os.path.join(_workspace_path(), "carte_audit_maillage.qgz")


# -------------------------------------------------------------------------------------------
# ------ RÉPERTOIRE DÉPARTEMENT -------------------------------------------------------------
# -------------------------------------------------------------------------------------------

def _department_path(insee: str) -> str:
    """Chemin du dossier du département concerné par le code insee, si le dossier n'existe pas, en créer."""
    dep_code = str(insee).strip()[:2]
    dep_path = os.path.join(_audit_sna_path(), f"Dep{dep_code}")
    os.makedirs(dep_path, exist_ok=True)
    return dep_path


def _insee_dep_path(insee: str) -> str:
    """Chemin de la commune concerné par le code insee"""
    insee_path = os.path.join(_department_path(insee), str(insee))
    os.makedirs(insee_path, exist_ok=True)
    return insee_path

def _excel_destination_file_path(insee: str) -> str:
    """Chemin du fichier excel audit de la commune (préparations des livrables"""
    return os.path.join(_insee_dep_path(insee), f"audit_{insee}.xlsx")

def _insee_carte_path(insee: str) -> str:
    """Chemin du dossier Carte de la commune concernée par le code insee"""
    carte_path = os.path.join(_insee_dep_path(insee), "Carte")
    os.makedirs(carte_path, exist_ok=True)
    return carte_path


def _insee_analyse_path(insee: str) -> str:
    """Chemin du dossier Analyse de la commune concernée par le code insee"""
    analysis_path = os.path.join(_insee_dep_path(insee), "Analyse")
    os.makedirs(analysis_path, exist_ok=True)
    return analysis_path


# Configuration par défaut (chemins et options)
DEFAULT_CONFIG = {

}
