import os
import shutil

from openpyxl import load_workbook

from modop.constants import ZONE1_COL, ZONE2_COL, SENS_COL
from modop.path_manager import _excel_source_file_path, _excel_destination_file_path


def _sort_value(value):
    """
    Normalise une valeur pour permettre un tri croissant
    même si certaines cellules sont numériques, textuelles ou vides.
    """
    if value is None:
        return 0, 0

    if isinstance(value, (int, float)):
        return 1, value

    try:
        return 1, float(value)
    except (ValueError, TypeError):
        return 2, str(value).strip().lower()


def format_excel_file(lot_name: str, insee: str):
    """
    Copie le fichier Excel original dans le dossier de la commune,
    puis trie la copie selon les colonnes :
        1. zone 1
        2. zone 2
        3. sens

    Le fichier original n'est jamais modifié.
    """

    # ------------------------------------------------------------------
    # 1. Fichier Excel original
    # ------------------------------------------------------------------
    source_file = _excel_source_file_path(lot_name, insee)

    if not os.path.isfile(source_file):
        print(f"❌ Fichier Excel introuvable : {source_file}")
        return None

    # ------------------------------------------------------------------
    # 2. Répertoire de destination
    # ------------------------------------------------------------------
    destination_file = _excel_destination_file_path(insee)

    try:
        # ------------------------------------------------------------------
        # 3. Copier le fichier original
        # ------------------------------------------------------------------
        shutil.copy2(source_file, destination_file)

        print(f"✅ Copie créée : {destination_file}")

        # ------------------------------------------------------------------
        # 4. Ouvrir la copie
        # ------------------------------------------------------------------
        wb = load_workbook(destination_file)
        ws = wb.active

        # ------------------------------------------------------------------
        # 5. Identifier les colonnes
        # ------------------------------------------------------------------
        headers = {
            str(cell.value).strip().lower(): cell.column
            for cell in ws[1]
            if cell.value is not None
        }

        required_columns = [ZONE1_COL, ZONE2_COL, SENS_COL]

        for column_name in required_columns:
            if column_name not in headers:
                raise ValueError(
                    f"Colonne '{column_name}' introuvable dans le fichier Excel."
                )

        zone1_col = headers[ZONE1_COL]
        zone2_col = headers[ZONE2_COL]
        sens_col = headers[SENS_COL]

        print(
            f"📊 Colonnes trouvées : "
            f"zone 1={zone1_col}, "
            f"zone 2={zone2_col}, "
            f"sens={sens_col}"
        )

        # ------------------------------------------------------------------
        # 6. Récupérer les lignes
        # ------------------------------------------------------------------
        rows = list(
            ws.iter_rows(
                min_row=2,
                max_row=ws.max_row
            )
        )

        # ------------------------------------------------------------------
        # 7. Trier les lignes
        # ------------------------------------------------------------------
        rows.sort(
            key=lambda row: (
                _sort_value(row[zone1_col - 1].value),
                _sort_value(row[zone2_col - 1].value),
                _sort_value(row[sens_col - 1].value),
            )
        )

        # ------------------------------------------------------------------
        # 8. Réorganiser les lignes
        # ------------------------------------------------------------------
        for new_row_index, row in enumerate(rows, start=2):

            for column_index, cell in enumerate(row, start=1):
                destination_cell = ws.cell(
                    row=new_row_index,
                    column=column_index
                )

                destination_cell.value = cell.value

        # ------------------------------------------------------------------
        # 9. Enregistrer
        # ------------------------------------------------------------------
        wb.save(destination_file)
        wb.close()

        print("✅ Fichier Excel trié avec succès.")
        print(f"📁 Fichier final : {destination_file}")

        return destination_file

    except PermissionError as e:
        print(f"❌ Erreur de permission : {e}")
        return None

    except Exception as e:
        print(f"❌ Erreur traitement Excel : {e}")
        return None


if __name__ == "__main__":
    format_excel_file(
        lot_name="Lot7",
        insee="73063"
    )
