# MODOP — Livrables audit SNA

Automatise la production des livrables cartographiques d'audit adresse, commune
par commune : tri du fichier Excel d'audit, préparation du projet QGIS, et
constitution de l'archive à déposer.

```
┌─ Configuration ─────────────────────────────────────────┐
│  Lot : Lot7    Codes INSEE : 45001, 45002    [Détecter] │
├─ Traitement ────────────────────────────────────────────┤
│  ████████████████████░░░░░░░░  Commune 2/2 — 45002      │
│  ● Audit  ● Purge  ● Copie  ● QGIS  ● Archive           │
├─ Résultats ─────────────────────────────────────────────┤
│  45001  ✅ OK   carto maillage principal  carte_audit…  │
│  45002  ✅ OK   carto maillage principal  carte_audit…  │
└─────────────────────────────────────────────────────────┘
```

## Installation

```powershell
uv sync
```

Prérequis : Python 3.13 et [uv](https://docs.astral.sh/uv/). Tkinter est fourni
avec Python sous Windows. Sous Linux, installer `python3-tk`.

**QGIS n'est pas requis** : le projet `.qgz` est manipulé directement, sans
PyQGIS.

## Utilisation

### Interface graphique

```powershell
uv run python main.py
```

1. Renseigner **Dossier AUDIT_SNA** et **Répertoire de travail**, ou les
   laisser vides pour utiliser les emplacements par défaut sur le Bureau. Le
   bouton 📁 ouvre un sélecteur de dossier.
2. Saisir le nom du lot, par exemple `Lot7`.
3. Saisir les codes INSEE, **un par ligne**, ou cliquer **Détecter** pour lire
   le répertoire QGIS du lot.
4. Cliquer **Lancer le traitement**.
5. Suivre l'avancement, puis consulter **Journal** pour le détail.

En fin de traitement, un signal sonore retentit et une synthèse s'affiche :
nombre de communes traitées, livrables produits, échecs et avertissements. La
page principale défile à la molette.

Chemins, lot, codes et options sont mémorisés d'une session à l'autre, dans un
fichier `config.json` dont l'emplacement s'adapte au mode d'exécution.

### Ligne de commande

```powershell
uv run python -m modop.services.workflow              # tout le lot
uv run python -m modop.services.workflow 45001 45002  # communes choisies
```

Chaque module s'exécute aussi seul, utile pour diagnostiquer une étape :

```powershell
uv run python -m modop.services.excel           # tri de l'audit
uv run python -m modop.services.files           # copie vers le workspace
uv run python -m modop.services.qgis_project    # inventaire des couches
uv run python -m modop.services.archive         # constitution du ZIP
```

### Depuis du code

```python
from modop.services.workflow import prepare_lot_deliverables

bilan = prepare_lot_deliverables("Lot7", [45001, 45002])

print(bilan.succeeded)   # ['45001', '45002']
print(bilan.failed)      # []
print(bilan.warnings)    # {'45002': ["Source introuvable pour la couche ..."]}
```

## Ce que fait le traitement

Pour chaque commune, dans cet ordre :

| Étape | Action |
|---|---|
| **Audit** | Trie `audit_<insee>.xlsx` sur zone 1, zone 2, sens, et dépose la copie triée dans le dossier de la commune |
| **Purge** | Vide le répertoire de travail, en préservant le projet modèle |
| **Copie** | Copie les fichiers QGIS de la commune vers le répertoire de travail |
| **QGIS** | Ouvre le projet modèle, contrôle les couches, centre la carte sur la commune, enregistre sous `carte_audit <insee>.qgz` |
| **Archive** | Compresse les `.csv` et le projet, dépose le ZIP dans le sous-dossier `Carte` |

Le fichier Excel est livré à part, dans le dossier de la commune : il n'entre
pas dans l'archive.

## Chemins

Deux racines sont configurables depuis l'interface :

| Racine | Défaut | Contient |
|---|---|---|
| Dossier AUDIT_SNA | `Bureau/AUDIT_SNA` | les lots en entrée et les livrables en sortie |
| Répertoire de travail | `Bureau/WORKSPACE` | le projet modèle et les fichiers de passage |

Tout le reste en découle. Changer la racine AUDIT_SNA déplace d'un coup les
chemins des lots, des fichiers d'audit et des dossiers de commune.

Le choix vaut aussi en ligne de commande : `python -m modop.services.workflow`
charge la configuration enregistrée avant de traiter.

## Arborescence attendue

```
Bureau/
├── AUDIT_SNA/
│   ├── LIVRABLE/Lot7/
│   │   ├── Excel/audit_45001.xlsx          ← source de l'audit
│   │   └── QGIS/45001/*.csv                ← données de la commune
│   └── Dep45/45001/
│       ├── audit_45001.xlsx                ← audit trié (sortie)
│       └── Carte/carte_audit 45001.zip     ← livrable (sortie)
└── WORKSPACE/
    └── carte_audit maillage.qgz            ← projet modèle
```

Tous ces chemins sont définis dans `modop/path_manager.py`, seul endroit à
modifier pour les adapter.

## Configuration

`modop/constants.py` — couches candidates pour le centrage de la carte :

```python
ZOOM_LAYER_CANDIDATES = (
    "carto maillage principal",   # couvre toute la commune
    "carto maillage nom",
    "carto SNA OK",
)
```

La première couche dont l'emprise est calculable est retenue. Les fonds de plan
(WMS, XYZ) sont écartés : leur emprise couvre le monde entier.

`modop/ui/theme.py` — couleurs, polices et libellés d'étapes. C'est le seul
fichier à modifier pour changer l'apparence.

## Tests

```powershell
uv run pytest -q          # 199 tests
uv run pytest -v          # détail
```

Les tests n'ont besoin ni de QGIS, ni d'affichage graphique, ni de
l'arborescence réelle : tous les chemins dérivent de `path_manager.BUREAU`,
redirigé vers un dossier temporaire.

## Points d'attention

**La purge supprime tout** dans le répertoire de travail, sauf le projet
modèle. Ne pas y conserver de fichiers personnels, ou décocher l'option.

**Le mode strict** fait échouer une commune à la première anomalie. Utile pour
un contrôle avant livraison, à laisser décoché en production.

**Les formules Excel** ne sont pas réécrites lors du tri : leurs références
relatives pointeraient vers les anciennes lignes. Un avertissement est émis si
le fichier en contient.

**Les cellules fusionnées** dans la zone de données font échouer le tri, à
dessein : les déplacer produirait un fichier faux sans le signaler.

## Documentation

`docs/ARCHITECTURE.md` détaille les choix techniques, le rôle de chaque module
et les pièges rencontrés.