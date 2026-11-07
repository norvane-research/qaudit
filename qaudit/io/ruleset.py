# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chargeur de règlement propfirm (TOML → ``Ruleset``) et squelette de la porte E2.

Une règle n'est **jamais** devinée : toute clé obligatoire absente lève
``RulesetError`` avec la liste des clés manquantes, et la coquille imprime le
squelette à compléter. La date de relevé ``as_of`` est obligatoire : les firmes
changent leurs règles souvent.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any

from qaudit.core.errors import RulesetError
from qaudit.core.propfirm import PhaseRule, Ruleset

REQUIRED_TOP: tuple[str, ...] = (
    "name", "as_of", "initial_balance", "currency", "fee", "refund_fee_on_funded",
    "profit_split", "payout_cycle_days", "balance_carry", "phases",
)
REQUIRED_PHASE: tuple[str, ...] = (
    "name", "funded", "profit_target", "max_daily_loss", "daily_loss_base", "max_total_loss",
    "drawdown_type", "trailing_lock_at_initial", "min_trading_days", "max_days",
    "consistency_max_day_share",
)

SKELETON = '''# Règlement propfirm — squelette qaudit (porte E2). Compléter CHAQUE clé :
# une règle absente est écrite explicitement (0 = pas de règle), jamais devinée.

name = "Nom de la firme et du programme"
as_of = 2026-01-01              # OBLIGATOIRE : date de relevé des règles (AAAA-MM-JJ)
initial_balance = 100000
currency = "USD"
fee = 500                       # frais d'inscription
refund_fee_on_funded = true     # frais remboursés une fois financé ?
profit_split = 0.80             # part du trader sur les profits en phase financée
payout_cycle_days = 14          # cycle de versement, en journées de trading
balance_carry = "reset"         # "reset" (chaque phase repart du solde initial) | "carry"

[[phases]]
name = "Phase 1"
funded = false
profit_target = 0.10            # fraction du solde de référence (0 si phase financée)
max_daily_loss = 0.05           # fraction ; 0 = pas de règle journalière
daily_loss_base = "initial"     # "initial" | "balance" (solde de début de journée)
max_total_loss = 0.10           # fraction du solde de référence
drawdown_type = "static"        # "static" | "trailing" (plus haut des soldes de fin de journée)
trailing_lock_at_initial = false
min_trading_days = 4
max_days = 0                    # jours calendaires ; 0 = sans limite (horizon paramétrable)
consistency_max_day_share = 0.0 # part max d'une journée dans le profit ; 0 = pas de règle

[[phases]]
name = "Financé"
funded = true
profit_target = 0.0
max_daily_loss = 0.05
daily_loss_base = "initial"
max_total_loss = 0.10
drawdown_type = "static"
trailing_lock_at_initial = false
min_trading_days = 0
max_days = 0
consistency_max_day_share = 0.0
'''


def skeleton() -> str:
    return SKELETON


def builtin_names() -> tuple[str, ...]:
    root = resources.files("qaudit.io.rulesets")
    return tuple(sorted(p.name[:-5] for p in root.iterdir() if p.name.endswith(".toml")))


def _as_of(value: object) -> str:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise RulesetError("propfirm.bad_as_of", value=value) from exc
    raise RulesetError("propfirm.bad_as_of", value=str(value))


def _phase(raw: Mapping[str, Any], index: int) -> PhaseRule:
    missing = tuple(f"phases[{index}].{k}" for k in REQUIRED_PHASE if k not in raw)
    if missing:
        raise RulesetError("propfirm.missing_keys", missing_keys=missing)
    return PhaseRule(
        name=str(raw["name"]),
        funded=bool(raw["funded"]),
        profit_target=float(raw["profit_target"]),
        max_daily_loss=float(raw["max_daily_loss"]),
        daily_loss_base=str(raw["daily_loss_base"]),
        max_total_loss=float(raw["max_total_loss"]),
        drawdown_type=str(raw["drawdown_type"]),
        trailing_lock_at_initial=bool(raw["trailing_lock_at_initial"]),
        min_trading_days=int(raw["min_trading_days"]),
        max_days=int(raw["max_days"]),
        consistency_max_day_share=float(raw["consistency_max_day_share"]),
    )


def parse_ruleset(raw: Mapping[str, Any]) -> Ruleset:
    missing = tuple(k for k in REQUIRED_TOP if k not in raw)
    if missing:
        raise RulesetError("propfirm.missing_keys", missing_keys=missing)
    phases_raw = raw["phases"]
    if not isinstance(phases_raw, list) or not phases_raw:
        raise RulesetError("propfirm.missing_keys", missing_keys=("phases",))
    return Ruleset(
        name=str(raw["name"]),
        as_of=_as_of(raw["as_of"]),
        initial_balance=float(raw["initial_balance"]),
        currency=str(raw["currency"]),
        fee=float(raw["fee"]),
        refund_fee_on_funded=bool(raw["refund_fee_on_funded"]),
        profit_split=float(raw["profit_split"]),
        payout_cycle_days=int(raw["payout_cycle_days"]),
        balance_carry=str(raw["balance_carry"]),
        phases=tuple(_phase(p, i) for i, p in enumerate(phases_raw)),
    )


def parse_ruleset_text(text: str) -> Ruleset:
    """Texte TOML → règlement ; de la prose (non TOML) est une porte E2."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RulesetError("propfirm.not_toml", detail=str(exc)) from exc
    return parse_ruleset(raw)


def load_ruleset(source: str | Path) -> Ruleset:
    """Charge un modèle embarqué (nom sans ``.toml``) ou un fichier TOML."""
    if isinstance(source, str) and source in builtin_names():
        text = resources.files("qaudit.io.rulesets").joinpath(f"{source}.toml").read_text(
            encoding="utf-8"
        )
        return parse_ruleset_text(text)
    path = Path(source)
    if not path.exists():
        raise RulesetError("propfirm.not_found", path=str(path), builtin=", ".join(builtin_names()))
    return parse_ruleset_text(path.read_text(encoding="utf-8"))
