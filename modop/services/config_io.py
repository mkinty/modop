"""Lecture et ecriture des preferences de l'interface.

Les preferences sont stockees en JSON dans le fichier designe par
`path_manager.CONFIG_FILE`, dont l'emplacement s'adapte au mode d'execution
(developpement ou application packagee).

Aucune exception ne remonte : une configuration illisible est remplacee par
les valeurs par defaut, une ecriture impossible est ignoree. Perdre des
preferences ne doit jamais empecher l'application de demarrer.
"""

from __future__ import annotations

import json
import os

from modop import path_manager
from modop.path_manager import CONFIG_FILE

#: Preferences par defaut, egalement utilisees comme schema : une cle absente
#: du fichier reprend sa valeur ici.
DEFAULT_CONFIG = {
    "lot_name": "Lot7",
    "insee_codes": "",
    "zoom_layer": "",
    # Chemins paramétrables. Vide = emplacement par défaut sur le Bureau.
    "audit_sna_path": "",
    "workspace_path": "",
    "sort_excel": True,
    "clean_workspace": True,
    "strict": False,
    "stop_on_error": False,
}


def load_config(path: str | None = None) -> dict:
    """Charge les preferences, completees par les valeurs par defaut.

    Args:
        path: fichier a lire. Par defaut, `CONFIG_FILE`.

    Returns:
        Un dictionnaire contenant toutes les cles de `DEFAULT_CONFIG`.
    """
    config = dict(DEFAULT_CONFIG)
    target = path or CONFIG_FILE

    try:
        with open(target, encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        # Fichier absent, illisible ou JSON invalide : valeurs par defaut.
        return config

    if isinstance(stored, dict):
        # Seules les cles connues sont reprises : un fichier d'une version
        # anterieure n'introduit pas de cle parasite.
        config.update({k: v for k, v in stored.items() if k in DEFAULT_CONFIG})

    return config


def save_config(config: dict, path: str | None = None) -> bool:
    """Enregistre les preferences.

    Args:
        config: preferences a ecrire. Les cles inconnues sont ignorees.
        path: fichier a ecrire. Par defaut, `CONFIG_FILE`.

    Returns:
        True si l'ecriture a reussi.
    """
    target = path or CONFIG_FILE
    retained = {k: v for k, v in config.items() if k in DEFAULT_CONFIG}

    try:
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(retained, handle, ensure_ascii=False, indent=2)
        return True
    except OSError:
        # Dossier en lecture seule, disque plein : sans consequence pour la
        # session en cours.
        return False


def parse_insee_codes(text: str) -> list[str]:
    """Extrait les codes INSEE d'une saisie libre.

    Accepte les separateurs usuels : virgule, point-virgule, espace, retour
    a la ligne, ainsi que les crochets d'une liste copiee depuis du code.

    Args:
        text: saisie de l'utilisateur, par exemple "45001, 45002" ou
            "[45001 45002]".

    Returns:
        Codes tries dans l'ordre de saisie, sans doublon.

    Examples:
        >>> parse_insee_codes("45001, 45002")
        ['45001', '45002']
        >>> parse_insee_codes("[45001; 45001\\n45002]")
        ['45001', '45002']
        >>> parse_insee_codes("   ")
        []
    """
    cleaned = text
    for character in "[]()'\",;\n\t":
        cleaned = cleaned.replace(character, " ")

    codes: list[str] = []
    for token in cleaned.split():
        if token not in codes:
            codes.append(token)

    return codes


def apply_paths(config: dict) -> None:
    """Applique les chemins de la configuration au reste du programme.

    A appeler une fois au demarrage, avant tout traitement : les services
    interrogent `path_manager` a chaque appel, ils prennent donc la nouvelle
    valeur en compte immediatement.

    Args:
        config: preferences chargees par `load_config`.
    """
    path_manager.set_paths(
        audit_sna=config.get("audit_sna_path", ""),
        workspace=config.get("workspace_path", ""),
    )


def load_and_apply(path: str | None = None) -> dict:
    """Charge les preferences et applique aussitot les chemins.

    Point d'entree unique pour l'interface comme pour la ligne de commande.

    Returns:
        Les preferences chargees.
    """
    config = load_config(path)
    apply_paths(config)
    return config