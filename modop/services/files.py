"""Copie des fichiers QGIS d'une commune vers le repertoire de travail local.

Source      : LIVRABLE / <lot> / QGIS / <insee>
Destination : workspace (Bureau)

Les fichiers existants sont ecrases par defaut, afin d'utiliser les versions
preparees pour le traitement QGIS.
"""

from __future__ import annotations

import os
import shutil

from modop.path_manager import _get_lot_path, _insee_qgis_path, _workspace_path


def copy_commune_files(
    lot_name: str,
    insee: str,
    destination: str | None = None,
    overwrite: bool = True,
    verbose: bool = True,
) -> list[str]:
    """Copie les fichiers QGIS de la commune vers le repertoire de travail.

    Args:
        lot_name: nom du lot (ex. "Lot7").
        insee: code INSEE de la commune (ex. "45001").
        destination: repertoire cible. Par defaut, le workspace.
        overwrite: ecrase les fichiers deja presents.
        verbose: affiche la progression.

    Returns:
        Chemins des fichiers copies, tries par nom.

    Raises:
        FileNotFoundError: le repertoire source n'existe pas.
        PermissionError: un fichier source ou cible est verrouille.
    """
    source_dir = _insee_qgis_path(lot_name, insee)
    if not os.path.isdir(source_dir):
        raise FileNotFoundError(f"Repertoire QGIS introuvable : {source_dir}")

    target_dir = destination or _workspace_path()
    os.makedirs(target_dir, exist_ok=True)

    copied: list[str] = []
    skipped = 0

    # walk() couvre les eventuels sous-dossiers, dont l'arborescence est
    # reproduite a l'identique dans la cible.
    for root, _dirs, filenames in os.walk(source_dir):
        relative = os.path.relpath(root, source_dir)
        current_target = target_dir if relative == "." else os.path.join(target_dir, relative)
        os.makedirs(current_target, exist_ok=True)

        for filename in sorted(filenames):
            source_file = os.path.join(root, filename)
            target_file = os.path.join(current_target, filename)

            if os.path.exists(target_file) and not overwrite:
                skipped += 1
                continue

            # copy2 conserve dates et metadonnees.
            shutil.copy2(source_file, target_file)
            copied.append(target_file)

    if verbose:
        print(f"[copie] {len(copied)} fichier(s) vers {target_dir}")
        if skipped:
            print(f"[copie] {skipped} fichier(s) deja present(s), conserve(s)")

    return sorted(copied)


def find_files(directory: str, extensions: tuple[str, ...]) -> list[str]:
    """Liste les fichiers d'un repertoire ayant l'une des extensions donnees.

    Args:
        directory: repertoire a inspecter (non recursif).
        extensions: extensions attendues, avec le point (ex. (".csv",)).

    Returns:
        Chemins tries. Liste vide si le repertoire n'existe pas.
    """
    if not os.path.isdir(directory):
        return []

    # Comparaison en minuscules : ".CSV" est accepte.
    wanted = tuple(ext.lower() for ext in extensions)

    return sorted(
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if name.lower().endswith(wanted)
        and os.path.isfile(os.path.join(directory, name))
    )


def list_communes(lot_name: str) -> list[str]:
    """Liste les codes INSEE presents dans le repertoire QGIS d'un lot.

    Args:
        lot_name: nom du lot (ex. "Lot7").

    Returns:
        Codes INSEE tries. Liste vide si le lot n'a pas de repertoire QGIS.
    """
    qgis_root = os.path.join(_get_lot_path(lot_name), "QGIS")
    if not os.path.isdir(qgis_root):
        return []

    return sorted(
        name for name in os.listdir(qgis_root)
        if os.path.isdir(os.path.join(qgis_root, name))
    )


def purge_workspace(
    directory: str | None = None,
    keep: tuple[str, ...] = (),
    verbose: bool = True,
) -> int:
    """Vide le repertoire de travail avant de traiter une commune.

    Indispensable en traitement par lot : sans purge, les fichiers de la
    commune precedente restent dans le workspace et entrent dans l'archive de
    la suivante.

    Le repertoire de travail est un espace de transit : tout ce qui n'est pas
    explicitement conserve est supprime.

    Args:
        directory: repertoire a vider. Par defaut, le workspace.
        keep: chemins a preserver, typiquement le projet QGIS modele.
        verbose: affiche la progression.

    Returns:
        Nombre d'elements supprimes.
    """
    target = directory or _workspace_path()
    if not os.path.isdir(target):
        return 0

    preserved = {os.path.abspath(path) for path in keep}
    removed = 0
    locked: list[str] = []

    for name in sorted(os.listdir(target)):
        path = os.path.join(target, name)
        if os.path.abspath(path) in preserved:
            continue

        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            removed += 1
        except OSError:
            # Fichier ouvert dans QGIS ou Excel : on signale sans interrompre.
            locked.append(name)

    if verbose:
        if removed:
            print(f"[purge] {removed} element(s) retire(s) du repertoire de travail")
        if locked:
            print(f"[purge] ⚠ {len(locked)} fichier(s) verrouille(s) : "
                  f"{', '.join(locked[:3])}")

    return removed