"""MODOP — production des livrables d'audit SNA.

Point d'entree : lance l'interface graphique.

Pour chaque commune d'un lot, l'application trie le fichier Excel d'audit,
copie les fichiers QGIS vers le repertoire de travail, centre le projet
cartographique sur la commune, l'enregistre au nom de celle-ci, puis depose
l'archive du livrable dans son dossier Carte.

Lancement :
    uv run python main.py

Sous Windows, renommer en main.pyw masque la console.
Le traitement reste utilisable sans interface :
    uv run python -m modop.services.workflow 45001 45002
"""

from modop.ui.application import App


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()