# Structure du programme

Vue d'ensemble des fichiers, de leur rôle et de leurs dépendances. Pour les
choix de conception, voir `ARCHITECTURE.md`.

## Arborescence

```
modop/
├── main.py                          point d'entrée : lance l'interface        26
├── README.md                        installation et usage                    156
├── pyproject.toml                   dépendances et configuration pytest       15
│
├── docs/
│   ├── ARCHITECTURE.md              choix techniques et pièges               228
│   └── STRUCTURE.md                 ce document
│
├── modop/
│   ├── path_manager.py              tous les chemins du programme            247
│   ├── constants.py                 colonnes de tri, variables PPT           40
│   │
│   ├── services/                    logique métier
│   │   ├── workflow.py              orchestration commune et lot             445
│   │   ├── excel.py                 tri du fichier d'audit                   440
│   │   ├── analyse.py               liens et PPT vierges du dossier Analyse  220
│   │   ├── ppt.py                   génération d'un PPT depuis le template   87
│   │   ├── files.py                 copie, purge, découverte des communes    173
│   │   ├── qgis_project.py          lecture et écriture du .qgz              452
│   │   ├── qgis_datasource.py       calcul d'emprise depuis les CSV          186
│   │   ├── archive.py               constitution du ZIP livrable             147
│   │   └── config_io.py             préférences de l'interface               153
│   │
│   └── ui/                          interface graphique
│       ├── application.py           fenêtre Tkinter                          1088
│       └── theme.py                 couleurs, polices, libellés               90
│
└── tests/                           287 tests
    ├── conftest.py                  fixtures partagées                       249
    ├── test_excel.py                                                         319
    ├── test_qgis_project.py                                                  337
    ├── test_workflow.py             (dont PPT vierges)                       412
    ├── test_analyse.py              liens et PPT vierges                     194
    ├── test_lot.py                                                           228
    ├── test_archive.py                                                       155
    ├── test_qgis_datasource.py                                               129
    ├── test_files.py                                                         107
    ├── test_paths_config.py                                                  270
    ├── test_config_io.py                                                     131
    └── test_ui_theme.py                                                       71
```

Total : environ 3 300 lignes de code et de tests.

## API publique

### `services/workflow.py` — orchestration

```python
prepare_commune_deliverable(lot_name, insee, zoom_layer=None, project_path=None,
                            sort_excel=True, clean_workspace=True, strict=False,
                            pptx_template_path=None, generate_ppts=False,
                            verbose=True) -> DeliverableResult

prepare_lot_deliverables(lot_name, insee_codes=None, zoom_layer=None,
                         project_path=None, sort_excel=True, strict=False,
                         stop_on_error=False, pptx_template_path=None,
                         generate_ppts=False, on_start=None, on_result=None,
                         verbose=True) -> LotResult
```

`DeliverableResult` : `insee`, `excel_file`, `ppt_liens`, `ppt_generes`,
`copied_files`, `project_file`, `archive_file`, `zoom_layer`, `warnings`,
`ok`, `complete`

`LotResult` : `lot_name`, `results`, `errors`, `processed`, `succeeded`,
`failed`, `ok`, `warnings`

### `services/excel.py` — tri de l'audit

```python
format_excel_file(lot_name, insee, verbose=True) -> str | None
```

### `services/analyse.py` — liens et PPT vierges du dossier Analyse

```python
generer_ppts_commune(excel_path, insee, pptx_template_path, generate_ppts,
                     parallel=True, verbose=True) -> AnalysePptResult
valider_template_ppt(pptx_template_path) -> None   # lève PptTemplateError
ppt_name_for(id_err) -> str            # "cas_analyse_<id_err>.pptx"
build_ppt_link(insee, id_err) -> str   # chemin dans le dossier Analyse
```

`AnalysePptResult` : `total`, `liens_completes`, `ppt_generes`, `erreurs`,
`avertissements`

`PptTemplateError` (`RuntimeError`) : levée si `generate_ppts` est vrai sans
template PPT valide configuré. Erreur de configuration, volontairement
**non** traitée comme un échec de commune : `workflow.prepare_lot_deliverables`
la valide une fois pour tout le lot, avant même la première commune, et la
laisse remonter telle quelle plutôt que de l'enregistrer dans
`LotResult.errors` — elle arrête tout le lot, contrairement aux autres
anomalies (audit absent, couche QGIS manquante…) qui n'affectent que la
commune concernée.

Sans effet si `generate_ppts` est faux (case décochée, valeur par défaut) :
le fichier Excel n'est même pas ouvert. Coché, pour chaque ligne de l'audit
identifiée par la colonne `ID erreur`, la colonne `Lien vers le .ppt` est
complétée et le PPT généré. Repris du programme BPA : même nommage de
fichier, mêmes variables de template (`constants.VARIABLES`), même
génération en parallèle.

### `services/ppt.py` — génération d'un PPT depuis le template

```python
generate_ppt(row, output_path, pptx_template_path) -> None
```

Substitution paragraphe par paragraphe des variables du template par les
valeurs de la ligne (voir le docstring du module pour le détail du
découpage PowerPoint). Code repris à l'identique du programme BPA.

### `services/files.py` — fichiers et répertoire de travail

```python
copy_commune_files(lot_name, insee, destination=None,
                   overwrite=True, verbose=True) -> list[str]
purge_workspace(directory=None, keep=(), verbose=True) -> int
list_communes(lot_name) -> list[str]
find_files(directory, extensions) -> list[str]
```

### `services/qgis_project.py` — projet cartographique

```python
class Extent:      is_valid, buffered(ratio)
class Layer:       is_file_based
class QgisProject:
    open(path)                         # classmethod
    title, layers, canvas_extent       # propriétés
    find_layer(name)
    missing_sources()
    check()                            # -> list[str] d'anomalies
    layer_extent(layer)
    pick_zoom_layer(candidates=())
    zoom_to_layer(name, margin=0.05)
    set_canvas_extent(extent)
    set_title(title)
    save_as(path, update_title=True)
```

### `services/qgis_datasource.py` — emprises

```python
class DataSource:  path, delimiter, x_field, y_field, wkt_field,
                   decimal_point, crs, has_geometry
parse_datasource(source) -> DataSource | None
compute_bounds(source, base_dir) -> tuple[float, float, float, float] | None
```

### `services/archive.py` — livrable

```python
create_zip(archive_path, files, verbose=True) -> str
collect_deliverable_files(project_file, source_dir=None,
                          extensions=(".csv",)) -> list[str]
build_deliverable_archive(insee, project_file, source_dir=None,
                          destination=None, verbose=True) -> str
```

### `services/config_io.py` — préférences

```python
load_config(path=None) -> dict
save_config(config, path=None) -> bool
load_and_apply(path=None) -> dict      # charge et pose les chemins
apply_paths(config) -> None
parse_insee_codes(text) -> list[str]
```

### `path_manager.py` — chemins

```python
set_paths(audit_sna=None, workspace=None, deliverable=None)   # vide = défaut
reset_paths()
default_audit_sna_path() -> str
default_workspace_path() -> str
default_prepare_deliverable_path() -> str
```

Trois racines sont surchargeables ; tous les autres chemins en découlent. Le
dossier de préparation dérive d'AUDIT_SNA par défaut, mais peut être fixé
indépendamment : entrée sur un partage, sortie sur le poste.

### `ui/theme.py` — charte graphique

```python
C_BG, C_PANEL, C_CARD, C_TEXT, C_ACCENT, C_GREEN, ...   couleurs
F_TITLE, F_BODY, F_MONO                                 polices
PHASES                                                  étapes affichées
LOG_COLORS                                              préfixe -> couleur
log_color(line) -> str
```

## Dépendances internes

```
services.workflow      -> constants, path_manager,
                          services.{excel, analyse, files, qgis_project, archive}
services.analyse       -> constants, path_manager, services.{excel, ppt}
services.ppt           -> constants
services.archive       -> path_manager, services.files
services.qgis_project  -> services.qgis_datasource
services.excel         -> constants, path_manager
services.files         -> path_manager
services.config_io     -> path_manager
ui.application         -> ui.theme, services.{workflow, files, config_io}
```

**Aucun cycle.** Les dépendances ne vont que dans un sens : interface →
orchestration → services → socle.

`qgis_project` et `qgis_datasource` ne dépendent ni de `path_manager` ni de
`constants` au moment de l'import : ces modules travaillent sur un chemin
quelconque, ce qui les rend réutilisables hors du contexte AUDIT_SNA. Les
imports visibles dans le graphe proviennent de leur bloc `__main__`, local.

## Flux d'exécution

```
Interface : saisie du lot et des codes INSEE
   │
   └─► prepare_lot_deliverables(lot, codes)
          │
          └─► pour chaque commune : prepare_commune_deliverable
                 │
                 ├─ 1. excel.format_excel_file        audit trié → dossier commune
                 ├─ 2. files.purge_workspace          vide le répertoire de travail
                 ├─ 3. files.copy_commune_files       données → répertoire de travail
                 ├─ 4. QgisProject.open + check       contrôle des couches
                 ├─ 5. zoom_to_layer + save_as        carte centrée, nom de la commune
                 └─ 6. archive.build_deliverable      ZIP → dossier Carte
```

Les étapes 1 et 2–6 sont indépendantes : un audit absent n'empêche pas la
production du livrable cartographique.

## Points d'entrée

| Commande | Effet |
|---|---|
| `python main.py` | interface graphique |
| `python -m modop.services.workflow` | lot entier, en console |
| `python -m modop.services.workflow 45001 45002` | communes choisies |
| `python -m modop.services.excel` | tri de l'audit seul |
| `python -m modop.services.analyse` | liens et PPT vierges seuls (voir son bloc `__main__`) |
| `python -m modop.services.files` | copie seule |
| `python -m modop.services.qgis_project` | inventaire des couches |
| `python -m modop.services.qgis_project "carto SNA OK"` | avec couche imposée |
| `python -m modop.services.archive` | constitution du ZIP seul |
| `pytest -q` | les 287 tests |

## Où intervenir

| Besoin | Fichier |
|---|---|
| Chemin ou nom de livrable | `path_manager.py` |
| Couches de centrage | `constants.py` |
| Colonnes de tri de l'audit | `constants.py` |
| Nom des PPT, variables du template | `constants.py` — `PPT_NAME_TEMPLATE`, `VARIABLES` |
| Chemin du template PPT vierge | interface (champ « Template PPT vierge ») ou `path_manager.set_paths(pptx_template=...)` |
| Extensions embarquées dans le ZIP | `archive.py`, `DELIVERABLE_EXTENSIONS` |
| Apparence de l'interface | `ui/theme.py` |
| Nouvelle étape du traitement | nouveau module dans `services/`, appelé par `workflow.py` |