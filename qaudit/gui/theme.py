# SPDX-License-Identifier: AGPL-3.0-or-later
"""Charte graphique de l'application PC — la même que les rapports HTML et PDF
(encre marine, filet or, couleurs sémantiques du verdict et des gravités).

Uniquement des styles ttk/tk : aucune dépendance, aucune image, aucune police
téléchargée (les familles citées ont un repli système).
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

INK = "#0b1f3a"
INK2 = "#17335d"
GOLD = "#b8860b"
PAPER = "#f3f1ea"
CARD = "#ffffff"
TEXT = "#1f2933"
MUTED = "#5f6b7a"
RULE = "#e4dfd4"
RULE2 = "#eef1f6"
SELECT = "#dbe4f0"

SEMANTIC: dict[str, tuple[str, str]] = {
    "GO": ("#166534", "#e8f5ec"),
    "GO_CONDITIONAL": ("#a15c07", "#fdf3e1"),
    "NO_GO": ("#991b1b", "#fdecec"),
    "passed": ("#166534", "#e8f5ec"),
    "triggered": ("#991b1b", "#fdecec"),
    "indecision": ("#a15c07", "#fdf3e1"),
    "not_evaluated": ("#475569", "#eef2f7"),
    "blocking": ("#991b1b", "#fdecec"),
    "major": ("#c2410c", "#fff0e6"),
    "minor": ("#8a6d00", "#fff8db"),
    "info": ("#475569", "#eef2f7"),
    "neutral": ("#475569", RULE2),
}

SERIF = "Georgia"
SANS = "Segoe UI"
MONO = "Consolas"
FONT_UI = (SANS, 10)
FONT_SMALL = (SANS, 9)
FONT_BOLD = (SANS, 9, "bold")
FONT_LOG = (MONO, 9)
FONT_BRAND = (SERIF, 17)
FONT_HEADING = (SERIF, 13)
FONT_DECISION = (SERIF, 26)
FONT_CAPTION = (SANS, 8)


SCALE = 1.0  # facteur d'échelle DPI (1.0 = 96 dpi), fixé par setup_scaling


def enable_dpi_awareness() -> None:
    """Windows : déclare le processus sensible au DPI avant la création de Tk,
    pour un rendu net sur les écrans à l'échelle 125–200 % (sinon Windows étire
    la fenêtre en bitmap). Sans effet ailleurs ; un refus (déjà fixé pour ce
    processus) est ignoré car sans conséquence."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        return


def setup_scaling(root: tk.Tk) -> float:
    """Aligne l'échelle Tk sur le DPI réel ; retourne le facteur (1.0 = 96 dpi)."""
    global SCALE  # unique état de module, fixé une fois par fenêtre
    dpi = float(root.winfo_fpixels("1i"))
    SCALE = max(1.0, dpi / 96.0)
    root.tk.call("tk", "scaling", dpi / 72.0)
    return SCALE


def px(value: float) -> int:
    """Pixels logiques → pixels physiques."""
    return round(value * SCALE)


def apply_theme(root: tk.Tk) -> ttk.Style:
    """Configure les styles ttk du thème « cabinet d'audit » sur ``root``."""
    setup_scaling(root)
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=PAPER)
    root.option_add("*TCombobox*Listbox.font", FONT_UI)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
    root.option_add("*TCombobox*Listbox.selectForeground", INK)

    style.configure(".", background=PAPER, foreground=TEXT, font=FONT_UI, bordercolor=RULE,
                    lightcolor=RULE, darkcolor=RULE, focuscolor=GOLD, troughcolor=RULE2)
    style.configure("TFrame", background=PAPER)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=PAPER, foreground=TEXT)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT)
    style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=FONT_SMALL)
    style.configure("Caption.TLabel", background=CARD, foreground=MUTED, font=FONT_CAPTION)
    style.configure("Heading.TLabel", background=CARD, foreground=INK, font=FONT_HEADING)
    style.configure("Status.TLabel", background=CARD, foreground=MUTED, font=FONT_SMALL)

    style.configure("TButton", padding=(12, 6), background=RULE2, foreground=INK, borderwidth=1,
                    focusthickness=0, bordercolor=RULE, lightcolor=RULE2, darkcolor=RULE2)
    style.map("TButton", background=[("active", RULE), ("pressed", RULE)],
              bordercolor=[("active", GOLD)])
    style.configure("Primary.TButton", background=INK, foreground=CARD, borderwidth=0,
                    padding=(16, 7), font=(SANS, 10, "bold"))
    style.map("Primary.TButton", background=[("active", INK2), ("pressed", INK2),
                                             ("disabled", "#9aa5b1")],
              foreground=[("disabled", CARD)])
    style.configure("Small.TButton", padding=(6, 4), width=3)

    style.configure("TEntry", fieldbackground=CARD, padding=4, insertcolor=INK)
    style.map("TEntry", bordercolor=[("focus", GOLD)], lightcolor=[("focus", GOLD)])
    style.configure("TCombobox", fieldbackground=CARD, background=RULE2, arrowcolor=INK,
                    padding=3, arrowsize=px(16))
    style.map("TCombobox", fieldbackground=[("readonly", CARD)],
              bordercolor=[("focus", GOLD)], lightcolor=[("focus", GOLD)])

    style.configure("TNotebook", background=PAPER, borderwidth=0, tabmargins=(0, 4, 0, 0))
    style.configure("TNotebook.Tab", padding=(16, 8), background=PAPER, foreground=MUTED,
                    font=FONT_UI, borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", INK)],
              expand=[("selected", (0, 0, 0, 0))])

    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                    rowheight=px(27), borderwidth=0, font=FONT_UI)
    style.configure("Treeview.Heading", background=RULE2, foreground=INK, font=FONT_BOLD,
                    padding=(8, 7), relief="flat", borderwidth=0)
    style.map("Treeview.Heading", background=[("active", RULE2)])
    style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", INK)])

    style.configure("Horizontal.TProgressbar", troughcolor=RULE2, background=GOLD,
                    bordercolor=RULE2, lightcolor=GOLD, darkcolor=GOLD, thickness=px(6))
    style.configure("TPanedwindow", background=PAPER)
    style.configure("Sash", sashthickness=px(8), gripcount=0)
    style.configure("Vertical.TScrollbar", background=RULE, troughcolor=PAPER, arrowcolor=MUTED,
                    borderwidth=0, arrowsize=px(14))
    style.map("Vertical.TScrollbar", background=[("active", MUTED)])
    return style


def tag_rows(tree: ttk.Treeview) -> None:
    """Déclare sur un tableau les étiquettes de couleur (statuts, gravités, verdicts)."""
    for tag, (fg, bg) in SEMANTIC.items():
        tree.tag_configure(tag, foreground=fg, background=bg)
    tree.tag_configure("even", background="#fbfaf7")
