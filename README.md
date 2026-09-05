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
│  45001  ✅ OK   carto maillage principal  Livrable Ca…  │
│  45002  ✅ OK   carto maillage principal  Livrable Ca…  │
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

1. Renseigner les trois chemins, ou les laisser vides pour utiliser les
   emplacements par défaut. Le bouton 📁 ouvre un sélecteur de dossier.
2. Renseigner le **template PPT vierge** (bouton 📁 : sélecteur de fichier
   `.pptx` cette fois) si la case **Générer les PPT** doit être cochée : il
   est alors obligatoire, faute de quoi le traitement de la commune est
   interrompu.
3. Saisir le nom du lot, par exemple `Lot7`.
4. Saisir les codes INSEE, **un par ligne**, ou cliquer **Détecter** pour lire
   le répertoire QGIS du lot.
5. Cocher **Générer les PPT** si les liens et les PPT vierges doivent être
   produits (case vide par défaut : sans elle, l'audit n'est pas touché et
   le dossier `Analyse` reste vide).
6. Cliquer **Lancer le traitement**.
7. Suivre l'avancement, puis consulter **Journal** pour le détail.

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
| **Dossiers** | Crée l'arborescence de la commune : `Carte` et `Analyse` |
| **Audit** | Trie `audit_<insee>.xlsx` sur zone 1, zone 2, sens, et dépose la copie triée dans le dossier de la commune |
| **PPT** | Si la case **Générer les PPT** est cochée : complète la colonne `Lien vers le .ppt` de l'audit trié et génère les PPT vierges correspondants dans `Analyse`. Requiert un template PPT valide, sinon le traitement de la commune est interrompu. Décochée (défaut), cette étape n'a aucun effet |
| **Purge** | Vide le répertoire de travail, en préservant le projet modèle |
| **Copie** | Copie les fichiers QGIS de la commune vers le répertoire de travail |
| **QGIS** | Ouvre le projet modèle, contrôle les couches, centre la carte sur la commune, enregistre au nom de la commune |
| **Archive** | Compresse les `.csv` et le projet, dépose le ZIP dans le sous-dossier `Carte` |

Le fichier Excel est livré à part, dans le dossier de la commune : il n'entre
pas dans l'archive.

## PPT vierges du dossier Analyse

Cette étape n'a d'effet que si la case **Générer les PPT** est cochée (vide
par défaut) : décochée, ni la colonne `Lien vers le .ppt`, ni le dossier
`Analyse` ne sont modifiés.

Cochée, un **template PPT valide est obligatoire** : sans lui, **tout le
traitement est arrêté** (le lot entier, pas seulement la commune en cours) et
un message d'erreur clair est affiché — un template manquant ou introuvable
est une erreur de configuration à corriger, pas une anomalie de commune à
signaler et ignorer. Ce contrôle a lieu avant même de commencer la première
commune : aucun dossier, aucun fichier n'est produit tant qu'il n'a pas
réussi. Le template étant valide, pour chaque ligne de l'audit identifiée par
la colonne `ID erreur`, la colonne `Lien vers le .ppt` est complétée avec le
chemin du fichier `cas_analyse_<ID erreur>.pptx` dans le sous-dossier
`Analyse` de la commune, et le PPT est généré.

- **Case « Générer les PPT »** : vide par défaut. C'est elle qui déclenche
  toute l'étape, y compris le contrôle du template.
- **Template PPT vierge** : chemin configurable depuis l'interface (troisième
  champ de la carte Configuration). Obligatoire dès que la case est cochée.

Un template invalide n'est **pas** traité comme les autres anomalies (couche
QGIS manquante, audit absent, etc.), qui elles ne font échouer que la
commune concernée sans arrêter le reste du lot.

Le mécanisme de génération (nommage des fichiers, substitution des variables
du template, génération en parallèle) reprend celui du programme **BPA**
(`services/ppt.py` et la fonction `faire_ppt()` de `services/traitement.py`) :
même nom de fichier, mêmes variables (`modop/constants.py` — `VARIABLES`), de
sorte qu'un même template PPT vierge peut servir aux deux programmes.

## Chemins

Trois racines sont configurables depuis l'interface :

| Racine | Défaut | Contient |
|---|---|---|
| Dossier AUDIT_SNA | `Bureau/AUDIT_SNA` | les dossiers de commune produits (`Dep45/45001/…`) |
| Préparation livrables | `<AUDIT_SNA>/LIVRABLE` | les lots en entrée : fichiers d'audit et données QGIS |
| Répertoire de travail | `Bureau/WORKSPACE` | le projet modèle et les fichiers de passage |
| Template PPT vierge | *(aucun)* | le fichier `.pptx` utilisé pour générer les PPT du dossier `Analyse` |

Tout le reste en découle. Le dossier de préparation suit AUDIT_SNA tant qu'on
ne lui fixe pas d'emplacement propre — utile lorsque les lots arrivent d'un
partage réseau alors que les livrables restent sur le poste.

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
│       ├── audit_45001.xlsx                 ← audit trié (sortie)
│       ├── Carte/Livrable Carto 45001.zip   ← livrable (sortie)
│       └── Analyse/                         ← PPT générés (si demandé), sinon vide
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
uv run pytest -q          # 287 tests
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

**Les listes déroulantes** dont la source est sur une autre feuille sont
supprimées par openpyxl à l'enregistrement. Le programme les relève avant
ouverture et les réinjecte dans le fichier trié. Le journal l'indique :
`🔧 Extensions restaurées : listes déroulantes.` Même traitement pour les mises
en forme conditionnelles avancées et les plages protégées.

## Documentation

`docs/ARCHITECTURE.md` détaille les choix techniques, le rôle de chaque module
et les pièges rencontrés.