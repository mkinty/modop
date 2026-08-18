"""Copie et tri du fichier Excel d'audit d'une commune.

Tri croissant sur zone 1, puis zone 2, puis sens. Le fichier source n'est
jamais modifié : on travaille sur la copie placée dans le dossier de la commune.

Deux pièges openpyxl à connaître :
  - `iter_rows()` renvoie les cellules vivantes de la feuille. Il faut copier
    les valeurs avant d'écrire, sinon chaque écriture écrase une ligne non
    encore traitée et le fichier se vide.
  - `ws.max_row` compte les lignes qui n'ont qu'une mise en forme. Sans
    correction, ces lignes vides sont triées puis réécrites sur les données.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import time
import unicodedata
from copy import copy
from datetime import date, datetime, time as dtime  # alias : `time` est déjà pris
from typing import Any, Iterable, Sequence

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.worksheet.worksheet import Worksheet

from modop.constants import ZONE1_COL, ZONE2_COL, SENS_COL
from modop.path_manager import (
    _excel_source_file_path,
    _excel_destination_file_path,
)

# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------

HEADER_SCAN_ROWS = 10       # lignes scannées pour retrouver l'en-tête
SAVE_RETRIES = 3            # tentatives avant repli sur un nom horodaté
SAVE_RETRY_DELAY = 1.5      # secondes entre deux tentatives
EMPTY_VALUES_LAST = True    # cellules vides en fin de tri
DROP_EMPTY_ROWS = True      # supprimer les lignes entièrement vides

_NUM_SPLIT_RE = re.compile(r"(\d+)")   # "Z10" -> ['Z', '10', '']


# ---------------------------------------------------------------------------
# En-têtes
# ---------------------------------------------------------------------------

def _normalize_header(value: Any) -> str:
    """Ramène un libellé d'en-tête à une forme comparable.

    Neutralise casse, accents, espaces multiples et espace insécable.
    """
    if value is None:
        return ""

    # L'espace insécable est invisible et résiste à strip().
    text = str(value).replace("\u00a0", " ")

    # NFKD sépare lettre et accent, le filtre retire l'accent : "é" -> "e".
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))

    # split() + join() réduit les espaces multiples à un seul.
    return " ".join(text.split()).lower()


# ---------------------------------------------------------------------------
# Clé de tri
# ---------------------------------------------------------------------------
# Chaque valeur devient (rang, nombre, texte). Le rang étant comparé en premier,
# deux types différents ne sont jamais comparés sur leur contenu : pas de
# TypeError possible.

_RANK_NUMBER = 0
_RANK_DATE = 1
_RANK_TEXT = 2
_RANK_EMPTY = 3 if EMPTY_VALUES_LAST else -1


def _to_number(text: str) -> float | None:
    """Convertit '07', '1,5' ou '1 200' en nombre. None si non numérique."""
    cleaned = text.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        return None

    try:
        number = float(cleaned)
    except (TypeError, ValueError):
        return None

    # nan est incomparable et rendrait le tri instable.
    return None if (math.isnan(number) or math.isinf(number)) else number


def _natural_chunks(text: str) -> tuple:
    """Découpe un texte pour trier 'Z2' avant 'Z10'.

    >>> _natural_chunks("z2")
    ((1, 0, 'z'), (0, 2, ''))
    """
    chunks = []

    # Le groupe capturant conserve les nombres dans le résultat du split.
    for part in _NUM_SPLIT_RE.split(text):
        if not part:
            continue
        if part.isdigit():
            chunks.append((0, int(part), ""))
        else:
            chunks.append((1, 0, part))

    return tuple(chunks)


def _sort_key(value: Any) -> tuple:
    """Clé de tri croissant : nombres < dates < texte < cellules vides.

    >>> _sort_key(7) < _sort_key("Z2")
    True
    >>> _sort_key("Z2") < _sort_key("Z10")
    True
    """
    if value is None:
        return (_RANK_EMPTY, 0.0, ())

    # bool hérite de int : à tester avant.
    if isinstance(value, bool):
        return (_RANK_NUMBER, float(value), ())

    if isinstance(value, (int, float)):
        return (_RANK_NUMBER, float(value), ())

    # datetime hérite de date : à tester avant, sinon l'heure est perdue.
    if isinstance(value, datetime):
        return (_RANK_DATE, value.toordinal() * 86400.0
                + value.hour * 3600 + value.minute * 60 + value.second, ())

    if isinstance(value, date):
        return (_RANK_DATE, value.toordinal() * 86400.0, ())

    if isinstance(value, dtime):
        return (_RANK_DATE, value.hour * 3600.0 + value.minute * 60 + value.second, ())

    text = str(value).replace("\u00a0", " ").strip()
    if not text:
        return (_RANK_EMPTY, 0.0, ())

    number = _to_number(text)
    if number is not None:
        # Texte numérique rangé avec les nombres ; les chunks départagent
        # "07" et "7", qui donnent la même valeur.
        return _RANK_NUMBER, number, _natural_chunks(text.lower())

    return (_RANK_TEXT, 0.0, _natural_chunks(text.lower()))


# ---------------------------------------------------------------------------
# Feuille
# ---------------------------------------------------------------------------

def _find_header(workbook, required: Sequence[str]) -> tuple[Worksheet, int, dict[str, int]]:
    """Cherche la feuille et la ligne d'en-tête contenant les colonnes voulues.

    Ne suppose ni que la feuille est `wb.active`, ni que l'en-tête est en
    ligne 1. Renvoie (feuille, ligne, {libellé normalisé: colonne}).
    """
    wanted = {_normalize_header(name) for name in required}

    for worksheet in workbook.worksheets:
        max_scan = min(HEADER_SCAN_ROWS, worksheet.max_row or 1)

        for row_index in range(1, max_scan + 1):
            headers: dict[str, int] = {}

            for cell in worksheet[row_index]:
                key = _normalize_header(cell.value)
                # En cas de doublon, on garde la colonne la plus à gauche.
                if key and key not in headers:
                    headers[key] = cell.column

            # La ligne convient dès qu'elle contient les trois colonnes.
            if wanted.issubset(headers):
                return worksheet, row_index, headers

    raise ValueError(
        "Colonnes introuvables : "
        + ", ".join(f"'{name}'" for name in required)
        + f" (recherche sur les {HEADER_SCAN_ROWS} premières lignes de chaque feuille)"
    )


def _last_data_row(worksheet: Worksheet, first_row: int) -> int:
    """Dernière ligne réellement remplie, en ignorant les lignes fantômes."""
    last = first_row - 1

    # Parcours du bas vers le haut : arrêt à la première ligne non vide.
    for row_index in range(worksheet.max_row, first_row - 1, -1):
        if any(cell.value is not None for cell in worksheet[row_index]):
            last = row_index
            break

    return last


def _snapshot(cells: Iterable[Cell]) -> list[tuple[Any, Any]]:
    """Fige valeur et style d'une ligne dans des données inertes.

    Étape clé : elle détache les données de la feuille, pour que la lecture
    soit terminée avant la première écriture.
    """
    snapshot = []

    for cell in cells:
        # `_style` regroupe police, fond, bordure, alignement et format.
        style = getattr(cell, "_style", None)
        # Copie : openpyxl partage un même objet style entre cellules.
        snapshot.append((cell.value, copy(style) if style is not None else None))

    return snapshot


def _write_row(worksheet: Worksheet, row_index: int,
               snapshot: Sequence[tuple[Any, Any]]) -> None:
    """Réécrit une ligne. Le style suit la donnée."""
    for column_index, (value, style) in enumerate(snapshot, start=1):
        cell = worksheet.cell(row=row_index, column=column_index)

        # Une MergedCell est en lecture seule.
        if isinstance(cell, MergedCell):
            continue

        cell.value = value
        if style is not None:
            cell._style = style


def _clear_rows(worksheet: Worksheet, first_row: int, last_row: int) -> None:
    """Supprime la queue laissée par les lignes vides retirées."""
    if last_row < first_row:
        return
    worksheet.delete_rows(first_row, last_row - first_row + 1)


def _update_refs(worksheet: Worksheet, header_row: int, last_row: int) -> None:
    """Recale filtre auto et tableaux sur la nouvelle plage.

    Suppose que la plage démarre en colonne A.
    """
    from openpyxl.utils import get_column_letter

    last_col = get_column_letter(worksheet.max_column)
    new_ref = f"A{header_row}:{last_col}{max(last_row, header_row)}"

    # On recale un filtre existant, on n'en crée pas.
    if worksheet.auto_filter and worksheet.auto_filter.ref:
        worksheet.auto_filter.ref = new_ref

    for table in getattr(worksheet, "tables", {}).values():
        table.ref = new_ref


def _safe_save(workbook, path: str) -> str:
    """Enregistre malgré un verrou temporaire (Excel ouvert, OneDrive).

    Réessaie, puis bascule sur un nom horodaté. Renvoie le chemin écrit.
    """
    last_error: Exception | None = None

    for attempt in range(1, SAVE_RETRIES + 1):
        try:
            workbook.save(path)
            return path
        except PermissionError as error:
            last_error = error
            if attempt < SAVE_RETRIES:
                print(f"⏳ Fichier verrouillé, nouvelle tentative "
                      f"({attempt}/{SAVE_RETRIES})…")
                time.sleep(SAVE_RETRY_DELAY)

    base, extension = os.path.splitext(path)
    fallback = f"{base}_{datetime.now():%Y%m%d_%H%M%S}{extension}"
    workbook.save(fallback)

    print(f"⚠️ '{os.path.basename(path)}' est verrouillé ({last_error}).")
    print(f"➡️ Enregistré sous : {fallback}")
    return fallback


# ---------------------------------------------------------------------------
# Traitement principal
# ---------------------------------------------------------------------------

def format_excel_file(lot_name: str, insee: str, verbose: bool = True) -> str | None:
    """Copie le fichier Excel de la commune puis trie la copie.

    Args:
        lot_name: nom du lot (ex. "Lot7").
        insee: code INSEE de la commune (ex. "73063").
        verbose: affiche la progression.

    Returns:
        Chemin du fichier trié, ou None en cas d'échec. Peut différer de la
        destination prévue si celle-ci était verrouillée.
    """

    def log(message: str) -> None:
        if verbose:
            print(message)

    source_file = _excel_source_file_path(lot_name, insee)

    # Hors du try : condition d'entrée, pas erreur de traitement.
    if not os.path.isfile(source_file):
        print(f"❌ Fichier Excel introuvable : {source_file}")
        return None

    destination_file = _excel_destination_file_path(insee)
    workbook = None   # testé dans finally même si l'ouverture échoue

    try:
        # -- 1. Copie -------------------------------------------------------
        # Sans ce test, on écraserait la source.
        if os.path.abspath(source_file) == os.path.abspath(destination_file):
            print("❌ Source et destination identiques : copie annulée.")
            return None

        os.makedirs(os.path.dirname(destination_file), exist_ok=True)
        shutil.copy2(source_file, destination_file)   # copy2 garde les métadonnées
        log(f"✅ Copie créée : {destination_file}")

        # -- 2. Ouverture ---------------------------------------------------
        workbook = load_workbook(
            destination_file,
            # Sans keep_vba, un .xlsm perd ses macros à l'enregistrement.
            keep_vba=destination_file.lower().endswith(".xlsm"),
        )

        # -- 3. En-tête et colonnes -----------------------------------------
        required = (ZONE1_COL, ZONE2_COL, SENS_COL)
        worksheet, header_row, headers = _find_header(workbook, required)

        # Les clés sont normalisées : les constantes doivent l'être aussi.
        zone1_col, zone2_col, sens_col = (
            headers[_normalize_header(name)] for name in required
        )

        log(f"📄 Feuille : '{worksheet.title}' — en-tête ligne {header_row}")
        log(f"📊 Colonnes : {ZONE1_COL}={zone1_col}, "
            f"{ZONE2_COL}={zone2_col}, {SENS_COL}={sens_col}")

        # -- 4. Contrôles ---------------------------------------------------
        first_data_row = header_row + 1
        last_row = _last_data_row(worksheet, first_data_row)

        if last_row < first_data_row:
            print("⚠️ Aucune donnée à trier sous l'en-tête.")
            return destination_file

        # Une fusion ne suit pas le tri : les valeurs glisseraient dessous.
        merged_in_data = [
            str(rng) for rng in worksheet.merged_cells.ranges
            if rng.max_row >= first_data_row
        ]
        if merged_in_data:
            raise ValueError(
                "Cellules fusionnées dans la zone de données "
                f"({', '.join(merged_in_data[:5])}…) : le tri les désolidariserait "
                "des valeurs. Fusion à supprimer avant traitement."
            )

        # -- 5. Lecture -----------------------------------------------------
        # Tout est figé ici : plus rien ne dépend ensuite de l'état de la feuille.
        snapshots = [
            _snapshot(row)
            for row in worksheet.iter_rows(min_row=first_data_row, max_row=last_row)
        ]

        # Les références relatives des formules ne sont pas réécrites.
        if any(isinstance(value, str) and value.startswith("=")
               for snapshot in snapshots for value, _ in snapshot):
            log("⚠️ Formules détectées : leurs références relatives ne sont pas "
                "réécrites lors du déplacement des lignes.")

        initial_count = len(snapshots)

        if DROP_EMPTY_ROWS:
            # Seules les lignes entièrement vides partent.
            snapshots = [s for s in snapshots if any(v is not None for v, _ in s)]
            removed = initial_count - len(snapshots)
            if removed:
                log(f"🧹 {removed} ligne(s) vide(s) supprimée(s).")

        # -- 6. Tri ---------------------------------------------------------
        # Tri stable : les ex æquo gardent leur ordre d'origine.
        snapshots.sort(
            key=lambda snapshot: (
                # -1 : colonnes openpyxl en base 1, listes Python en base 0.
                _sort_key(snapshot[zone1_col - 1][0]),
                _sort_key(snapshot[zone2_col - 1][0]),
                _sort_key(snapshot[sens_col - 1][0]),
            )
        )

        # -- 7. Réécriture --------------------------------------------------
        for offset, snapshot in enumerate(snapshots):
            _write_row(worksheet, first_data_row + offset, snapshot)

        new_last_row = first_data_row + len(snapshots) - 1
        _clear_rows(worksheet, new_last_row + 1, worksheet.max_row)
        _update_refs(worksheet, header_row, new_last_row)

        # -- 8. Enregistrement ----------------------------------------------
        final_path = _safe_save(workbook, destination_file)
        log(f"✅ {len(snapshots)} ligne(s) triée(s).")
        log(f"📁 Fichier final : {final_path}")
        return final_path

    except ValueError as error:
        # Erreurs métier : le message est déjà explicite.
        print(f"❌ {error}")
        return None

    except Exception as error:
        # Le type est affiché, sinon un KeyError s'affiche comme "'zone 1'".
        print(f"❌ Erreur traitement Excel : {type(error).__name__} : {error}")
        return None

    finally:
        # Libère le handle : sous Windows, un classeur ouvert reste verrouillé.
        if workbook is not None:
            workbook.close()


if __name__ == "__main__":
    # uv run python -m modop.services.excel
    format_excel_file(lot_name="Lot7", insee="45001")