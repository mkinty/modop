"""
Création des répertoires par code INSEE — Projet SNA
Crée l'arborescence (Dep<xx>/<insee>/Carte, Analyse) définie dans path_manager,
sous la racine du répertoire dossier à auditer (AUDIT_SNA_DIR) choisi par
l'utilisateur.
py creer_repertoires.py
"""
import os, sys, re, json, subprocess, threading, warnings, importlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

warnings.filterwarnings('ignore')

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Fichier local (à côté de ce script) qui mémorise où se trouve le package
#    contenant path_manager.py — indépendant de tout ce qui vient de ce module,
#    puisqu'on en a besoin AVANT de pouvoir l'importer. ──────────────────────
_LOCAL_SETTINGS_FILE = os.path.join(_THIS_DIR, "creer_repertoires_settings.json")


def _load_local_settings():
    try:
        with open(_LOCAL_SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_local_settings(data):
    try:
        with open(_LOCAL_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _import_path_manager_from(package_dir):
    """Importe path_manager comme membre du package situé dans package_dir.

    path_manager.py fait un `from .constants import ...` : il doit donc être
    importé comme sous-module d'un package (dossier avec __init__.py), pas
    comme script isolé. On ajoute le PARENT de ce dossier à sys.path et on
    importe "<nom_du_dossier>.path_manager".
    """
    package_dir = os.path.abspath(package_dir)
    parent_dir  = os.path.dirname(package_dir)
    package_name = os.path.basename(package_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    module_name = f"{package_name}.path_manager"
    if module_name in sys.modules:
        del sys.modules[module_name]  # pour repartir propre si l'emplacement a changé
    return importlib.import_module(module_name)


def _locate_path_manager(demander_si_absent=False):
    """Tente de localiser + importer path_manager.

    Essaie d'abord le dossier enregistré, puis le dossier du script lui-même.
    Si `demander_si_absent`, ouvre une boîte de dialogue pour choisir le
    dossier contenant path_manager.py.

    Renvoie (module_ou_None, dossier_ou_None, message_erreur_ou_None).
    """
    local = _load_local_settings()
    candidats = []
    if local.get("package_dir"):
        candidats.append(local["package_dir"])
    candidats.append(_THIS_DIR)

    for dossier in candidats:
        if dossier and os.path.isfile(os.path.join(dossier, "path_manager.py")):
            try:
                module = _import_path_manager_from(dossier)
                local["package_dir"] = dossier
                _save_local_settings(local)
                return module, dossier, None
            except Exception as e:
                dernier_msg = str(e)

    if demander_si_absent:
        messagebox.showinfo(
            "Localiser path_manager.py",
            "path_manager.py est introuvable automatiquement.\n\n"
            "Sélectionnez le DOSSIER qui contient le fichier path_manager.py "
            "(ce dossier doit aussi contenir un fichier __init__.py, car "
            "path_manager fait partie d'un package)."
        )
        dossier = filedialog.askdirectory(title="Dossier contenant path_manager.py")
        if dossier and os.path.isfile(os.path.join(dossier, "path_manager.py")):
            try:
                module = _import_path_manager_from(dossier)
                local["package_dir"] = dossier
                _save_local_settings(local)
                return module, dossier, None
            except Exception as e:
                return None, None, str(e)
        elif dossier:
            return None, None, f"Aucun fichier path_manager.py trouvé dans « {dossier} »."
        else:
            return None, None, "Sélection annulée."

    return None, None, "path_manager.py introuvable (voir « 📁 Localiser path_manager… »)."


def get_codes(text):
    """Extrait les codes INSEE (5 chiffres, ou 2A/2B pour la Corse) d'un texte."""
    return list(dict.fromkeys(re.findall(r'\b(?:2[ABab]\d{3}|\d{5})\b', text.upper())))


def creer_repertoires(path_manager, communes, log_fn, link_fn, progress_fn):
    """Crée l'arborescence (Dep/INSEE/Carte + Analyse) pour chaque commune,
    sous la racine AUDIT_SNA actuellement configurée dans path_manager.

    `link_fn(path)` est appelé pour chaque dossier créé afin que l'appelant
    puisse en afficher un accès rapide (raccourci cliquable) dans le journal.
    """
    try:
        racine = path_manager.verifier_racine_audit_sna()
        log_fn(f"📁 Répertoire dossier à auditer :", "#90caf9")
        link_fn(racine)
    except OSError as e:
        log_fn(f"❌ {e}", "#ef5350")
        return 0

    log_fn(f"{'─'*45}", "#78909c")
    n_ok = 0
    progress_fn(0, len(communes), "Création des dossiers...")

    for i, commune in enumerate(communes, 1):
        progress_fn(i, len(communes), f"Création {commune}...")
        try:
            carte   = path_manager._insee_carte_path(commune)
            analyse = path_manager._insee_analyse_path(commune)
            log_fn(f"  ✅ {commune} — Carte + Analyse créés :", "#69f0ae")
            link_fn(carte)
            link_fn(analyse)
            n_ok += 1
        except OSError as e:
            log_fn(f"  ❌ {commune} — Erreur : {e}", "#ef5350")

    log_fn(f"\n{'─'*45}", "#78909c")
    if n_ok:
        log_fn(f"🎉 {n_ok}/{len(communes)} dossier(s) créé(s)", "#69f0ae")
    else:
        log_fn("❌ Aucun dossier créé", "#ef5350")
    return n_ok


# ── Persistance du chemin AUDIT_SNA paramétré ──
_SETTINGS_KEY = "repertoires_paths"


def _load_path_settings(path_manager):
    try:
        with open(path_manager.CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get(_SETTINGS_KEY, {})
    except Exception:
        return {}


def _save_path_settings(path_manager, audit_sna):
    fichier = path_manager.CONFIG_FILE
    try:
        with open(fichier, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data[_SETTINGS_KEY] = {"audit_sna": audit_sna}
    os.makedirs(os.path.dirname(fichier), exist_ok=True)
    with open(fichier, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Interface ─────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Création des répertoires — Projet SNA")
        self.geometry("680x700")
        self.configure(bg="#0f1117")
        self.path_manager = None
        self._link_counter = 0
        self._build_ui()
        self._init_path_manager(demander_si_absent=False)

    # -- Chargement de path_manager --------------------------------------
    def _init_path_manager(self, demander_si_absent):
        module, dossier, erreur = _locate_path_manager(demander_si_absent)
        self.path_manager = module
        if module is not None:
            self.lbl_pm_status.config(text=f"✅ path_manager chargé depuis : {dossier}",
                                       fg="#69f0ae")
            self._appliquer_config_sauvegardee()
        else:
            self.lbl_pm_status.config(text=f"⚠️ {erreur}", fg="#ffb74d")
        self._update_placeholder()

    def _localiser_path_manager(self):
        self._init_path_manager(demander_si_absent=True)

    # -- Paramètre du répertoire à auditer --------------------------------
    def _appliquer_config_sauvegardee(self):
        saved = _load_path_settings(self.path_manager)
        self.ent_audit.delete(0, tk.END)
        self.ent_audit.insert(0, saved.get("audit_sna", ""))
        if saved:
            self.path_manager.set_paths(audit_sna=saved.get("audit_sna") or None)

    def _update_placeholder(self):
        if self.path_manager is None:
            self.lbl_audit_def.config(text="")
            return
        self.lbl_audit_def.config(text=f"Par défaut : {self.path_manager.default_audit_sna_path()}")

    def _parcourir(self, entry):
        dossier = filedialog.askdirectory()
        if dossier:
            entry.delete(0, tk.END)
            entry.insert(0, dossier)

    def _enregistrer_parametres(self):
        if self.path_manager is None:
            messagebox.showerror("Erreur", "path_manager n'est pas chargé. "
                                            "Utilisez d'abord « 📁 Localiser path_manager… ».")
            return
        audit_sna = self.ent_audit.get().strip()
        self.path_manager.set_paths(audit_sna=audit_sna or None)
        try:
            _save_path_settings(self.path_manager, audit_sna)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'enregistrer les paramètres :\n{e}")
            return
        self._update_placeholder()
        messagebox.showinfo("Paramètres", "Paramètres enregistrés.")

    def _reinitialiser_parametres(self):
        self.ent_audit.delete(0, tk.END)
        if self.path_manager is not None:
            self.path_manager.reset_paths()
            try:
                _save_path_settings(self.path_manager, "")
            except Exception:
                pass
        self._update_placeholder()

    # -- UI -------------------------------------------------------------
    def _build_ui(self):
        hdr = tk.Frame(self, bg="#161b2e", pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  📂  Création des répertoires par commune",
                 font=("Segoe UI", 14, "bold"), bg="#161b2e", fg="#e8eaf6").pack(side="left")

        body = tk.Frame(self, bg="#0f1117")
        body.pack(fill="both", expand=True, padx=20, pady=15)

        tk.Label(body,
                 text="Colle les codes INSEE des communes : crée pour chacune\n"
                      "l'arborescence Dep<xx>/<insee>/Carte et /Analyse.",
                 bg="#0f1117", fg="#78909c", font=("Segoe UI", 10),
                 justify="left").pack(anchor="w", pady=(0, 10))

        # ── Statut path_manager ──
        pm_row = tk.Frame(body, bg="#0f1117")
        pm_row.pack(fill="x", pady=(0, 10))
        self.lbl_pm_status = tk.Label(pm_row, text="", bg="#0f1117", font=("Segoe UI", 9),
                                       anchor="w", justify="left", wraplength=480)
        self.lbl_pm_status.pack(side="left", fill="x", expand=True)
        tk.Button(pm_row, text="📁 Localiser path_manager…", command=self._localiser_path_manager,
                   bg="#37474f", fg="white", font=("Segoe UI", 8),
                   relief="flat", cursor="hand2").pack(side="right")

        # ── Paramètre du répertoire à auditer ──
        params = tk.LabelFrame(body, text=" ⚙ Paramètres ",
                                bg="#0f1117", fg="#90caf9", bd=1,
                                labelanchor="nw", font=("Segoe UI", 9, "bold"))
        params.pack(fill="x", pady=(0, 14))

        self.ent_audit     = self._champ_chemin(params, "Répertoire dossier à auditer :")
        self.lbl_audit_def = self._label_defaut(params)

        btn_row = tk.Frame(params, bg="#0f1117")
        btn_row.pack(fill="x", padx=10, pady=(6, 10))
        tk.Button(btn_row, text="💾 Enregistrer les paramètres", command=self._enregistrer_parametres,
                   bg="#1565c0", fg="white", font=("Segoe UI", 9, "bold"),
                   relief="flat", cursor="hand2").pack(side="left")
        tk.Button(btn_row, text="↺ Réinitialiser", command=self._reinitialiser_parametres,
                   bg="#37474f", fg="white", font=("Segoe UI", 9),
                   relief="flat", cursor="hand2").pack(side="left", padx=(8, 0))

        tk.Label(body, text="Codes communes :",
                 bg="#0f1117", fg="#78909c", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 4))
        self.txt = tk.Text(body, height=8, bg="#1a1f35", fg="white",
                            font=("Segoe UI", 10), relief="flat",
                            insertbackground="white", bd=6)
        self.txt.pack(fill="x", pady=(0, 10))
        self.txt.focus()

        self.btn = tk.Button(body, text="📂  Créer les répertoires",
                              command=self._run,
                              bg="#1565c0", fg="white", font=("Segoe UI", 12, "bold"),
                              relief="flat", cursor="hand2", pady=10)
        self.btn.pack(fill="x", pady=(0, 8))

        s = ttk.Style(); s.theme_use("clam")
        s.configure("exp.Horizontal.TProgressbar", troughcolor="#1a1f35",
                    background="#1565c0", darkcolor="#1565c0",
                    lightcolor="#1565c0", bordercolor="#1a1f35")
        self.progress = ttk.Progressbar(body, style="exp.Horizontal.TProgressbar",
                                         mode="determinate")
        self.progress.pack(fill="x", pady=(0, 2))
        self.lbl_prog = tk.Label(body, text="", bg="#0f1117", fg="#78909c", font=("Segoe UI", 9))
        self.lbl_prog.pack(anchor="w", pady=(0, 6))

        tk.Label(body, text="Journal :", bg="#0f1117", fg="#78909c",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.txt_log = tk.Text(body, height=10, bg="#0a0d14", fg="#69f0ae",
                                font=("Consolas", 9), relief="flat", state="disabled")
        self.txt_log.pack(fill="both", expand=True, pady=(2, 0))

    def _champ_chemin(self, parent, label):
        tk.Label(parent, text=label, bg="#0f1117", fg="#78909c",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(8, 2))
        row = tk.Frame(parent, bg="#0f1117")
        row.pack(fill="x", padx=10)
        entry = tk.Entry(row, font=("Segoe UI", 9), bg="#1a1f35", fg="white",
                          insertbackground="white", relief="flat", bd=6)
        entry.pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Parcourir…", command=lambda: self._parcourir(entry),
                   bg="#37474f", fg="white", font=("Segoe UI", 8),
                   relief="flat", cursor="hand2").pack(side="left", padx=(6, 0))
        return entry

    def _label_defaut(self, parent):
        lbl = tk.Label(parent, text="", bg="#0f1117", fg="#546e7a", font=("Segoe UI", 8))
        lbl.pack(anchor="w", padx=10)
        return lbl

    def _log(self, msg, color="#69f0ae"):
        self.txt_log.config(state="normal")
        tag = f"c{color.replace('#', '')}"
        self.txt_log.tag_config(tag, foreground=color)
        self.txt_log.insert(tk.END, msg + "\n", tag)
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def _log_link(self, path):
        """Insère le chemin d'un dossier créé comme lien cliquable dans le
        journal — un clic (ou double-clic) ouvre directement le dossier."""
        self.txt_log.config(state="normal")
        tag = f"link{self._link_counter}"
        self._link_counter += 1

        self.txt_log.insert(tk.END, "      📂 ")
        start = self.txt_log.index(tk.END)
        self.txt_log.insert(tk.END, path)
        end = self.txt_log.index(tk.END)
        self.txt_log.insert(tk.END, "\n")

        self.txt_log.tag_add(tag, start, end)
        self.txt_log.tag_config(tag, foreground="#64b5f6", underline=True)
        self.txt_log.tag_bind(tag, "<Enter>", lambda e: self.txt_log.config(cursor="hand2"))
        self.txt_log.tag_bind(tag, "<Leave>", lambda e: self.txt_log.config(cursor=""))
        self.txt_log.tag_bind(tag, "<Button-1>", lambda e, p=path: self._ouvrir_dossier(p))

        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def _ouvrir_dossier(self, path):
        """Ouvre le dossier dans l'explorateur de fichiers du système."""
        if not os.path.isdir(path):
            messagebox.showwarning("Dossier introuvable", f"Le dossier n'existe pas (ou plus) :\n{path}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le dossier :\n{e}")

    def _prog(self, done, total, label=""):
        self.progress["maximum"] = max(total, 1)
        self.progress["value"] = done
        self.lbl_prog.config(text=f"{done}/{total} — {label}")
        self.update_idletasks()

    def _run(self):
        if self.path_manager is None:
            messagebox.showerror("Erreur", "path_manager n'est pas chargé. "
                                            "Utilisez « 📁 Localiser path_manager… » en haut de la fenêtre.")
            return

        codes = get_codes(self.txt.get("1.0", tk.END))
        if not codes:
            messagebox.showwarning("Erreur", "Aucun code commune valide détecté.")
            return

        # Applique le chemin actuellement saisi dans le champ, même si
        # « Enregistrer les paramètres » n'a pas été cliqué explicitement.
        audit_sna = self.ent_audit.get().strip()
        self.path_manager.set_paths(audit_sna=audit_sna or None)

        if not messagebox.askyesno("Confirmation",
                f"Créer les répertoires pour {len(codes)} commune(s) ?"):
            return

        self.txt_log.config(state="normal"); self.txt_log.delete("1.0", tk.END)
        self.txt_log.config(state="disabled")
        self.btn.config(state="disabled")

        def do():
            self._log(f"🚀 Création des répertoires pour {len(codes)} commune(s)...", "#90caf9")
            n = creer_repertoires(self.path_manager, codes, self._log, self._log_link, self._prog)
            self.btn.config(state="normal")
            if n > 0:
                messagebox.showinfo("Terminé", f"✅ {n} dossier(s) créé(s) !")
            else:
                messagebox.showwarning("Terminé", "Aucun dossier créé. Voir le journal.")

        threading.Thread(target=do, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
