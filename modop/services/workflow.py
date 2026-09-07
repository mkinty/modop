"""Orchestration du livrable d'une commune.

Enchaine les huit etapes du mode operatoire :

    1. creer l'arborescence de la commune (Carte et Analyse) ;
    2. trier le fichier Excel d'audit et le deposer dans le dossier commune ;
    3. completer la colonne "Lien vers le .ppt" de l'audit et, si demande,
       generer les PPT vierges correspondants dans le dossier Analyse ;
    4. copier les fichiers QGIS de la commune vers le repertoire de travail ;
    5. ouvrir le projet QGIS modele ;
    6. controler les couches, puis centrer la carte sur la commune ;
    7. enregistrer le projet au nom de la commune ;
    8. compresser les .csv et le projet, et deposer l'archive dans Carte.

Chaque etape est deleguee a un module dedie. Ce module ne fait qu'enchainer
et rapporter.

Le fichier Excel n'entre pas dans l'archive : il est livre a part, dans le
dossier de la commune, ou excel.py le depose.

Deux points d'entree :
    prepare_commune_deliverable(lot, insee)    une commune
    prepare_lot_deliverables(lot, [insee, ...]) un lot entier
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Sequence

from modop.constants import ZOOM_LAYER_CANDIDATES
from modop.path_manager import (
    _excel_source_file_path,
    _insee_analyse_path,
    _insee_carte_path,
    _qgis_project_path,
    _qgis_saved_project_path,
    _workspace_path,
    verifier_racine_audit_sna,
)
from modop.services.analyse import (
    PptTemplateError,
    generer_ppts_commune,
    valider_template_ppt,
)
from modop.services.archive import build_deliverable_archive
from modop.services.excel import format_excel_file
from modop.services.files import copy_commune_files, list_communes, purge_workspace
from modop.services.qgis_project import QgisProject


@dataclass
class DeliverableResult:
    """Resultat d'un traitement de commune."""

    insee: str
    carte_dir: str = ""
    analysis_dir: str = ""
    excel_file: str = ""
    ppt_liens: int = 0
    ppt_generes: int = 0
    copied_files: list[str] = field(default_factory=list)
    project_file: str = ""
    archive_file: str = ""
    zoom_layer: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Vrai si l'archive du livrable a bien ete produite."""
        return bool(self.archive_file) and os.path.isfile(self.archive_file)

    @property
    def complete(self) -> bool:
        """Vrai si l'archive et le fichier Excel trie sont tous deux presents."""
        return self.ok and bool(self.excel_file) and os.path.isfile(self.excel_file)


@dataclass
class LotResult:
    """Resultat du traitement d'un lot entier."""

    lot_name: str
    results: dict[str, DeliverableResult] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def processed(self) -> list[str]:
        """Codes INSEE traites, en succes comme en echec."""
        return sorted(set(self.results) | set(self.errors))

    @property
    def succeeded(self) -> list[str]:
        """Codes INSEE dont l'archive a bien ete produite."""
        return sorted(insee for insee, r in self.results.items() if r.ok)

    @property
    def failed(self) -> list[str]:
        """Codes INSEE en echec, exception ou archive absente."""
        return sorted(
            set(self.errors) | {i for i, r in self.results.items() if not r.ok}
        )

    @property
    def ok(self) -> bool:
        """Vrai si toutes les communes traitees ont abouti."""
        return bool(self.processed) and not self.failed

    @property
    def warnings(self) -> dict[str, list[str]]:
        """Avertissements par commune, communes sans anomalie exclues."""
        return {i: r.warnings for i, r in self.results.items() if r.warnings}


def _sort_audit_file(lot_name: str, insee: str, warnings: list[str]) -> str:
    """Trie le fichier Excel d'audit et le depose dans le dossier commune.

    Une absence ou un echec est signale dans `warnings` : le livrable QGIS
    reste produit, les deux chaines etant independantes.

    Returns:
        Chemin du fichier trie, ou chaine vide en cas d'echec.
    """
    source = _excel_source_file_path(lot_name, insee)
    if not os.path.isfile(source):
        warnings.append(f"Fichier d'audit absent : {source}")
        return ""

    # verbose=False : excel.py a sa propre journalisation, on conserve ici le
    # format [etape] commun au workflow. Les erreurs restent affichees.
    result = format_excel_file(lot_name, insee, verbose=False)
    if result is None:
        warnings.append(f"Tri du fichier d'audit echoue : {source}")
        return ""

    return result


def _generer_ppts_analyse(
    excel_file: str,
    insee: str,
    pptx_template_path: str | None,
    generate_ppts: bool,
    warnings: list[str],
    verbose: bool,
) -> tuple[int, int]:
    """Complète la colonne "Lien vers le .ppt" et génère les PPT vierges.

    Le contrôle du template (obligatoire si `generate_ppts` est vrai) se
    fait quel que soit l'état de l'audit : un template manquant ou
    introuvable est une erreur de configuration, indépendante de la présence
    du fichier Excel. Voir `services.analyse.generer_ppts_commune`.

    Returns:
        (liens complétés, PPT générés).

    Raises:
        PptTemplateError: la case est cochée sans template PPT valide.
    """
    resultat = generer_ppts_commune(
        excel_file, insee, pptx_template_path, generate_ppts, verbose=verbose,
    )
    warnings.extend(resultat.avertissements)
    return resultat.liens_completes, resultat.ppt_generes


def _pick_zoom_layer(project: QgisProject, requested: str | None) -> str:
    """Determine la couche sur laquelle centrer la carte.

    Sans couche demandee, le projet choisit parmi les candidats declares dans
    les constantes.

    Raises:
        LookupError: aucune couche exploitable.
    """
    return requested or project.pick_zoom_layer(ZOOM_LAYER_CANDIDATES)


def prepare_commune_deliverable(
    lot_name: str,
    insee: str,
    zoom_layer: str | None = None,
    project_path: str | None = None,
    sort_excel: bool = True,
    clean_workspace: bool = True,
    strict: bool = False,
    pptx_template_path: str | None = None,
    generate_ppts: bool = False,
    verbose: bool = True,
) -> DeliverableResult:
    """Produit le livrable complet d'une commune : audit trie et archive QGIS.

    Args:
        lot_name: nom du lot (ex. "Lot7").
        insee: code INSEE de la commune (ex. "45001").
        zoom_layer: couche de centrage. Detectee automatiquement si omise.
        project_path: projet QGIS source. Par defaut, celui que designe
            path_manager.
        sort_excel: traite le fichier d'audit. False pour ne produire que le
            livrable QGIS.
        clean_workspace: vide le repertoire de travail avant la copie, en
            preservant le projet modele. A laisser actif pour eviter qu'une
            commune herite des fichiers d'une autre.
        strict: si True, la moindre anomalie interrompt le traitement.
        pptx_template_path: chemin du template PPT vierge, configurable
            depuis l'interface. Sans effet si `generate_ppts` est faux.
        generate_ppts: correspond a la case a cocher de l'interface. Vide par
            defaut : les PPT ne sont generes que si elle est cochee. La
            colonne "Lien vers le .ppt" est completee dans tous les cas.
        verbose: affiche la progression.

    Returns:
        Un DeliverableResult decrivant le traitement.

    Raises:
        FileNotFoundError: repertoire source ou projet QGIS absent.
        ValueError: anomalie rencontree en mode strict.
        LookupError: couche de centrage introuvable.
    """

    def log(message: str) -> None:
        if verbose:
            print(message)

    def stop_if_strict() -> None:
        """Interrompt a la premiere anomalie, si le mode strict est actif."""
        if strict and result.warnings:
            raise ValueError(f"Traitement interrompu : {result.warnings[0]}")

    result = DeliverableResult(insee=insee)

    # -- 1. Arborescence de la commune -------------------------------------
    # Les deux fonctions creent le dossier au passage. Analyse reste vide a
    # ce stade : elle accueille les pieces produites hors de ce traitement.
    result.carte_dir = _insee_carte_path(insee)
    result.analysis_dir = _insee_analyse_path(insee)
    log(f"[dossier] commune {insee} : Carte et Analyse prêts")

    # -- 2. Fichier d'audit -------------------------------------------------
    if sort_excel:
        result.excel_file = _sort_audit_file(lot_name, insee, result.warnings)
        if result.excel_file:
            log(f"[excel] trie : {result.excel_file}")
        else:
            log(f"[excel] ⚠ {result.warnings[-1]}")
        stop_if_strict()

    # -- 3. Liens PPT et generation des PPT vierges ------------------------
    # Le controle du template (si `generate_ppts`) est volontairement non
    # rattrape ici : une erreur de configuration ne doit pas etre reduite a
    # un simple avertissement. Elle est en outre re-levee telle quelle par
    # `prepare_lot_deliverables`, qui ne la traite pas comme un echec de
    # cette seule commune (voir plus bas).
    try:
        result.ppt_liens, result.ppt_generes = _generer_ppts_analyse(
            result.excel_file, insee, pptx_template_path, generate_ppts,
            result.warnings, verbose,
        )
    except PptTemplateError as error:
        log(f"[ppt] ❌ {error}")
        raise
    if result.ppt_liens:
        log(f"[ppt] {result.ppt_liens} lien(s) complété(s)"
            + (f", {result.ppt_generes} PPT généré(s)" if generate_ppts else ""))
    stop_if_strict()

    # -- 4. Copie des fichiers vers le repertoire de travail ---------------
    source_project = project_path or _qgis_project_path()

    # La purge evite qu'une commune herite des fichiers de la precedente :
    # ils entreraient dans son archive. Le projet modele est preserve.
    if clean_workspace:
        purge_workspace(keep=(source_project,), verbose=verbose)

    result.copied_files = copy_commune_files(lot_name, insee, verbose=verbose)

    # -- 5. Ouverture du projet -------------------------------------------
    project = QgisProject.open(source_project)
    log(f"[qgis] projet ouvert : {os.path.basename(source_project)} "
        f"({len(project.layers)} couche(s))")

    # -- 6. Controles et centrage ------------------------------------------
    # Le projet est ouvert depuis le workspace : les sources relatives
    # pointent donc vers les fichiers qui viennent d'etre copies.
    anomalies = project.check()
    result.warnings.extend(anomalies)
    for anomalie in anomalies:
        log(f"[qgis] ⚠ {anomalie}")
    stop_if_strict()

    result.zoom_layer = _pick_zoom_layer(project, zoom_layer)
    extent = project.zoom_to_layer(result.zoom_layer)
    log(f"[qgis] centrage sur '{result.zoom_layer}' "
        f"({extent.xmin:.0f}, {extent.ymin:.0f}) -> ({extent.xmax:.0f}, {extent.ymax:.0f})")

    # -- 7. Enregistrement au nom de la commune ----------------------------
    # Meme repertoire que les donnees, pour que les sources relatives restent
    # valides.
    result.project_file = project.save_as(_qgis_saved_project_path(insee))
    log(f"[qgis] enregistre : {os.path.basename(result.project_file)}")

    # -- 8. Archive du livrable --------------------------------------------
    result.archive_file = build_deliverable_archive(
        insee,
        project_file=result.project_file,
        source_dir=_workspace_path(),
        verbose=verbose,
    )

    log(f"[ok] livrable {insee} : {result.archive_file}")
    return result




def prepare_lot_deliverables(
    lot_name: str,
    insee_codes: Sequence[str | int] | None = None,
    zoom_layer: str | None = None,
    project_path: str | None = None,
    sort_excel: bool = True,
    strict: bool = False,
    stop_on_error: bool = False,
    pptx_template_path: str | None = None,
    generate_ppts: bool = False,
    on_start: Callable[[int, int, str], None] | None = None,
    on_result: Callable[[str, "DeliverableResult | None", str], None] | None = None,
    verbose: bool = True,
) -> LotResult:
    """Produit les livrables de plusieurs communes d'un meme lot.

    Les communes sont traitees en sequence et de facon independante : l'echec
    de l'une n'interrompt pas les suivantes, sauf `stop_on_error`. Le
    repertoire de travail est purge avant chaque commune.

    Args:
        lot_name: nom du lot (ex. "Lot7").
        insee_codes: codes INSEE a traiter (ex. [45001, 45002]). Si omis, les
            communes sont decouvertes dans le repertoire QGIS du lot.
        zoom_layer: couche de centrage, commune a toutes les communes.
        project_path: projet QGIS source. Par defaut, celui que designe
            path_manager.
        sort_excel: traite les fichiers d'audit.
        strict: une anomalie fait echouer la commune concernee.
        stop_on_error: interrompt le lot a la premiere commune en echec.
        pptx_template_path: chemin du template PPT vierge, commun a toutes
            les communes.
        generate_ppts: correspond a la case a cocher de l'interface. Vide par
            defaut : les PPT ne sont generes que si elle est cochee.
        on_start: appele avant chaque commune, avec (position, total, insee).
            Permet a une interface de suivre l'avancement.
        on_result: appele apres chaque commune, avec (insee, resultat, erreur).
            `resultat` vaut None en cas d'echec, `erreur` est vide en cas de
            succes.
        verbose: affiche la progression.

    Returns:
        Un LotResult recapitulant chaque commune.

    Raises:
        ValueError: aucune commune a traiter.
        PptTemplateError: `generate_ppts` est vrai sans template PPT valide
            configuré. Erreur de configuration : arrête tout le lot avant
            même de commencer la première commune, contrairement aux autres
            erreurs qui ne font échouer que la commune concernée.
        Exception: relayee telle quelle si `stop_on_error`.
    """

    def log(message: str) -> None:
        if verbose:
            print(message)

    # Erreurs de configuration, pas des anomalies de commune : verifiees une
    # bonne fois pour toutes avant de commencer, plutot que de les decouvrir
    # au milieu du lot, a l'identique, sur chaque commune.
    try:
        verifier_racine_audit_sna()
    except OSError as error:
        log(f"[config] ❌ {error}")
        raise

    if generate_ppts:
        try:
            valider_template_ppt(pptx_template_path)
        except PptTemplateError as error:
            log(f"[ppt] ❌ {error}")
            raise

    # Les codes peuvent arriver en entiers : [45001, 45002].
    if insee_codes is None:
        codes = list_communes(lot_name)
        log(f"[lot {lot_name}] {len(codes)} commune(s) detectee(s)")
    else:
        codes = [str(code).strip() for code in insee_codes if str(code).strip()]

    if not codes:
        raise ValueError(f"Aucune commune a traiter pour le lot '{lot_name}'.")

    result = LotResult(lot_name=lot_name)

    for position, insee in enumerate(codes, start=1):
        log("")
        log(f"===== [{position}/{len(codes)}] commune {insee} " + "=" * 30)

        if on_start is not None:
            on_start(position, len(codes), insee)

        try:
            commune = prepare_commune_deliverable(
                lot_name,
                insee,
                zoom_layer=zoom_layer,
                project_path=project_path,
                sort_excel=sort_excel,
                clean_workspace=True,
                strict=strict,
                pptx_template_path=pptx_template_path,
                generate_ppts=generate_ppts,
                verbose=verbose,
            )
            result.results[insee] = commune

            if on_result is not None:
                on_result(insee, commune, "")

        except PptTemplateError:
            # Erreur de configuration : ne doit pas etre reduite a un echec
            # de cette seule commune. Arrete tout le lot, quel que soit
            # `stop_on_error`.
            raise

        except Exception as error:
            # Une commune en echec ne doit pas faire perdre les precedentes.
            message = f"{type(error).__name__} : {error}"
            result.errors[insee] = message
            log(f"[ko] commune {insee} : {message}")

            if on_result is not None:
                on_result(insee, None, message)

            if stop_on_error:
                raise

    log("")
    log(f"===== bilan du lot {lot_name} " + "=" * 30)
    log(f"[lot] {len(result.succeeded)}/{len(codes)} livrable(s) produit(s)")

    if result.failed:
        log(f"[lot] ⚠ en echec : {', '.join(result.failed)}")

    for insee, messages in result.warnings.items():
        for message in messages:
            log(f"[lot] ⚠ {insee} : {message}")

    return result


if __name__ == "__main__":
    # Une commune :
    #     uv run python -m modop.services.workflow 45001
    # Un lot entier (communes decouvertes automatiquement) :
    #     uv run python -m modop.services.workflow
    # Plusieurs communes choisies :
    #     uv run python -m modop.services.workflow 45001 45002
    import sys

    from modop.services.config_io import load_and_apply

    # Les chemins et options choisis dans l'interface s'appliquent aussi en
    # console (dont le template PPT et la case "Générer les PPT").
    _config = load_and_apply()

    LOT = "Lot7"
    codes = sys.argv[1:] or None

    bilan = prepare_lot_deliverables(
        LOT, codes,
        pptx_template_path=_config.get("pptx_template_path") or None,
        generate_ppts=_config.get("generate_ppts", False),
    )

    print()
    for insee in bilan.processed:
        commune = bilan.results.get(insee)
        etat = "OK  " if commune and commune.ok else "ECHEC"
        detail = commune.archive_file if commune and commune.ok else bilan.errors.get(insee, "")
        print(f"  {etat} {insee} : {detail}")