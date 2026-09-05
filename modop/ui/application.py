"""Fenetre principale de l'application MODOP.

L'interface ne contient aucune logique metier : elle collecte une saisie, la
transmet a `modop.services.workflow` et affiche ce qui remonte.

CONCURRENCE
-----------
Tkinter n'est pas thread-safe : seul le thread principal peut toucher aux
widgets. Le traitement s'execute donc dans un thread de travail qui se
contente d'empiler des messages dans `self._queue`, tandis qu'un poller
(`_poll`, replanifie par `after`) vide cette file et met a jour l'affichage.

JOURNALISATION
--------------
Les services ecrivent leur progression avec `print`. Plutot que de les
modifier, la sortie standard est redirigee vers la file pendant le
traitement : le journal de l'interface reste identique a celui de la console,
et les services restent utilisables en ligne de commande.
"""

from __future__ import annotations

import contextlib
import io
import traceback
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from modop.services.config_io import (
    apply_paths, load_and_apply, parse_insee_codes, save_config,
)
from modop.path_manager import (
    default_audit_sna_path,
    default_prepare_deliverable_path,
    default_workspace_path,
)
from modop import path_manager
from modop.services.files import list_communes
from modop.services.workflow import prepare_lot_deliverables

from .theme import (
    C_ACCENT, C_AMBER, C_BG, C_BORDER, C_BORDER2, C_CARD, C_CYAN, C_GREEN,
    C_LOG_BG, C_LOG_HEAD, C_LOG_TITLE, C_MUTED, C_PANEL, C_PANEL2, C_RED,
    C_TEXT, C_TEXT2, F_BODY, F_MONO, F_TITLE, PHASES, log_color,
)

#: Periode de relecture de la file, en millisecondes. Assez court pour que le
#: journal defile de facon fluide, assez long pour ne pas saturer la boucle.
POLL_INTERVAL_MS = 120

#: Delai sans le moindre message avant de considerer le traitement figé et
#: d'afficher ou se trouve le thread de travail. Une commune volumineuse peut
#: rester silencieuse un moment : le seuil est large.
WATCHDOG_SECONDS = 90


class _QueueWriter(io.TextIOBase):
    """Fichier virtuel qui redirige `print` vers une file de messages.

    Les services ecrivent ligne par ligne ; `print` emet le texte puis le
    retour a la ligne en deux appels, d'ou le tampon.
    """

    def __init__(self, target: queue.Queue):
        self._queue = target
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._queue.put(("log", line))
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._queue.put(("log", self._buffer))
            self._buffer = ""


class App(tk.Tk):
    """Fenetre principale."""

    def __init__(self):
        super().__init__()
        self.title("MODOP — Livrables audit SNA")
        self.geometry("1080x780")
        self.minsize(940, 620)
        self.configure(bg=C_BG)

        # load_and_apply : les chemins enregistres sont poses avant toute
        # utilisation des services.
        self.config_data = load_and_apply()
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._started_at = None
        self._worker_thread: threading.Thread | None = None
        self._last_message_at = 0.0
        self._watchdog_fired = False
        self._log_visible = False
        self._phase_dots: dict[str, tk.Label] = {}

        self._build_styles()
        self._build_ui()
        self._restore_config()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Sans cette redirection, une erreur survenue dans un rappel Tkinter
        # part sur la sortie d'erreur, invisible si l'application est lancee
        # depuis le Finder ou un raccourci.
        self.report_callback_exception = self._on_tk_error

    def _on_tk_error(self, exc_type, value, tb) -> None:
        """Journalise une erreur survenue dans un rappel Tkinter."""
        detail = "".join(traceback.format_exception(exc_type, value, tb)).rstrip()
        for ligne in detail.splitlines():
            self._append_log(f"[ko] {ligne}")

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------

    def _build_styles(self) -> None:
        """Applique le theme aux widgets ttk, qui ignorent les options tk."""
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Treeview", background=C_CARD, foreground=C_TEXT2,
            fieldbackground=C_CARD, rowheight=28, font=(F_BODY, 10),
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading", background=C_PANEL2, foreground=C_ACCENT,
            font=(F_BODY, 9, "bold"), relief="flat", padding=6,
        )
        style.map(
            "Treeview",
            background=[("selected", "#243150")],
            foreground=[("selected", "white")],
        )
        style.configure(
            "modop.Horizontal.TProgressbar", troughcolor=C_PANEL2,
            background=C_ACCENT, darkcolor=C_ACCENT, lightcolor=C_ACCENT,
            bordercolor=C_PANEL2, thickness=12,
        )

    def _build_ui(self) -> None:
        self._build_header()
        self._build_log_page()

        self.page_main = tk.Frame(self, bg=C_BG)
        self.page_main.pack(fill="both", expand=True)

        # La page defile : son contenu depasse la fenetre des que la carte de
        # configuration est deployee.
        contenu = self._build_scrollable(self.page_main)

        self._build_config_card(contenu)
        self._build_progress_card(contenu)
        self._build_results_card(contenu)

        # Marge de fin, pour que la derniere carte ne colle pas au bord bas.
        tk.Frame(contenu, bg=C_BG, height=18).pack(fill="x")

    def _build_scrollable(self, parent) -> tk.Frame:
        """Rend une zone defilante et renvoie le cadre ou placer le contenu.

        Le cadre interieur est place dans un canvas ; sa hauteur pilote la
        zone de defilement, sa largeur suit celle du canvas pour que les
        cartes occupent toute la largeur disponible.
        """
        self.canvas = tk.Canvas(parent, bg=C_BG, highlightthickness=0)
        barre = ttk.Scrollbar(parent, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=barre.set)

        barre.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        cadre = tk.Frame(self.canvas, bg=C_BG)
        fenetre = self.canvas.create_window((0, 0), window=cadre, anchor="nw")

        cadre.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(
            fenetre, width=e.width))

        # Molette : Windows et macOS emettent <MouseWheel>, X11 des boutons 4/5.
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", lambda _e: self._scroll(-1))
        self.bind_all("<Button-5>", lambda _e: self._scroll(1))

        return cadre

    def _on_mousewheel(self, event) -> None:
        # delta vaut ±120 par cran sous Windows, ±1 sous macOS.
        self._scroll(-1 if event.delta > 0 else 1)

    def _scroll(self, pas: int) -> None:
        """Fait defiler la page principale, sauf si le journal est affiche."""
        if not self._log_visible:
            self.canvas.yview_scroll(pas, "units")

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=C_PANEL, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=C_PANEL)
        left.pack(side="left", padx=20)
        tk.Label(left, text="🗺", font=(F_BODY, 22), bg=C_PANEL,
                 fg=C_ACCENT).pack(side="left", pady=11)

        titles = tk.Frame(left, bg=C_PANEL)
        titles.pack(side="left", padx=10)
        tk.Label(titles, text="MODOP — Livrables audit SNA",
                 font=(F_TITLE, 15, "bold"), bg=C_PANEL,
                 fg=C_TEXT).pack(anchor="w", pady=(10, 0))
        tk.Label(titles, text="Audit trié · Projet QGIS · Archive livrable",
                 font=(F_BODY, 8), bg=C_PANEL, fg=C_MUTED).pack(anchor="w")

        self.lbl_state = tk.Label(header, text="●  Prêt", font=(F_BODY, 10, "bold"),
                                  bg=C_PANEL, fg=C_GREEN)
        self.lbl_state.pack(side="right", padx=(0, 18))

        tk.Button(header, text="📋 Journal", command=self._toggle_log,
                  bg=C_PANEL2, fg=C_LOG_TITLE, font=(F_BODY, 10, "bold"),
                  relief="flat", cursor="hand2", padx=16).pack(
            side="right", padx=10, pady=16)

    def _build_log_page(self) -> None:
        """Page journal, masquee par defaut et affichee a la demande."""
        self.page_log = tk.Frame(self, bg=C_LOG_BG)

        head = tk.Frame(self.page_log, bg=C_LOG_HEAD, height=44)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="   📋 Journal du traitement",
                 font=(F_TITLE, 12, "bold"), bg=C_LOG_HEAD,
                 fg=C_LOG_TITLE).pack(side="left")

        tk.Button(head, text="💾 Exporter", font=(F_BODY, 9), bg=C_PANEL2,
                  fg=C_TEXT2, relief="flat", cursor="hand2",
                  command=self._export_log).pack(side="right", padx=(0, 10), pady=8)
        tk.Button(head, text="🗑 Effacer", font=(F_BODY, 9), bg=C_PANEL2,
                  fg=C_TEXT2, relief="flat", cursor="hand2",
                  command=self._clear_log).pack(side="right", padx=6, pady=8)
        tk.Button(head, text="◀ Retour", font=(F_BODY, 9, "bold"), bg=C_ACCENT,
                  fg="white", relief="flat", cursor="hand2", padx=14,
                  command=self._toggle_log).pack(side="right", padx=6, pady=8)

        wrap = tk.Frame(self.page_log, bg=C_LOG_BG)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        self.txt_log = tk.Text(wrap, bg=C_LOG_BG, fg=C_TEXT2, font=(F_MONO, 10),
                               relief="flat", state="disabled", wrap="word",
                               padx=10, pady=8)
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")

    def _card(self, parent, title: str, icon: str, accent: str, subtitle: str = "",
              expand: bool = False) -> tk.Frame:
        """Cadre titre reutilisable. Renvoie le conteneur de son contenu."""
        wrap = tk.Frame(parent, bg=C_BORDER)
        wrap.pack(fill="both" if expand else "x", expand=expand, padx=18, pady=(14, 0))

        inner = tk.Frame(wrap, bg=C_CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(inner, bg=C_CARD)
        head.pack(fill="x", padx=16, pady=(12, 2))
        tk.Frame(head, bg=accent, width=4, height=18).pack(side="left", padx=(0, 10))

        titles = tk.Frame(head, bg=C_CARD)
        titles.pack(side="left")
        tk.Label(titles, text=f"{icon}  {title}", font=(F_TITLE, 12, "bold"),
                 bg=C_CARD, fg=C_TEXT).pack(anchor="w")
        if subtitle:
            tk.Label(titles, text=subtitle, font=(F_BODY, 8), bg=C_CARD,
                     fg=C_MUTED).pack(anchor="w")

        body = tk.Frame(inner, bg=C_CARD)
        body.pack(fill="both", expand=True, padx=16, pady=(8, 14))
        return body

    #: Largeur de la colonne des libelles, en caracteres. Fixe pour que tous
    #: les champs s'alignent verticalement.
    LABEL_WIDTH = 22

    def _row(self, parent) -> tk.Frame:
        """Ligne de formulaire : un libelle a gauche, un champ a droite."""
        row = tk.Frame(parent, bg=C_CARD)
        row.pack(fill="x", pady=(0, 10))
        return row

    #: Police des intitules de champ : taille du corps de texte, en gras pour
    #: que l'oeil accroche la structure du formulaire.
    F_LABEL = (F_BODY, 9, "bold")

    def _label(self, row, text: str, anchor: str = "w", width: int | None = None) -> None:
        tk.Label(row, text=text, font=self.F_LABEL, bg=C_CARD, fg=C_TEXT2,
                 width=self.LABEL_WIDTH if width is None else width,
                 anchor=anchor).pack(side="left", padx=(0, 10), pady=(6, 0))

    def _make_entry(self, parent) -> tk.Entry:
        """Champ de saisie nu, aux couleurs du theme."""
        return tk.Entry(parent, font=(F_BODY, 10), bg=C_PANEL2, fg=C_TEXT,
                        insertbackground=C_ACCENT, relief="flat",
                        highlightthickness=1, highlightbackground=C_BORDER2,
                        highlightcolor=C_ACCENT)

    def _hint(self, parent, text: str) -> tk.Label:
        """Ligne d'aide sous un champ. Renvoie le libellé, pour pouvoir le
        mettre à jour."""
        label = tk.Label(parent, text=text, font=(F_BODY, 8), bg=C_CARD,
                         fg=C_MUTED)
        label.pack(anchor="w", pady=(2, 0))
        return label

    #: Largeur des libelles dans une paire de colonnes. Identique a
    #: LABEL_WIDTH pour que tous les champs de la carte s'alignent sur une
    #: seule grille verticale, quelle que soit la ligne.
    PAIR_LABEL_WIDTH = LABEL_WIDTH

    def _entry_pair(self, parent, gauche: tuple[str, str],
                    droite: tuple[str, str]) -> tuple[tk.Entry, tk.Entry]:
        """Deux champs cote a cote, chacun precede de son libelle.

        Args:
            gauche: (libelle, aide) du premier champ.
            droite: (libelle, aide) du second.

        Returns:
            Les deux champs, dans l'ordre.
        """
        row = self._row(parent)
        champs = []

        for index, (label, hint) in enumerate((gauche, droite)):
            colonne = tk.Frame(row, bg=C_CARD)
            colonne.pack(side="left", fill="x", expand=True,
                         padx=(0, 18) if index == 0 else 0)

            ligne = tk.Frame(colonne, bg=C_CARD)
            ligne.pack(fill="x")

            tk.Label(ligne, text=label, font=self.F_LABEL, bg=C_CARD, fg=C_TEXT2,
                     width=self.PAIR_LABEL_WIDTH, anchor="w").pack(
                side="left", padx=(0, 8))

            entry = self._make_entry(ligne)
            entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)
            champs.append(entry)

            if hint:
                # Aide alignee sous le champ, pas sous le libelle.
                aide = tk.Frame(colonne, bg=C_CARD)
                aide.pack(fill="x")
                tk.Frame(aide, bg=C_CARD, width=self.PAIR_LABEL_WIDTH * 8).pack(side="left")
                self._hint(aide, hint)

        return champs[0], champs[1]

    def _entry_row(self, parent, label: str, hint: str = "",
                   browse: bool = False, browse_file: bool = False) -> tk.Entry:
        """Ligne comportant un champ texte sur une seule ligne.

        Args:
            label: libelle affiche a gauche.
            hint: aide affichee sous le champ.
            browse: ajoute un bouton de selection de dossier.
            browse_file: ajoute un bouton de selection de fichier PPTX, a la
                place du selecteur de dossier. Ignore si `browse` est faux.
        """
        row = self._row(parent)
        self._label(row, label)

        right = tk.Frame(row, bg=C_CARD)
        right.pack(side="left", fill="x", expand=True)

        line = tk.Frame(right, bg=C_CARD)
        line.pack(fill="x")

        entry = self._make_entry(line)
        entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)

        if browse:
            command = (lambda: self._browse_file(entry)) if browse_file \
                else (lambda: self._browse(entry))
            tk.Button(line, text="📁", command=command,
                      bg=C_PANEL2, fg=C_TEXT2, font=(F_BODY, 10), relief="flat",
                      cursor="hand2", padx=10).pack(side="left", padx=(6, 0), ipady=3)

        # L'aide est toujours créée : son texte peut devoir être recalculé.
        entry.hint_label = self._hint(right, hint)

        return entry

    def _browse(self, entry: tk.Entry) -> None:
        """Ouvre un selecteur de dossier et renseigne le champ."""
        chosen = filedialog.askdirectory(initialdir=entry.get() or None)
        if chosen:
            entry.delete(0, "end")
            entry.insert(0, os.path.normpath(chosen))
            self._refresh_deliverable_hint()

    def _browse_file(self, entry: tk.Entry) -> None:
        """Ouvre un selecteur de fichier PPTX et renseigne le champ."""
        initial = os.path.dirname(entry.get()) or None
        chosen = filedialog.askopenfilename(
            initialdir=initial,
            filetypes=[("Modèle PowerPoint", "*.pptx"), ("Tous les fichiers", "*.*")],
        )
        if chosen:
            entry.delete(0, "end")
            entry.insert(0, os.path.normpath(chosen))

    def _refresh_deliverable_hint(self) -> None:
        """Recalcule l'aide du dossier de préparation des livrables.

        Son emplacement par défaut est un sous-dossier d'AUDIT_SNA : il change
        dès que l'utilisateur redéfinit celui-ci.
        """
        saisi = self.ent_audit.get().strip()
        racine = saisi or default_audit_sna_path()
        defaut = os.path.join(racine, path_manager.DEFAULT_DELIVERABLE_DIR)
        self.ent_deliverable.hint_label.configure(text=f"Vide = {defaut}")

    def _build_config_card(self, parent) -> None:
        """Carte de configuration : un champ par ligne."""
        body = self._card(parent, "Configuration", "⚙️", C_ACCENT,
                          "Chemins, lot et communes — mémorisés d'une session à l'autre")

        self.ent_audit = self._entry_row(
            body, "Dossier AUDIT_SNA",
            hint=f"Vide = {default_audit_sna_path()}", browse=True)
        self.ent_deliverable = self._entry_row(
            body, "Préparation livrables",
            hint="", browse=True)
        self.ent_workspace = self._entry_row(
            body, "Répertoire de travail",
            hint=f"Vide = {default_workspace_path()}", browse=True)
        self.ent_pptx_template = self._entry_row(
            body, "Template PPT vierge",
            hint="Vide = génération des PPT désactivée",
            browse=True, browse_file=True)

        # L'emplacement par défaut des livrables dérive du dossier AUDIT_SNA :
        # l'aide doit suivre la saisie, sinon elle indique un chemin faux.
        self.ent_audit.bind("<KeyRelease>",
                            lambda _event: self._refresh_deliverable_hint())

        tk.Frame(body, bg=C_BORDER, height=1).pack(fill="x", pady=(4, 12))

        self.ent_lot, self.ent_zoom = self._entry_pair(
            body,
            ("Nom du lot", "Exemple : Lot7"),
            ("Couche de centrage", "Vide = détection automatique"),
        )

        # Codes INSEE : intitule au-dessus pour laisser toute la largeur a la
        # zone de saisie, boutons regroupes en dessous.
        bloc = tk.Frame(body, bg=C_CARD)
        bloc.pack(fill="x", pady=(0, 10))

        tk.Label(bloc, text="Codes INSEE", font=self.F_LABEL, bg=C_CARD,
                 fg=C_TEXT2).pack(anchor="w")
        tk.Label(bloc, text="Un code par ligne", font=(F_BODY, 8), bg=C_CARD,
                 fg=C_MUTED).pack(anchor="w", pady=(0, 4))

        zone = tk.Frame(bloc, bg=C_CARD)
        zone.pack(fill="x")

        self.txt_insee = tk.Text(
            zone, height=6, font=(F_MONO, 10), bg=C_PANEL2, fg=C_TEXT,
            insertbackground=C_ACCENT, relief="flat", highlightthickness=1,
            highlightbackground=C_BORDER2, highlightcolor=C_ACCENT,
            wrap="none", padx=8, pady=6,
        )
        scroll = ttk.Scrollbar(zone, orient="vertical", command=self.txt_insee.yview)
        self.txt_insee.configure(yscrollcommand=scroll.set)
        self.txt_insee.pack(side="left", fill="x", expand=True)
        scroll.pack(side="left", fill="y")

        barre = tk.Frame(bloc, bg=C_CARD)
        barre.pack(fill="x", pady=(6, 0))

        tk.Button(barre, text="🔍 Détecter", command=self._detect_communes,
                  bg=C_PANEL2, fg=C_ACCENT, font=(F_BODY, 9, "bold"),
                  relief="flat", cursor="hand2", padx=16).pack(
            side="left", ipady=4)
        tk.Button(barre, text="🗑 Vider", command=self._clear_insee,
                  bg=C_PANEL2, fg=C_TEXT2, font=(F_BODY, 9), relief="flat",
                  cursor="hand2", padx=16).pack(side="left", padx=(8, 0), ipady=4)

        self.lbl_insee_count = tk.Label(barre, text="0 commune", font=(F_BODY, 9),
                                        bg=C_CARD, fg=C_MUTED)
        self.lbl_insee_count.pack(side="right")
        self.txt_insee.bind("<KeyRelease>", lambda _event: self._update_insee_count())

        # Options : intitulé et cases sur une même ligne.
        tk.Frame(body, bg=C_BORDER, height=1).pack(fill="x", pady=(4, 10))

        options_row = tk.Frame(body, bg=C_CARD)
        options_row.pack(fill="x")

        tk.Label(options_row, text="Options", font=self.F_LABEL, bg=C_CARD,
                 fg=C_TEXT2, width=self.PAIR_LABEL_WIDTH, anchor="w").pack(
            side="left", padx=(0, 8))

        options = tk.Frame(options_row, bg=C_CARD)
        options.pack(side="left", fill="x", expand=True)

        self.var_sort_excel = tk.BooleanVar(value=True)
        self.var_clean = tk.BooleanVar(value=True)
        self.var_strict = tk.BooleanVar(value=False)
        self.var_stop = tk.BooleanVar(value=False)
        # Vide par défaut : les PPT ne sont générés que si l'utilisateur
        # coche explicitement la case.
        self.var_generate_ppts = tk.BooleanVar(value=False)

        for variable, label in (
            (self.var_sort_excel, "Trier l'audit"),
            (self.var_clean, "Purger le répertoire"),
            (self.var_strict, "Mode strict"),
            (self.var_stop, "Arrêter au 1er échec"),
            (self.var_generate_ppts, "Générer les PPT"),
        ):
            tk.Checkbutton(
                options, text=label, variable=variable, bg=C_CARD, fg=C_TEXT2,
                font=(F_BODY, 10), selectcolor=C_PANEL2, activebackground=C_CARD,
                activeforeground=C_TEXT, relief="flat", cursor="hand2",
                highlightthickness=0, anchor="w",
            ).pack(side="left", padx=(0, 22))

    def _clear_insee(self) -> None:
        self.txt_insee.delete("1.0", "end")
        self._update_insee_count()

    def _update_insee_count(self) -> None:
        """Met a jour le compteur sous la zone de saisie."""
        nombre = len(parse_insee_codes(self.txt_insee.get("1.0", "end")))
        self.lbl_insee_count.configure(
            text="0 commune" if nombre == 0 else
            f"{nombre} commune{'s' if nombre > 1 else ''}")

    def _build_progress_card(self, parent) -> None:
        body = self._card(parent, "Traitement", "▶️", C_GREEN,
                          "Progression du lot en cours")

        self.progress = ttk.Progressbar(body, style="modop.Horizontal.TProgressbar",
                                        mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 8))

        line = tk.Frame(body, bg=C_CARD)
        line.pack(fill="x")

        self.lbl_progress = tk.Label(line, text="En attente", font=(F_BODY, 10),
                                     bg=C_CARD, fg=C_TEXT2)
        self.lbl_progress.pack(side="left")

        self.lbl_elapsed = tk.Label(line, text="", font=(F_MONO, 9), bg=C_CARD,
                                    fg=C_MUTED)
        self.lbl_elapsed.pack(side="right")

        # Pastilles d'etape : allumees par le prefixe des lignes de journal.
        phases = tk.Frame(body, bg=C_CARD)
        phases.pack(fill="x", pady=(12, 0))
        for key, label, color in PHASES:
            block = tk.Frame(phases, bg=C_CARD)
            block.pack(side="left", padx=(0, 16))
            dot = tk.Label(block, text="○", font=(F_BODY, 11), bg=C_CARD, fg=C_MUTED)
            dot.pack(side="left", padx=(0, 4))
            tk.Label(block, text=label, font=(F_BODY, 9), bg=C_CARD,
                     fg=C_MUTED).pack(side="left")
            self._phase_dots[key] = dot

        actions = tk.Frame(body, bg=C_CARD)
        actions.pack(fill="x", pady=(14, 0))

        self.btn_start = tk.Button(actions, text="▶  Lancer le traitement",
                                   command=self._start, bg=C_ACCENT, fg="white",
                                   font=(F_BODY, 11, "bold"), relief="flat",
                                   cursor="hand2", padx=24, pady=8)
        self.btn_start.pack(side="left")

        self.btn_open = tk.Button(actions, text="📂  Ouvrir le dossier livrable",
                                  command=self._open_output, bg=C_PANEL2,
                                  fg=C_TEXT2, font=(F_BODY, 10), relief="flat",
                                  cursor="hand2", padx=18, pady=8, state="disabled")
        self.btn_open.pack(side="left", padx=10)

    def _build_results_card(self, parent) -> None:
        body = self._card(parent, "Résultats", "📦", C_CYAN,
                          "Une ligne par commune traitée")

        columns = ("commune", "statut", "couche", "ppt", "archive")
        self.tree = ttk.Treeview(body, columns=columns, show="headings", height=8)
        for column, label, width in (
            ("commune", "Commune", 100),
            ("statut", "Statut", 110),
            ("couche", "Couche de centrage", 200),
            ("ppt", "PPT", 130),
            ("archive", "Archive produite", 420),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, anchor="w")

        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")

        self.tree.tag_configure("ok", foreground=C_GREEN)
        self.tree.tag_configure("warn", foreground=C_AMBER)
        self.tree.tag_configure("ko", foreground=C_RED)

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def _restore_config(self) -> None:
        """Reapplique les preferences de la session precedente."""
        self.ent_audit.insert(0, self.config_data["audit_sna_path"])
        self.ent_deliverable.insert(0, self.config_data["deliverable_path"])
        self.ent_workspace.insert(0, self.config_data["workspace_path"])
        self.ent_pptx_template.insert(0, self.config_data["pptx_template_path"])
        self._refresh_deliverable_hint()
        self.ent_lot.insert(0, self.config_data["lot_name"])
        self.ent_zoom.insert(0, self.config_data["zoom_layer"])

        # Les codes sont stockes separes par des virgules et affiches un par
        # ligne : la saisie reste lisible quel que soit leur nombre.
        codes = parse_insee_codes(self.config_data["insee_codes"])
        self.txt_insee.insert("1.0", "\n".join(codes))
        self._update_insee_count()
        self.var_sort_excel.set(self.config_data["sort_excel"])
        self.var_clean.set(self.config_data["clean_workspace"])
        self.var_strict.set(self.config_data["strict"])
        self.var_stop.set(self.config_data["stop_on_error"])
        self.var_generate_ppts.set(self.config_data["generate_ppts"])

    def _collect_config(self) -> dict:
        """Etat courant de la saisie."""
        return {
            "audit_sna_path": self.ent_audit.get().strip(),
            "deliverable_path": self.ent_deliverable.get().strip(),
            "workspace_path": self.ent_workspace.get().strip(),
            "pptx_template_path": self.ent_pptx_template.get().strip(),
            "lot_name": self.ent_lot.get().strip(),
            "insee_codes": ", ".join(parse_insee_codes(self.txt_insee.get("1.0", "end"))),
            "zoom_layer": self.ent_zoom.get().strip(),
            "sort_excel": self.var_sort_excel.get(),
            "clean_workspace": self.var_clean.get(),
            "strict": self.var_strict.get(),
            "stop_on_error": self.var_stop.get(),
            "generate_ppts": self.var_generate_ppts.get(),
        }

    def _on_close(self) -> None:
        """Enregistre les preferences avant de quitter."""
        if self._running and not messagebox.askokcancel(
            "Traitement en cours",
            "Un traitement est en cours. Quitter maintenant l'interrompra.\n\n"
            "Fermer l'application ?",
        ):
            return

        save_config(self._collect_config())
        self.destroy()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _detect_communes(self) -> None:
        """Remplit le champ INSEE avec les communes presentes dans le lot."""
        lot = self.ent_lot.get().strip()
        if not lot:
            messagebox.showwarning("Lot manquant", "Renseignez d'abord le nom du lot.")
            return

        # Les chemins saisis doivent etre actifs avant de scruter le disque.
        apply_paths(self._collect_config())
        codes = list_communes(lot)
        if not codes:
            messagebox.showinfo(
                "Aucune commune",
                f"Aucune commune trouvée dans le répertoire QGIS du lot « {lot} ».",
            )
            return

        self.txt_insee.delete("1.0", "end")
        self.txt_insee.insert("1.0", "\n".join(codes))
        self._update_insee_count()
        self._append_log(f"[lot] {len(codes)} commune(s) détectée(s) dans {lot}")

    def _start(self) -> None:
        """Valide la saisie puis lance le traitement dans un thread."""
        if self._running:
            return

        lot = self.ent_lot.get().strip()
        if not lot:
            messagebox.showwarning("Lot manquant", "Renseignez le nom du lot.")
            return

        codes = parse_insee_codes(self.txt_insee.get("1.0", "end"))
        if not codes:
            messagebox.showwarning(
                "Communes manquantes",
                "Renseignez au moins un code INSEE, ou utilisez « Détecter ».",
            )
            return

        config = self._collect_config()
        # Les chemins saisis prennent effet immediatement, puis sont memorises.
        apply_paths(config)
        save_config(config)

        for item in self.tree.get_children():
            self.tree.delete(item)
        self._reset_phases()

        self._running = True
        self._started_at = time.time()
        self.btn_start.configure(state="disabled", text="⏳  Traitement en cours…")
        self.btn_open.configure(state="disabled")
        self.lbl_state.configure(text="●  Traitement", fg=C_AMBER)
        self.progress.configure(value=0)
        self.lbl_progress.configure(text=f"Démarrage — {len(codes)} commune(s)")
        self._append_log(f"===== lancement du lot {lot} — {len(codes)} commune(s) =====")

        options = {
            "zoom_layer": self.ent_zoom.get().strip() or None,
            "sort_excel": self.var_sort_excel.get(),
            "strict": self.var_strict.get(),
            "stop_on_error": self.var_stop.get(),
            "pptx_template_path": self.ent_pptx_template.get().strip() or None,
            "generate_ppts": self.var_generate_ppts.get(),
        }
        self._last_message_at = time.time()
        self._watchdog_fired = False
        self._worker_thread = threading.Thread(
            target=self._worker, args=(lot, codes, options), daemon=True)
        self._worker_thread.start()
        self.after(POLL_INTERVAL_MS, self._poll)

    def _worker(self, lot: str, codes: list[str], options: dict) -> None:
        """Traitement, execute hors du thread principal.

        Ne touche a aucun widget : tout passe par la file.
        """
        writer = _QueueWriter(self._queue)
        termine = False

        try:
            # Les services journalisent avec print : on capte cette sortie
            # plutot que de les modifier.
            with contextlib.redirect_stdout(writer):
                bilan = prepare_lot_deliverables(
                    lot,
                    codes,
                    on_start=lambda position, total, insee: self._queue.put(
                        ("progress", (position, total, insee))),
                    on_result=lambda insee, result, error: self._queue.put(
                        ("result", (insee, result, error))),
                    verbose=True,
                    **options,
                )
            writer.flush()
            self._queue.put(("done", bilan))
            termine = True

        except BaseException as error:
            # BaseException et non Exception : une sortie inattendue laisserait
            # sinon l'interface bloquee sur « traitement en cours ».
            writer.flush()
            self._queue.put(("log", "".join(traceback.format_exc()).rstrip()))
            self._queue.put(("failed", f"{type(error).__name__} : {error}"))
            termine = True

        finally:
            if not termine:
                self._queue.put(("failed", "Le traitement s'est interrompu sans message."))

    def _poll(self) -> None:
        """Vide la file et met a jour l'affichage. Seul a toucher aux widgets.

        Toute erreur d'affichage est journalisee sans interrompre la boucle :
        une exception qui remonte ici empecherait le `after` suivant d'etre
        planifie, et l'interface resterait figee sur « traitement en cours »
        sans que rien ne le signale.
        """
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                self._last_message_at = time.time()

                try:
                    if kind == "log":
                        self._append_log(payload)
                        self._light_phase(payload)
                    elif kind == "progress":
                        self._update_progress(*payload)
                    elif kind == "result":
                        self._add_result(*payload)
                    elif kind == "done":
                        self._finish(payload)
                    elif kind == "failed":
                        self._finish(None, payload)

                except Exception as error:
                    self._append_log(
                        f"[ko] affichage « {kind} » : {type(error).__name__} : {error}")

        except queue.Empty:
            pass

        if self._running:
            self._update_elapsed()
            self._check_watchdog()
            self.after(POLL_INTERVAL_MS, self._poll)

    def _check_watchdog(self) -> None:
        """Signale un traitement silencieux depuis trop longtemps.

        Deux situations donnent la meme apparence de blocage : le thread de
        travail s'est arrete sans rien dire, ou il est coince dans un appel
        systeme. Le diagnostic distingue les deux.
        """
        silence = time.time() - self._last_message_at
        if silence < WATCHDOG_SECONDS or self._watchdog_fired:
            return

        self._watchdog_fired = True
        self._append_log(f"[ko] aucun message depuis {int(silence)} s.")

        thread = self._worker_thread
        if thread is not None and not thread.is_alive():
            self._append_log("[ko] le thread de traitement s'est arrêté sans message.")
            self._finish(None, "Le traitement s'est interrompu de façon inattendue.")
            return

        self._append_log("[ko] le traitement est bloqué. Pile d'exécution :")
        for ligne in self._worker_stack():
            self._append_log(f"    {ligne}")
        self._append_log(
            "[ko] la dernière ligne indique l'appel qui ne rend pas la main.")

    def _worker_stack(self) -> list[str]:
        """Pile d'execution courante du thread de travail.

        Repond a la question « ou est-ce que ca bloque ? » sans avoir a
        reproduire le probleme sous debogueur.
        """
        thread = self._worker_thread
        if thread is None or thread.ident is None:
            return ["thread de traitement introuvable"]

        frame = sys._current_frames().get(thread.ident)
        if frame is None:
            return ["pile indisponible"]

        lignes = []
        for fichier, numero, fonction, code in traceback.extract_stack(frame):
            lignes.append(f"{os.path.basename(fichier)}:{numero} {fonction}() "
                          f"{(code or '').strip()}")

        # Les dernieres images sont les plus parlantes : c'est la que ca coince.
        return lignes[-6:]

    # ------------------------------------------------------------------
    # Mise a jour de l'affichage
    # ------------------------------------------------------------------

    def _append_log(self, line: str) -> None:
        """Ajoute une ligne au journal, coloree selon son prefixe."""
        color = log_color(line)
        tag = f"c{color.lstrip('#')}"

        self.txt_log.configure(state="normal")
        self.txt_log.tag_configure(tag, foreground=color)
        self.txt_log.insert("end", f"{datetime.now():%H:%M:%S}  {line}\n", tag)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _light_phase(self, line: str) -> None:
        """Allume la pastille correspondant au prefixe d'une ligne."""
        stripped = line.lstrip()
        for key, _label, color in PHASES:
            if stripped.startswith(f"[{key}]"):
                self._phase_dots[key].configure(text="●", fg=color)

    def _reset_phases(self) -> None:
        for dot in self._phase_dots.values():
            dot.configure(text="○", fg=C_MUTED)

    def _update_progress(self, position: int, total: int, insee: str) -> None:
        self.progress.configure(value=(position - 1) / total * 100)
        self.lbl_progress.configure(text=f"Commune {position}/{total} — {insee}")
        self._reset_phases()

    def _add_result(self, insee: str, result, error: str) -> None:
        """Ajoute une ligne au tableau des resultats."""
        if result is None:
            values = (insee, "❌ Échec", "", "", error)
            tag = "ko"
        else:
            ppt_texte = f"{result.ppt_liens} lien(s)"
            if result.ppt_generes:
                ppt_texte += f" · {result.ppt_generes} PPT"

            if result.warnings:
                values = (insee, f"⚠ {len(result.warnings)} alerte(s)",
                          result.zoom_layer, ppt_texte, result.archive_file)
                tag = "warn"
            else:
                values = (insee, "✅ OK", result.zoom_layer, ppt_texte, result.archive_file)
                tag = "ok"

        self.tree.insert("", "end", values=values, tags=(tag,))
        self.tree.see(self.tree.get_children()[-1])

    def _update_elapsed(self) -> None:
        if self._started_at is None:
            return
        elapsed = int(time.time() - self._started_at)
        self.lbl_elapsed.configure(text=f"{elapsed // 60:02d}:{elapsed % 60:02d}")

    def _finish(self, bilan, error: str = "") -> None:
        """Retablit l'interface, signale la fin et resume le traitement."""
        self._running = False
        self.btn_start.configure(state="normal", text="▶  Lancer le traitement")
        self.progress.configure(value=100 if bilan is not None else 0)
        duree = self._elapsed_text()

        # Signal sonore : le traitement d'un lot est long, l'utilisateur a pu
        # passer a autre chose.
        self._alert()

        if error:
            self.lbl_state.configure(text="●  Échec", fg=C_RED)
            self.lbl_progress.configure(text=error)
            self._append_log(f"[ko] {error}")
            messagebox.showerror(
                "Traitement interrompu",
                f"Le traitement s'est arrêté après {duree}.\n\n{error}",
            )
            return

        total = len(bilan.processed)
        reussis = len(bilan.succeeded)
        echecs = bilan.failed
        alertes = sum(len(messages) for messages in bilan.warnings.values())

        if bilan.ok:
            self.lbl_state.configure(text="●  Terminé", fg=C_GREEN)
        else:
            self.lbl_state.configure(text="●  Terminé avec erreurs", fg=C_AMBER)

        self.lbl_progress.configure(text=f"{reussis}/{total} livrable(s) produit(s)")
        self.btn_open.configure(state="normal" if reussis else "disabled")
        self._last_archive = next(
            (r.archive_file for r in bilan.results.values() if r.ok), ""
        )

        self._show_summary(bilan, duree, total, reussis, echecs, alertes)

    def _alert(self) -> None:
        """Signale la fin du traitement : son, puis mise en avant de la fenetre."""
        try:
            self.bell()
        except tk.TclError:
            # Poste sans peripherique audio : sans consequence.
            pass

        # Ramene la fenetre au premier plan sans la verrouiller au-dessus des
        # autres : le topmost est retire aussitot.
        try:
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except tk.TclError:
            pass

    def _show_summary(self, bilan, duree: str, total: int, reussis: int,
                      echecs: list, alertes: int) -> None:
        """Affiche la synthese de fin de traitement."""
        lignes = [
            f"Lot {bilan.lot_name} — terminé en {duree}",
            "",
            f"Communes traitées   : {total}",
            f"Livrables produits  : {reussis}",
        ]

        if echecs:
            lignes.append(f"Échecs              : {len(echecs)}")
        if alertes:
            lignes.append(f"Avertissements      : {alertes}")

        if echecs:
            lignes += ["", "Communes en échec :"]
            # Au-dela de cinq, la liste devient illisible dans une boite de
            # dialogue : le detail reste dans le journal.
            for insee in echecs[:5]:
                lignes.append(f"  • {insee} — {bilan.errors.get(insee, 'archive absente')}")
            if len(echecs) > 5:
                lignes.append(f"  … et {len(echecs) - 5} autre(s), voir le journal")

        texte = "\n".join(lignes)

        if echecs:
            messagebox.showwarning("Traitement terminé avec erreurs", texte)
        elif alertes:
            messagebox.showinfo("Traitement terminé", texte
                                + "\n\nConsultez le journal pour le détail des alertes.")
        else:
            messagebox.showinfo("Traitement terminé", texte)

    def _elapsed_text(self) -> str:
        """Duree ecoulee, en minutes et secondes."""
        if self._started_at is None:
            return "0 s"

        total = int(time.time() - self._started_at)
        minutes, secondes = divmod(total, 60)
        return f"{minutes} min {secondes:02d} s" if minutes else f"{secondes} s"

    def _open_output(self) -> None:
        """Ouvre le dossier du dernier livrable dans l'explorateur."""
        archive = getattr(self, "_last_archive", "")
        folder = os.path.dirname(archive)
        if not folder or not os.path.isdir(folder):
            messagebox.showinfo("Dossier introuvable", "Aucun livrable à afficher.")
            return

        if sys.platform.startswith("win"):
            os.startfile(folder)          # noqa: S606 - API Windows standard
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    # ------------------------------------------------------------------
    # Page journal
    # ------------------------------------------------------------------

    def _toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.page_main.pack_forget()
            self.page_log.pack(fill="both", expand=True)
        else:
            self.page_log.pack_forget()
            self.page_main.pack(fill="both", expand=True)

    def _clear_log(self) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _export_log(self) -> None:
        """Enregistre le journal a cote du dossier de travail."""
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"journal_modop_{datetime.now():%Y%m%d_%H%M%S}.txt",
            filetypes=[("Fichier texte", "*.txt")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.txt_log.get("1.0", "end"))
            messagebox.showinfo("Journal exporté", path)
        except OSError as error:
            messagebox.showerror("Export impossible", str(error))