"""Constitution de l'archive ZIP du livrable d'une commune.

L'archive regroupe les fichiers .csv du repertoire de travail et le projet
QGIS enregistre au nom de la commune, puis est deposee dans le sous-repertoire
Carte de la commune.
"""

from __future__ import annotations

import os
import shutil
import zipfile

from modop.path_manager import _deliverable_archive_path, _workspace_path
from modop.services.files import find_files

#: Extensions embarquees dans le livrable, en plus du projet QGIS.
DELIVERABLE_EXTENSIONS = (".csv",)


def create_zip(archive_path: str, files: list[str], verbose: bool = True) -> str:
    """Compresse une liste de fichiers dans une archive ZIP a plat.

    Args:
        archive_path: chemin de l'archive a creer (ecrasee si presente).
        files: fichiers a inclure.
        verbose: affiche la progression.

    Returns:
        Le chemin de l'archive.

    Raises:
        ValueError: liste vide, ou deux fichiers de meme nom.
        FileNotFoundError: un fichier de la liste est absent.
    """
    if not files:
        raise ValueError("Aucun fichier a compresser.")

    missing = [path for path in files if not os.path.isfile(path)]
    if missing:
        raise FileNotFoundError("Fichier(s) introuvable(s) : " + ", ".join(missing))

    # L'archive est a plat : deux fichiers homonymes s'ecraseraient en silence.
    names = [os.path.basename(path) for path in files]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise ValueError("Noms de fichiers en double : " + ", ".join(sorted(duplicates)))

    os.makedirs(os.path.dirname(os.path.abspath(archive_path)), exist_ok=True)

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=os.path.basename(path))

    if verbose:
        print(f"[zip] {len(files)} fichier(s) -> {archive_path}")

    return archive_path


def collect_deliverable_files(
    project_file: str,
    source_dir: str | None = None,
    extensions: tuple[str, ...] = DELIVERABLE_EXTENSIONS,
) -> list[str]:
    """Reunit les fichiers du livrable : les .csv et le projet QGIS.

    Args:
        project_file: projet QGIS enregistre au nom de la commune.
        source_dir: repertoire des .csv. Par defaut, le workspace.
        extensions: extensions a collecter en plus du projet.

    Returns:
        Chemins des fichiers a compresser.

    Raises:
        FileNotFoundError: le projet QGIS est absent.
    """
    if not os.path.isfile(project_file):
        raise FileNotFoundError(f"Projet QGIS introuvable : {project_file}")

    directory = source_dir or _workspace_path()
    files = find_files(directory, extensions)

    # Le projet peut deja figurer dans la liste s'il porte une extension
    # collectee : on evite le doublon.
    if os.path.abspath(project_file) not in {os.path.abspath(f) for f in files}:
        files.append(project_file)

    return files


def build_deliverable_archive(
    insee: str,
    project_file: str,
    source_dir: str | None = None,
    destination: str | None = None,
    verbose: bool = True,
) -> str:
    """Construit l'archive du livrable et la depose dans le dossier Carte.

    L'archive est d'abord creee dans le repertoire de travail, puis copiee
    vers sa destination finale.

    Args:
        insee: code INSEE de la commune.
        project_file: projet QGIS a inclure.
        source_dir: repertoire des .csv. Par defaut, le workspace.
        destination: chemin final de l'archive. Par defaut, dossier Carte.
        verbose: affiche la progression.

    Returns:
        Le chemin final de l'archive.
    """
    files = collect_deliverable_files(project_file, source_dir)

    final_path = destination or _deliverable_archive_path(insee)

    # L'archive est d'abord ecrite dans le repertoire de travail, sous le nom
    # de sa destination : la convention de nommage reste definie au seul
    # endroit qui en decide, path_manager.
    working_dir = source_dir or _workspace_path()
    staging_path = os.path.join(working_dir, os.path.basename(final_path))
    create_zip(staging_path, files, verbose=verbose)

    if os.path.abspath(staging_path) != os.path.abspath(final_path):
        os.makedirs(os.path.dirname(os.path.abspath(final_path)), exist_ok=True)
        shutil.copy2(staging_path, final_path)
        if verbose:
            print(f"[zip] copie vers {final_path}")

    return final_path


if __name__ == "__main__":
    # uv run python -m modop.services.archive
    from modop.path_manager import _qgis_saved_project_path

    INSEE = "45001"

    fichiers = collect_deliverable_files(_qgis_saved_project_path(INSEE))
    print(f"[zip] {len(fichiers)} fichier(s) a livrer :")
    for chemin in fichiers:
        print(f"  - {os.path.basename(chemin)}")

    archive = build_deliverable_archive(INSEE, _qgis_saved_project_path(INSEE))
    print(f"[zip] archive : {archive}")