# Architecture technique

Ce document explique les choix de conception et les pièges rencontrés. Le
`README.md` couvre l'usage ; celui-ci s'adresse à qui doit modifier le code.

## Vue d'ensemble

```
main.py
   └── modop/ui/application.py        fenêtre Tkinter
          └── modop/services/workflow.py       orchestration
                 ├── excel.py                  tri de l'audit
                 ├── files.py                  copie et purge
                 ├── qgis_project.py           lecture/écriture du .qgz
                 │      └── qgis_datasource.py calcul d'emprise depuis les CSV
                 └── archive.py                constitution du ZIP
```

Trois règles structurent le découpage :

1. **Un module par étape du mode opératoire.** Chaque service est utilisable
   seul, dispose de son bloc `__main__` et de son fichier de tests.
2. **`workflow.py` n'enchaîne que.** Aucune logique métier ne s'y trouve : il
   appelle, collecte les résultats et rapporte.
3. **`path_manager.py` détient tous les chemins.** Aucun autre module ne
   construit de chemin ni ne code un nom de fichier en dur. C'est ce qui rend
   les tests possibles : rediriger `BUREAU` isole tout le programme.

## Modules

### `services/excel.py`

Trie le fichier d'audit sur `zone 1`, `zone 2`, `sens`, par ordre croissant.

Deux pièges openpyxl y sont neutralisés :

**Les cellules vivantes.** `ws.iter_rows()` ne renvoie pas des valeurs mais les
objets `Cell` de la feuille. Trier cette liste ne déplace rien : chaque tuple
continue de pointer vers sa ligne d'origine. Réécrire à partir de ces objets
revient à lire et écrire au même endroit, chaque écriture corrompant une source
non encore traitée — le fichier finit vide. `_snapshot()` fige valeurs et
styles avant toute écriture.

**Les lignes fantômes.** `ws.max_row` compte les lignes ne portant qu'une mise
en forme résiduelle. Non filtrées, elles remontent en tête du tri et écrasent
les données. `_last_data_row()` cherche la dernière ligne réellement remplie.

La clé de tri (`_sort_key`) produit un triplet `(rang, nombre, texte)`. Le rang
étant comparé en premier, deux valeurs de types différents ne sont jamais
comparées sur leur contenu : aucun `TypeError` n'est structurellement possible.
Ordre obtenu : nombres < dates < texte < cellules vides.

### `services/xlsx_extensions.py`

openpyxl ignore les blocs `<extLst>` des feuilles et les supprime à
l'enregistrement, avec pour seule trace :

```
UserWarning: Data Validation extension is not supported and will be removed
```

Ces blocs portent des fonctionnalités courantes dans un fichier d'audit :
listes déroulantes dont la source est sur une autre feuille, mises en forme
conditionnelles avancées, plages protégées. Vérifié : après un simple
aller-retour `load_workbook` / `save`, le bloc a disparu de l'archive.

Le module les relève **avant** ouverture, puis les réinjecte dans le fichier
enregistré, par manipulation directe du zip. Un point subtil : un fragment
déplacé perd les déclarations d'espaces de noms portées par la balise
`<worksheet>` d'origine, ce qui produirait un XML invalide. `_with_namespaces()`
les rappelle sur le fragment lui-même.

Le procédé est défensif : à la moindre difficulté — archive illisible, feuille
sans balise fermante — le fichier enregistré par openpyxl est conservé tel quel
et le journal signale la perte.

### `services/files.py`

`copy_commune_files()` copie le répertoire QGIS de la commune vers le
répertoire de travail, sous-dossiers compris, en écrasant l'existant.

`purge_workspace()` vide ce répertoire avant chaque commune. **C'est la
fonction la plus importante du traitement par lot** : sans elle, les fichiers
de la commune précédente restent en place et entrent dans l'archive de la
suivante — un livrable contenant les données d'une autre commune, sans le
moindre signal. Le projet modèle est préservé via `keep`.

`list_communes()` lit les codes INSEE présents dans le répertoire QGIS du lot,
ce qui alimente le bouton **Détecter** de l'interface.

### `services/qgis_project.py`

Un `.qgz` est une archive ZIP contenant un `.qgs`, qui est du XML. Le module
manipule ce XML directement.

**Pourquoi pas PyQGIS ?** Il n'est importable que depuis l'environnement Python
de QGIS, ce qui imposerait une installation sur chaque poste et rendrait les
tests impossibles en intégration continue. La contrepartie est qu'il n'y a
aucun rendu graphique : le « zoom » écrit l'emprise que QGIS restaurera à
l'ouverture du projet.

Les fichiers annexes de l'archive — notamment le `.qgd` de stockage auxiliaire
et la base de styles — sont conservés à l'identique lors de l'enregistrement.

### `services/qgis_datasource.py`

**QGIS n'enregistre pas l'emprise des couches vectorielles** dans le `.qgs` : il
la recalcule en lisant les données à l'ouverture. Seules les couches raster et
WMS portent un bloc `<extent>`. Sans ce module, aucune couche de données du
projet ne serait utilisable pour le centrage — et la détection automatique
tomberait sur un fond de plan, dont l'emprise couvre le monde entier.

Le module décode l'URI de source :

```
file:./carto DGFIP.csv?delimiter=;&decimalPoint=,&xField=X DGFIP&yField=Y DGFIP
file:./carto maillage principal.csv?delimiter=;&wktField=zone
```

puis lit le CSV pour calculer les bornes, dans les deux modes de géométrie :
colonnes X/Y, ou champ WKT. L'encodage est deviné (`utf-8-sig` puis `cp1252`),
les exports Excel français n'étant pas en UTF-8.

Limite assumée : **aucune reprojection**. Une couche dans un CRS différent de
celui du projet produirait une emprise dans son propre système.

### `services/archive.py`

Constitue le ZIP à plat — les fichiers homonymes provoquent une erreur explicite
plutôt qu'un écrasement silencieux — puis le copie vers le sous-dossier `Carte`
de la commune.

Le nom de l'archive intermédiaire est dérivé de sa destination
(`os.path.basename(final_path)`) et non reconstruit : la convention de nommage
reste définie dans `path_manager` uniquement.

### `services/workflow.py`

Deux points d'entrée :

```python
prepare_commune_deliverable(lot, insee)      -> DeliverableResult
prepare_lot_deliverables(lot, [insee, ...])  -> LotResult
```

Une commune en échec n'interrompt pas les suivantes : sur un lot de trente,
perdre vingt-neuf livrables parce que la deuxième a un dossier manquant serait
absurde. `stop_on_error=True` inverse ce choix.

Les chaînes Excel et QGIS sont **indépendantes** : un audit absent ou mal formé
produit un avertissement, pas un arrêt.

Deux callbacks optionnels permettent à une interface de suivre l'avancement
sans que le workflow ne connaisse Tkinter :

```python
on_start(position, total, insee)          # avant chaque commune
on_result(insee, resultat, erreur)        # après chaque commune
```

### `ui/theme.py`

Couleurs, polices, libellés d'étapes et correspondance préfixe de journal →
couleur. **Aucune couleur n'apparaît dans `application.py`.** Deux bénéfices :
changer la charte ne touche qu'un fichier, et le thème se teste sans affichage
graphique — `test_ui_theme.py` tourne en intégration continue.

### `ui/application.py`

**Tkinter n'est pas thread-safe.** Seul le thread principal peut toucher aux
widgets. Le traitement s'exécute donc dans un thread de travail qui se contente
d'empiler des messages dans une `queue.Queue`, tandis qu'un poller replanifié
par `after()` vide cette file et met à jour l'affichage.

```
thread de travail          queue.Queue          thread principal
─────────────────          ───────────          ────────────────
prepare_lot_...()  ──put──►  ("log", ...)  ──get──►  _append_log()
                             ("progress",…)          _update_progress()
                             ("result", …)           _add_result()
                             ("done", bilan)         _finish()
```

**Capture du journal.** Les services journalisent avec `print`.
`contextlib.redirect_stdout` détourne cette sortie vers la file pendant le
traitement, via `_QueueWriter`. Le journal de l'interface est donc identique à
celui de la console, et les services restent utilisables en ligne de commande
sans dépendre de l'interface.

C'est un compromis assumé : `redirect_stdout` agit sur `sys.stdout`, qui est
global. Un seul traitement pouvant s'exécuter à la fois, la contrainte est sans
effet ici. Si le programme devait un jour lancer plusieurs traitements en
parallèle, il faudrait passer les services à une journalisation par callback ou
via le module `logging`.

## Tests

199 tests, sans QGIS, sans affichage, sans arborescence réelle.

| Fichier | Portée |
|---|---|
| `test_excel.py` | tri, clés, lignes fantômes, structures de fichier |
| `test_files.py` | copie, filtrage par extension |
| `test_lot.py` | découverte, purge, traitement multi-communes, callbacks |
| `test_qgis_project.py` | lecture, contrôles, zoom, enregistrement |
| `test_qgis_datasource.py` | analyse d'URI, calcul d'emprise, encodages |
| `test_archive.py` | constitution du ZIP, dépôt |
| `test_workflow.py` | intégration bout en bout |
| `test_config_io.py` | préférences, analyse de la saisie |
| `test_ui_theme.py` | cohérence du thème |

**L'isolation tient à une seule ligne :**

```python
monkeypatch.setattr(path_manager, "BUREAU", str(dossier_temporaire))
```

Tous les chemins dérivent de cette variable, lue à chaque appel de fonction.
Cela fonctionne même pour les modules qui importent les fonctions de chemin
directement, la fonction résolvant `BUREAU` dans son propre module au moment de
l'appel.

**Les fixtures dérivent les noms de `path_manager`**, jamais en dur. Un test
garde-fou, `test_le_modele_suit_path_manager`, échoue explicitement si cette
règle est enfreinte — sans lui, renommer un fichier dans `path_manager` produit
vingt échecs qui pointent tous vers le code de production.

## Faire évoluer le programme

| Besoin | Fichier |
|---|---|
| Changer un chemin ou un nom de livrable | `path_manager.py` |
| Changer les couches de centrage | `constants.py` |
| Changer les extensions embarquées | `archive.py`, `DELIVERABLE_EXTENSIONS` |
| Changer l'apparence | `ui/theme.py` |
| Ajouter une étape au traitement | un nouveau module dans `services/`, appelé depuis `workflow.py` |

## Limites connues

**Pas de rendu graphique.** Le contrôle visuel des couches reste à faire dans
QGIS. Le programme vérifie ce qui est vérifiable sans moteur de rendu :
présence des couches, existence des fichiers sources, validité des emprises.

**Pas de reprojection.** Toutes les couches doivent partager le CRS du projet.

**Les formules Excel ne sont pas translatées.** Leurs références relatives
pointent vers les anciens numéros de ligne après tri. Un avertissement est émis.
`openpyxl.formula.translate.Translator` permettrait de les réécrire si le besoin
apparaît.

**Une emprise réduite à un point** est rejetée : cadrer dessus demanderait une
distance arbitraire. Le cas se présente pour une couche à un seul objet.