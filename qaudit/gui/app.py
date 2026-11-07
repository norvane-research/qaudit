# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fenêtre principale de l'application PC (tkinter / ttk — livré avec Python).

Trois zones : le formulaire (dossier, options, offre), les résultats (verdict,
barrières, constats, journal) et l'historique des audits du dossier de sortie.
L'audit tourne dans un fil d'arrière-plan ; la fenêtre reste réactive et
n'affiche que ce que le contrôleur lui rend (``qaudit.gui.controller``).

Aucune chaîne destinée à l'utilisateur n'est écrite ici : tout passe par les
clés ``gui.*`` des catalogues i18n.
"""

from __future__ import annotations

import gc
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from qaudit import ENGINE_VERSION, i18n
from qaudit.core.validate import parse_float
from qaudit.gui import controller as ctl
from qaudit.gui import theme
from qaudit.i18n import Catalog
from qaudit.io.document import Json
from qaudit.io.profile import DEFAULT_PROFILE, load_profile
from qaudit.io.readers.common import infer_mapping
from qaudit.io.ruleset import skeleton as ruleset_skeleton
from qaudit.io.writers.render import Fmt

PADX, PADY = 6, 4


class MappingDialog(tk.Toplevel):
    """Éditeur de correspondance E1 : un champ canonique ↔ une colonne vue."""

    def __init__(
        self, master: tk.Misc, catalog: Catalog, columns: tuple[str, ...], choices: ctl.Choices
    ) -> None:
        super().__init__(master)
        self.title(catalog.text("gui.mapping.title"))
        self.resizable(False, False)
        self.configure(bg=theme.PAPER, padx=10, pady=8)
        self.result: dict[str, str] | None = None
        self._vars: dict[str, tk.StringVar] = {}
        ttk.Label(self, text=catalog.text("gui.mapping.intro"), wraplength=520).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=PADX, pady=PADY
        )
        options = ("", *columns)
        for row, field_name in enumerate(choices.fields, start=1):
            required = field_name in choices.required_fields
            label = field_name + (" *" if required else "")
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="e", padx=PADX, pady=PADY)
            var = tk.StringVar(value="")
            self._vars[field_name] = var
            ttk.Combobox(self, textvariable=var, values=options, state="readonly", width=40).grid(
                row=row, column=1, sticky="w", padx=PADX, pady=PADY
            )
        buttons = ttk.Frame(self)
        buttons.grid(row=len(choices.fields) + 1, column=0, columnspan=2, sticky="e",
                     padx=PADX, pady=PADY)
        ttk.Button(buttons, text=catalog.text("gui.cancel"), command=self.destroy).pack(
            side="right", padx=4
        )
        ttk.Button(buttons, text=catalog.text("gui.mapping.apply"), command=self._apply).pack(
            side="right", padx=4
        )
        self._required = choices.required_fields
        self._catalog = catalog
        self.grab_set()

    def prefill(self, guess: dict[str, str]) -> None:
        for field_name, column in guess.items():
            if field_name in self._vars:
                self._vars[field_name].set(column)

    def _apply(self) -> None:
        mapping = {k: v.get() for k, v in self._vars.items() if v.get()}
        missing = [f for f in self._required if f not in mapping]
        if missing:
            messagebox.showwarning(
                self._catalog.text("gui.mapping.title"),
                self._catalog.text("gui.mapping.missing", fields=", ".join(missing)),
                parent=self,
            )
            return
        self.result = mapping
        self.destroy()


class App(tk.Tk):
    """Fenêtre principale."""

    def __init__(self, lang: str = i18n.DEFAULT_LANGUAGE) -> None:
        theme.enable_dpi_awareness()
        super().__init__()
        self.catalog = i18n.load(lang)
        self.choices = ctl.Choices()
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._done_queue: queue.Queue[tuple[ctl.AuditRequest, ctl.Outcome]] = queue.Queue()
        self._running = False
        self._last: ctl.AuditDone | None = None
        self._exit_after = False
        self.exit_code = 0
        # avertissements de saisie : remplaçable (tests) ; boîte de dialogue par défaut
        self.warn: Callable[[str], object] = self._warn_dialog
        self.title(f"qaudit {ENGINE_VERSION}")
        self.minsize(theme.px(1100), theme.px(700))
        theme.apply_theme(self)
        self._build_variables()
        self._build_menu()
        self._build_layout()
        self._center(theme.px(1280), theme.px(800))
        self._append_log(self.t("gui.log.hello", version=ENGINE_VERSION, log=str(log_file())))
        self.after(150, self._poll)
        self.after(200, self._bring_to_front)

    def _center(self, width: int, height: int) -> None:
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(width, screen_w - theme.px(40))
        height = min(height, screen_h - theme.px(80))
        x, y = max(0, (screen_w - width) // 2), max(0, (screen_h - height) // 2 - 20)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _bring_to_front(self) -> None:
        """Passe devant les autres fenêtres au lancement (puis redevient normale)."""
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()
        self.after(1500, lambda: self.attributes("-topmost", False))

    # ------------------------------------------------------------------ état

    def _build_variables(self) -> None:
        self.v_trades = tk.StringVar()
        self.v_kind = tk.StringVar(value="auto")
        self.v_balance = tk.StringVar()
        self.v_currency = tk.StringVar()
        self.v_prices = tk.StringVar()
        self.v_symbol = tk.StringVar()
        self.v_walkforward = tk.StringVar()
        self.v_ruleset = tk.StringVar(value="")
        self.v_profile = tk.StringVar(value=DEFAULT_PROFILE)
        self.v_lang = tk.StringVar(value=self.catalog.lang)
        self.v_seed = tk.StringVar(value="0")
        self.v_n_iter = tk.StringVar(value="")
        self.v_n_trials = tk.StringVar(value="")
        self.v_mapping = tk.StringVar()
        self.v_out = tk.StringVar(value=str(Path.home() / "qaudit-out"))
        self.v_status = tk.StringVar(value=self.catalog.text("gui.status.ready"))

    def t(self, key: str, **params: object) -> str:
        return self.catalog.text(key, **params)

    def apply_options(self, options: dict[str, str | bool]) -> None:
        """Pré-remplit depuis les arguments de lancement ; ``--run`` lance l'audit."""
        if "trades" in options:
            self.v_trades.set(str(options["trades"]))
        if "out" in options:
            self.v_out.set(str(options["out"]))
            self._refresh_history()
        if "initial_balance" in options:
            self.v_balance.set(str(options["initial_balance"]))
        self._exit_after = bool(options.get("exit_after", False))
        if options.get("run"):
            self.after(300, self._run)

    def load_example(self) -> None:
        """Charge le témoin sain embarqué (avec ses candidats walk-forward)."""
        demo = ctl.demo_folder()
        self.v_trades.set(str(demo / "healthy_witness.csv"))
        self.v_balance.set("10000")
        self.v_currency.set("USD")
        self.v_walkforward.set(str(demo / "walkforward"))
        self.v_prices.set("")
        self.v_ruleset.set("two_step_static")
        self._append_log(self.t("gui.log.example"))

    def _warn_dialog(self, text: str) -> None:
        messagebox.showwarning("qaudit", text, parent=self)

    def _warn_offer(self, document: Json) -> None:
        warning = ctl.offer_warning(
            load_profile(self.v_profile.get()), document, self.catalog
        )
        if warning:
            self._append_log(warning)
            self.warn(warning)

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label=self.t("gui.menu.open_archive"), command=self._open_archive)
        file_menu.add_command(label=self.t("gui.menu.batch"), command=self._run_batch_dialog)
        file_menu.add_separator()
        file_menu.add_command(label=self.t("gui.menu.quit"), command=self.destroy)
        menubar.add_cascade(label=self.t("gui.menu.file"), menu=file_menu)
        tools = tk.Menu(menubar, tearoff=0)
        tools.add_command(label=self.t("gui.menu.ruleset_skeleton"), command=self._save_skeleton)
        tools.add_command(label=self.t("gui.menu.mapping_editor"), command=self._edit_mapping)
        menubar.add_cascade(label=self.t("gui.menu.tools"), menu=tools)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=self.t("gui.menu.about"), command=self._about)
        menubar.add_cascade(label=self.t("gui.menu.help"), menu=help_menu)
        self.config(menu=menubar)

    # ------------------------------------------------------------------ disposition

    def _build_layout(self) -> None:
        self._build_header()
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=14, pady=(12, 8))
        form_card = ttk.Frame(paned, style="Card.TFrame", padding=(14, 12))
        results = ttk.Frame(paned, padding=(12, 0, 0, 0))
        paned.add(form_card, weight=0)
        paned.add(results, weight=1)
        self._build_form(form_card)
        self._build_results(results)
        bar = ttk.Frame(self, style="Card.TFrame", padding=(14, 6))
        bar.pack(fill="x", side="bottom")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=theme.px(180))
        self.progress.pack(side="right", padx=4)
        ttk.Label(bar, textvariable=self.v_status, style="Status.TLabel").pack(side="left")

    def _build_header(self) -> None:
        """Bandeau de marque : encre marine, nom en serif, pastille or."""
        p = theme.px
        header = tk.Frame(self, bg=theme.INK, padx=p(18), pady=p(12))
        header.pack(fill="x", side="top")
        badge = tk.Canvas(header, width=p(26), height=p(26), bg=theme.INK, highlightthickness=0)
        badge.create_oval(p(2), p(2), p(24), p(24), outline=theme.GOLD, width=p(2))
        badge.create_oval(p(8), p(8), p(18), p(18), fill=theme.GOLD, outline=theme.GOLD)
        badge.pack(side="left", padx=(0, p(10)))
        tk.Label(header, text="qaudit", font=theme.FONT_BRAND, bg=theme.INK,
                 fg="#ffffff").pack(side="left")
        tk.Label(header, text=self.t("report.brand_line", version=ENGINE_VERSION),
                 font=theme.FONT_SMALL, bg=theme.INK, fg="#c8d0dc").pack(side="left", padx=p(16))
        tk.Label(header, text=self.t("gui.header.tagline"), font=theme.FONT_SMALL,
                 bg=theme.INK, fg=theme.GOLD).pack(side="right")

    def _lab(self, parent: ttk.Frame, row: int, key: str) -> None:
        ttk.Label(parent, text=self.t(key), style="Muted.TLabel").grid(
            row=row, column=0, sticky="e", padx=PADX, pady=PADY
        )

    def _row(self, parent: ttk.Frame, row: int, key: str, var: tk.StringVar,
             browse: Callable[[], None] | None = None, width: int = 44) -> None:
        self._lab(parent, row, key)
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=row, column=1, sticky="we", padx=PADX, pady=PADY)
        if browse is not None:
            button = ttk.Button(parent, text="…", style="Small.TButton", command=browse)
            button.grid(row=row, column=2, padx=PADX, pady=PADY)

    def _combo(self, parent: ttk.Frame, row: int, key: str, var: tk.StringVar,
               values: tuple[str, ...], width: int, *, readonly: bool = True,
               browse: Callable[[], None] | None = None) -> ttk.Combobox:
        self._lab(parent, row, key)
        box = ttk.Combobox(parent, textvariable=var, values=values, width=width,
                           state="readonly" if readonly else "normal")
        box.grid(row=row, column=1, sticky="w", padx=PADX, pady=PADY)
        if browse is not None:
            button = ttk.Button(parent, text="…", style="Small.TButton", command=browse)
            button.grid(row=row, column=2, padx=PADX, pady=PADY)
        return box

    def _heading(self, parent: ttk.Frame, row: int, key: str) -> None:
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=0, columnspan=3, sticky="we", padx=PADX,
                   pady=(12 if row else 2, 6))
        tk.Frame(frame, bg=theme.GOLD, width=theme.px(16), height=theme.px(3)).pack(
            side="left", padx=(0, theme.px(8))
        )
        ttk.Label(frame, text=self.t(key), style="Heading.TLabel").pack(side="left")

    def _build_form(self, form: ttk.Frame) -> None:
        self._heading(form, 0, "gui.section.inputs")
        self._row(form, 1, "gui.field.trades", self.v_trades, self._pick_trades)
        self._combo(form, 2, "gui.field.kind", self.v_kind, self.choices.kinds, 12)
        self._row(form, 3, "gui.field.initial_balance", self.v_balance, width=16)
        self._row(form, 4, "gui.field.currency", self.v_currency, width=8)
        self._row(form, 5, "gui.field.prices", self.v_prices, self._pick_prices)
        self._row(form, 6, "gui.field.symbol", self.v_symbol, width=12)
        self._row(form, 7, "gui.field.walkforward", self.v_walkforward, self._pick_walkforward)
        self._row(form, 8, "gui.field.mapping", self.v_mapping, self._pick_mapping)
        self._heading(form, 9, "gui.section.options")
        self._combo(form, 10, "gui.field.ruleset", self.v_ruleset, ("", *self.choices.rulesets),
                    30, readonly=False, browse=self._pick_ruleset)
        self.profile_box = self._combo(form, 11, "gui.field.profile", self.v_profile,
                                       self.choices.profiles, 30)
        self._combo(form, 12, "gui.field.lang", self.v_lang, self.choices.languages, 6)
        self._row(form, 13, "gui.field.seed", self.v_seed, width=8)
        self._row(form, 14, "gui.field.n_iter", self.v_n_iter, width=8)
        self._row(form, 15, "gui.field.n_trials", self.v_n_trials, width=8)
        self._row(form, 16, "gui.field.out", self.v_out, self._pick_out)
        buttons = ttk.Frame(form, style="Card.TFrame")
        buttons.grid(row=17, column=0, columnspan=3, sticky="we", pady=(16, 4))
        self.run_button = ttk.Button(buttons, text=self.t("gui.action.audit"),
                                     style="Primary.TButton", command=self._run)
        self.run_button.pack(side="left", padx=(PADX, 8))
        ttk.Button(buttons, text=self.t("gui.action.load_example"),
                   command=self.load_example).pack(side="left", padx=4)
        outputs = ttk.Frame(form, style="Card.TFrame")
        outputs.grid(row=18, column=0, columnspan=3, sticky="we", pady=(4, 2))
        for key, command in (("gui.action.open_html", self._open_html),
                             ("gui.action.open_pdf", self._open_pdf),
                             ("gui.action.open_folder", self._open_out)):
            ttk.Button(outputs, text=self.t(key), command=command).pack(side="left",
                                                                         padx=(PADX, 4))

    def _build_results(self, parent: ttk.Frame) -> None:
        self.verdict_card = tk.Frame(parent, bg=theme.CARD, highlightthickness=1,
                                     highlightbackground=theme.RULE)
        self.verdict_card.pack(fill="x")
        self.verdict_band = tk.Frame(self.verdict_card, bg=theme.RULE, width=theme.px(8))
        self.verdict_band.pack(side="left", fill="y")
        body = self.verdict_body = tk.Frame(self.verdict_card, bg=theme.CARD, padx=theme.px(16),
                                            pady=theme.px(12))
        body.pack(side="left", fill="both", expand=True)
        self.verdict_caption = tk.Label(body, text=self.t("gui.verdict_caption"),
                                        font=theme.FONT_CAPTION, bg=theme.CARD, fg=theme.MUTED)
        self.verdict_caption.pack(anchor="w")
        self.decision_label = tk.Label(body, text="—", font=theme.FONT_DECISION, bg=theme.CARD,
                                       fg=theme.MUTED, anchor="w")
        self.decision_label.pack(anchor="w")
        self.review_label = tk.Label(body, text="", font=theme.FONT_SMALL, bg=theme.CARD,
                                     fg=theme.MUTED, anchor="w", justify="left")
        self.review_label.pack(anchor="w", fill="x")
        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True, pady=(10, 0))
        self.barriers = self._tree(notebook, "gui.tab.barriers",
                                   ("barrier", "value", "threshold", "band", "status"))
        self.findings = self._tree(notebook, "gui.tab.findings", ("severity", "code", "text"))
        self.history = self._tree(notebook, "gui.tab.history",
                                  ("name", "decision", "e3", "n", "period", "seed", "method"))
        self.history.bind("<Double-1>", lambda _e: self._open_history_item())
        log_frame = ttk.Frame(notebook, style="Card.TFrame", padding=8)
        notebook.add(log_frame, text=self.t("gui.tab.log"))
        self.log = tk.Text(log_frame, height=10, wrap="word", state="disabled",
                           font=theme.FONT_LOG, bg=theme.CARD, fg=theme.TEXT, relief="flat",
                           padx=theme.px(8), pady=theme.px(6), spacing1=theme.px(2),
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        self._refresh_history()

    def _tree(self, notebook: ttk.Notebook, key: str, columns: tuple[str, ...]) -> ttk.Treeview:
        frame = ttk.Frame(notebook, style="Card.TFrame", padding=8)
        notebook.add(frame, text=self.t(key))
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        widths = {"barrier": 260, "text": 520, "period": 250, "name": 180, "status": 120,
                  "band": 130, "value": 80, "threshold": 80, "severity": 90, "code": 190,
                  "decision": 150, "e3": 50, "n": 60, "seed": 60, "method": 70}
        numeric = {"value", "threshold", "band", "n", "seed"}
        stretch = {"barrier", "text", "period", "name"}
        for column in columns:
            tree.heading(column, text=self.t(f"gui.col.{column}"))
            tree.column(column, width=theme.px(widths.get(column, 110)),
                        minwidth=theme.px(40), stretch=column in stretch,
                        anchor="e" if column in numeric else "w")
        theme.tag_rows(tree)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    # ------------------------------------------------------------------ sélecteurs

    def _pick_trades(self) -> None:
        path = filedialog.askopenfilename(filetypes=[(self.t("gui.filetype.trades"),
                                                      "*.csv *.txt *.html *.htm")])
        if path:
            self.v_trades.set(path)

    def _pick_prices(self) -> None:
        path = filedialog.askopenfilename(filetypes=[(self.t("gui.filetype.csv"), "*.csv *.txt")])
        if path:
            self.v_prices.set(path)

    def _pick_walkforward(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.v_walkforward.set(path)

    def _pick_mapping(self) -> None:
        path = filedialog.askopenfilename(filetypes=[(self.t("gui.filetype.toml"), "*.toml")])
        if path:
            self.v_mapping.set(path)

    def _pick_ruleset(self) -> None:
        path = filedialog.askopenfilename(filetypes=[(self.t("gui.filetype.toml"), "*.toml")])
        if path:
            self.v_ruleset.set(path)

    def _pick_out(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.v_out.set(path)
            self._refresh_history()

    # ------------------------------------------------------------------ demande

    def _optional_float(self, text: str) -> float | None:
        text = text.strip()
        return parse_float(text) if text else None  # « 10 000 », « 1 234,56 » acceptés

    def _optional_int(self, text: str) -> int | None:
        text = text.strip()
        return int(text) if text else None

    def request(self) -> ctl.AuditRequest | None:
        """Construit la demande depuis le formulaire ; ``None`` et un message si invalide."""
        trades = self.v_trades.get().strip()
        if not trades:
            self.warn(self.t("gui.error.no_trades"))
            return None
        try:
            return ctl.AuditRequest(
                trades=Path(trades),
                out_dir=Path(self.v_out.get().strip() or "qaudit-out"),
                lang=self.v_lang.get(),
                kind=self.v_kind.get(),
                initial_balance=self._optional_float(self.v_balance.get()),
                currency=self.v_currency.get().strip() or None,
                prices=Path(self.v_prices.get()) if self.v_prices.get().strip() else None,
                symbol=self.v_symbol.get().strip() or None,
                walkforward=(Path(self.v_walkforward.get())
                             if self.v_walkforward.get().strip() else None),
                ruleset=self.v_ruleset.get().strip(),
                profile=self.v_profile.get(),
                seed=int(self.v_seed.get().strip() or "0"),
                n_iter=self._optional_int(self.v_n_iter.get()),
                n_trials=self._optional_int(self.v_n_trials.get()),
                mapping=Path(self.v_mapping.get()) if self.v_mapping.get().strip() else None,
            )
        except ValueError:
            self.warn(self.t("gui.error.bad_number"))
            return None

    def _run(self) -> None:
        if self._running:
            return
        request = self.request()
        if request is None:
            return
        self.catalog = i18n.load(request.lang)
        self._set_running(True)
        self._append_log(self.t("gui.log.start", name=request.name))
        worker = threading.Thread(target=self._worker, args=(request,), daemon=True)
        worker.start()

    def _worker(self, request: ctl.AuditRequest) -> None:
        outcome = ctl.run_request(request, self.catalog, log=self._log_queue.put)
        self._done_queue.put((request, outcome))

    def _poll(self) -> None:
        while not self._log_queue.empty():
            self._append_log(self._log_queue.get_nowait())
        while not self._done_queue.empty():
            request, outcome = self._done_queue.get_nowait()
            self._set_running(False)
            self._show_outcome(request, outcome)
        self.after(150, self._poll)

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.run_button.state(["disabled"] if running else ["!disabled"])
        if running:
            self.progress.start(12)
            self.v_status.set(self.t("gui.status.running"))
        else:
            self.progress.stop()
            self.v_status.set(self.t("gui.status.ready"))

    # ------------------------------------------------------------------ résultats

    def _show_outcome(self, request: ctl.AuditRequest, outcome: ctl.Outcome) -> None:
        if isinstance(outcome, ctl.AuditDone):
            self._show_done(outcome)
            self.exit_code = ctl.exit_code_of(outcome)
        elif isinstance(outcome, ctl.MappingNeeded):
            self.exit_code = 10
            if self._exit_after:
                self._append_log(self.t("gui.gate.e1"))
            else:
                self._show_mapping_needed(request, outcome)
        elif isinstance(outcome, ctl.RulesetNeeded):
            self.exit_code = 11
            self._show_ruleset_needed(outcome)
        else:
            self.exit_code = outcome.exit_code
            self._show_failed(outcome)
        self._refresh_history()
        if self._exit_after:
            self.after(200, self.destroy)

    def _show_done(self, done: ctl.AuditDone) -> None:
        self._last = done
        if done.warning:
            self.warn(done.warning)
        verdict = done.result.verdict
        label = self.t(f"decision.{verdict.decision.value}")
        self._paint_verdict(done.decision, label)
        self.review_label.config(
            text=self.t("gui.review_yes") if verdict.human_review else self.t("gui.review_no"),
            fg=theme.SEMANTIC["indecision"][0] if verdict.human_review else theme.MUTED,
        )
        fmt = Fmt(self.catalog)
        self._fill(self.barriers, [
            (
                self.t(b.message_key),
                fmt.num(b.value, 3) if b.value is not None else self.t("report.na"),
                f"{'<' if b.sense == 'below' else '≥'} {fmt.num(b.threshold, 3)}",
                f"[{fmt.num(b.band_low, 3)} ; {fmt.num(b.band_high, 3)}]",
                self._status(b.evaluated, b.triggered, b.indecision),
            )
            for b in verdict.barriers
        ], [self._status_tag(b.evaluated, b.triggered, b.indecision) for b in verdict.barriers])
        rows = []
        tags = []
        for finding in sorted(verdict.findings, key=lambda f: -int(f.severity)):
            params = dict(finding.params)
            rows.append((
                self.t("severity." + finding.severity.name.lower()),
                finding.code,
                self.t(finding.message_key, **params),
            ))
            tags.append(finding.severity.name.lower())
        self._fill(self.findings, rows, tags)
        self.v_status.set(self.t("gui.status.done", decision=label, path=str(done.archive)))
        self._append_log(self.t("gui.log.done", decision=label))
        for path in done.deliverables:
            self._append_log(self.t("cli.written", path=str(path)))

    def _status_tag(self, evaluated: bool, triggered: bool, indecision: bool) -> str:
        if not evaluated:
            return "not_evaluated"
        if triggered:
            return "triggered"
        if indecision:
            return "indecision"
        return "passed"

    def _status(self, evaluated: bool, triggered: bool, indecision: bool) -> str:
        return self.t("report.status." + self._status_tag(evaluated, triggered, indecision))

    def _paint_verdict(self, decision: str, label: str) -> None:
        colour, tint = theme.SEMANTIC.get(decision, theme.SEMANTIC["neutral"])
        self.decision_label.config(text=label, fg=colour, bg=tint)
        self.verdict_band.config(bg=colour)
        self.verdict_card.config(highlightbackground=colour)
        self.verdict_card.config(bg=tint)
        self.verdict_body.config(bg=tint)
        self.verdict_caption.config(bg=tint)
        self.review_label.config(bg=tint)

    def _show_mapping_needed(self, request: ctl.AuditRequest, gate: ctl.MappingNeeded) -> None:
        self._set_decision_neutral(self.t("gui.gate.e1"))
        self._append_log(self.t("gui.gate.e1_detail", missing=", ".join(gate.missing_fields),
                                seen=", ".join(gate.seen_columns)))
        dialog = MappingDialog(self, self.catalog, gate.seen_columns, self.choices)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        target = request.out_dir / f"mapping-{gate.header_fingerprint[:12]}.toml"
        request.out_dir.mkdir(parents=True, exist_ok=True)
        ctl.save_mapping(target, dialog.result, gate.seen_columns)
        self.v_mapping.set(str(target))
        self._append_log(self.t("gui.log.mapping_saved", path=str(target)))
        self._run()

    def _show_ruleset_needed(self, gate: ctl.RulesetNeeded) -> None:
        self._set_decision_neutral(self.t("gui.gate.e2"))
        self._append_log(gate.message)
        if self._exit_after:
            return
        if messagebox.askyesno("qaudit", self.t("gui.gate.e2_ask"), parent=self):
            self._save_skeleton()

    def _show_failed(self, failed: ctl.Failed) -> None:
        self._set_decision_neutral(self.t("gui.failed", code=failed.exit_code))
        self._append_log(failed.message)
        if not self._exit_after:
            messagebox.showerror("qaudit", failed.message, parent=self)

    def _set_decision_neutral(self, text: str) -> None:
        self._last = None
        self._paint_verdict("neutral", text)
        self.review_label.config(text="")
        self._fill(self.barriers, [])
        self._fill(self.findings, [])
        self.v_status.set(text)

    def _fill(self, tree: ttk.Treeview, rows: Sequence[tuple[str, ...]],
              tags: Sequence[str] = ()) -> None:
        tree.delete(*tree.get_children())
        for i, row in enumerate(rows):
            tag = tags[i] if i < len(tags) and tags[i] else ("even" if i % 2 else "")
            tree.insert("", "end", values=row, tags=(tag,) if tag else ())

    def _append_log(self, text: str) -> None:
        write_log(text)
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------ historique

    def _refresh_history(self) -> None:
        out = Path(self.v_out.get().strip() or "qaudit-out")
        rows = []
        summaries = []
        for archive in ctl.list_archives(out):
            try:
                s = ctl.archive_summary(archive)
            except (OSError, ValueError, KeyError):
                continue
            summaries.append(s)
            rows.append((s["name"], self.t(f"decision.{s['decision']}"), s["human_review"],
                         s["n_trades"], s["period"], s["seed"], s["method"]))
        self._fill(self.history, rows, [str(s["decision"]) for s in summaries])

    def _open_history_item(self) -> None:
        selected = self.history.selection()
        if not selected:
            return
        name = str(self.history.item(selected[0], "values")[0])
        out = Path(self.v_out.get().strip() or "qaudit-out")
        archive = out / "archive" / f"{name}.json"
        if archive.exists():
            document, written = ctl.render_archive(
                archive, out, self.catalog, self.v_profile.get()
            )
            self._append_log(self.t("gui.log.rendered", name=name, profile=self.v_profile.get()))
            self._warn_offer(document)
            html = next((p for p in written if p.suffix == ".html"), None)
            if html is not None:
                ctl.open_path(html)

    def _open_archive(self) -> None:
        path = filedialog.askopenfilename(filetypes=[(self.t("gui.filetype.json"), "*.json")])
        if not path:
            return
        out = Path(self.v_out.get().strip() or "qaudit-out")
        document, written = ctl.render_archive(
            Path(path), out, self.catalog, self.v_profile.get()
        )
        for p in written:
            self._append_log(self.t("cli.written", path=str(p)))
        self._warn_offer(document)
        self._refresh_history()

    # ------------------------------------------------------------------ actions

    def _open_html(self) -> None:
        self._open_deliverable(".html")

    def _open_pdf(self) -> None:
        self._open_deliverable(".pdf")

    def _open_deliverable(self, suffix: str) -> None:
        if self._last is None:
            messagebox.showinfo("qaudit", self.t("gui.error.no_result"), parent=self)
            return
        path = next((p for p in self._last.deliverables if p.suffix == suffix), None)
        if path is None:
            messagebox.showinfo("qaudit", self.t("gui.error.not_in_profile", ext=suffix),
                                parent=self)
            return
        ctl.open_path(path)

    def _open_out(self) -> None:
        out = Path(self.v_out.get().strip() or "qaudit-out")
        out.mkdir(parents=True, exist_ok=True)
        ctl.open_path(out)

    def _save_skeleton(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".toml", initialfile="reglement.toml",
                                            filetypes=[(self.t("gui.filetype.toml"), "*.toml")])
        if path:
            Path(path).write_text(ruleset_skeleton(), encoding="utf-8")
            self._append_log(self.t("gui.log.skeleton_saved", path=path))
            self.v_ruleset.set(path)

    def _edit_mapping(self) -> None:
        trades = self.v_trades.get().strip()
        if not trades:
            messagebox.showwarning("qaudit", self.t("gui.error.no_trades"), parent=self)
            return
        columns = ctl.table_columns(Path(trades), self.v_kind.get())
        dialog = MappingDialog(self, self.catalog, columns, self.choices)
        dialog.prefill(infer_mapping(columns))
        self.wait_window(dialog)
        if dialog.result is None:
            return
        target = filedialog.asksaveasfilename(defaultextension=".toml", initialfile="mapping.toml",
                                              filetypes=[(self.t("gui.filetype.toml"), "*.toml")])
        if target:
            ctl.save_mapping(Path(target), dialog.result, columns)
            self.v_mapping.set(target)

    def _run_batch_dialog(self) -> None:
        folder = filedialog.askdirectory(title=self.t("gui.menu.batch"))
        if not folder:
            return
        from qaudit.cli.main import main as cli_main

        args = ["batch", folder, "--out", self.v_out.get().strip() or "qaudit-out",
                "--offre", self.v_profile.get(), "--lang", self.v_lang.get()]
        if self.v_balance.get().strip():
            args += ["--initial-balance", self.v_balance.get().strip().replace(",", ".")]
        self._append_log(self.t("gui.log.batch_start", path=folder))
        code = cli_main(args)
        self._append_log(self.t("gui.log.batch_done", code=code))
        self._refresh_history()
        ctl.open_path(Path(self.v_out.get().strip() or "qaudit-out") / "portfolio.html")

    def _about(self) -> None:
        messagebox.showinfo(self.t("gui.menu.about"), ctl.about_text(self.catalog), parent=self)


def log_file() -> Path:
    """Journal de l'application : ``~/qaudit-out/qaudit-gui.log``."""
    return Path.home() / "qaudit-out" / "qaudit-gui.log"


def write_log(text: str) -> None:
    try:
        path = log_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
    except OSError:
        return  # un journal indisponible ne doit jamais empêcher l'audit


def parse_args(argv: list[str]) -> dict[str, str | bool]:
    """Options de lancement : un fichier de trades déposé sur l'icône, ``--lang``,
    ``--out``, ``--initial-balance``, ``--run`` (lancer aussitôt), ``--exit-after``
    (fermer une fois l'audit rendu ; le code de sortie est alors le verdict)."""
    options: dict[str, str | bool] = {}
    items = list(argv)
    while items:
        item = items.pop(0)
        if item in ("--lang", "--out", "--initial-balance") and items:
            options[item[2:].replace("-", "_")] = items.pop(0)
        elif item in ("--run", "--exit-after"):
            options[item[2:].replace("-", "_")] = True
        elif not item.startswith("--"):
            options["trades"] = item
    return options


def hide_own_console() -> bool:
    """Windows : masque la fenêtre console si ce processus en est le seul
    occupant (lancement par double-clic sur ``qaudit.exe gui``). Depuis un
    terminal (plusieurs occupants) la console est laissée intacte. Vrai si
    masquée."""
    if sys.platform != "win32":
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    window = kernel32.GetConsoleWindow()
    if not window:
        return False
    owners = (ctypes.c_uint * 2)()
    if kernel32.GetConsoleProcessList(owners, 2) > 1:
        return False
    ctypes.windll.user32.ShowWindow(window, 0)  # SW_HIDE
    return True


def _open_app(lang: str, attempts: int = 3) -> App:
    """Crée la fenêtre ; réessaie brièvement si Tcl n'a pas pu lire ses fichiers
    d'initialisation (verrou passager d'un antivirus sur ``init.tcl``, observé)."""
    for attempt in range(attempts):
        try:
            return App(lang)
        except tk.TclError as error:
            write_log(f"Tk init attempt {attempt + 1}/{attempts}: {error}")
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)
    raise RuntimeError("unreachable")


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée ``qaudit-gui``. Un plantage est journalisé et affiché,
    jamais silencieux."""
    options = parse_args(list(sys.argv[1:] if argv is None else argv))
    lang = str(options.get("lang", i18n.DEFAULT_LANGUAGE))
    if lang not in i18n.LANGUAGES:
        lang = i18n.DEFAULT_LANGUAGE
    try:
        app = _open_app(lang)
        app.apply_options(options)
        app.mainloop()
    except Exception as error:  # noqa: BLE001 — dernier recours : journal + boîte de dialogue
        detail = traceback.format_exc()
        write_log(detail)
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("qaudit", i18n.load(lang).text("gui.crash", error=str(error),
                                                       log=str(log_file())))
        return 30
    code = app.exit_code
    del app  # dernière référence lâchée : la fenêtre n'est plus tenue que par ses cycles
    reclaim_destroyed_windows()
    return code


def reclaim_destroyed_windows() -> None:
    """Libère maintenant, dans le fil qui possède Tcl, les fenêtres déjà détruites.

    Une fenêtre détruite survit par des cycles de références (chaque variable Tk
    pointe vers sa racine, qui la référence en retour) jusqu'au prochain passage
    du ramasse-miettes, lequel a lieu dans le fil qui alloue à ce moment-là —
    typiquement le fil d'audit d'une fenêtre suivante. Or Tcl ne supporte d'être
    appelé ou détruit que depuis son propre fil : « main thread is not in main
    loop », fichiers de Tcl/Tk introuvables à la création de la fenêtre suivante,
    voire arrêt du processus (« Tcl_AsyncDelete: async handler deleted by the
    wrong thread »). À appeler depuis le fil principal, la fenêtre détruite et
    lâchée."""
    gc.collect()


if __name__ == "__main__":
    raise SystemExit(main())
