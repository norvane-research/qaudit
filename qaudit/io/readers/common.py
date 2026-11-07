# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outils communs aux lecteurs : empreinte, décodage, correspondance d'en-têtes."""

from __future__ import annotations

import codecs
import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

import numpy as np

from qaudit.core.models import ALL_FIELDS, REQUIRED_FIELDS, Cell
from qaudit.core.validate import parse_datetime

_NUMERIC = re.compile(r"^[-+]?\d+([.,]\d+)?$")
ENCODINGS: tuple[str, ...] = ("utf-16 (BOM seulement)", "utf-8-sig", "cp1252")

# Synonymes d'en-têtes reconnus (normalisés : minuscules, sans espaces ni
# ponctuation). L'ordre des champs compte : un même en-tête n'est attribué
# qu'une fois, au premier champ qui le réclame.
SYNONYMS: Mapping[str, tuple[str, ...]] = {
    "open_time": (
        "opentime", "timeopen", "entrytime", "dateopen", "opendate", "openingtime",
        "heureouverture", "dateouverture", "ouverture", "entry", "timein", "start",
        "starttime", "opened",
    ),
    "close_time": (
        "closetime", "timeclose", "exittime", "dateclose", "closedate", "closingtime",
        "heurecloture", "datecloture", "cloture", "exit", "timeout", "end", "endtime",
        "closed", "time",
    ),
    "profit": (
        "profit", "pnl", "pl", "netprofit", "net", "result", "gain", "resultat",
        "profitloss", "netpnl", "realizedpnl", "realisedpnl", "return", "pandl",
    ),
    "volume": ("volume", "lots", "lot", "size", "qty", "quantity", "taille", "contracts", "units"),
    "direction": ("direction", "side", "type", "sens", "buysell", "action", "position_type"),
    "symbol": ("symbol", "instrument", "ticker", "pair", "symbole", "market", "asset", "item"),
    "open_price": (
        "openprice", "entryprice", "priceopen", "prixouverture", "priceentry", "entry_px",
        "openpx", "avgentry", "pricein",
    ),
    "close_price": (
        "closeprice", "exitprice", "priceclose", "prixcloture", "priceexit", "exit_px",
        "closepx", "avgexit", "priceout",
    ),
    "stop_loss": ("sl", "stoploss", "stop", "stoplossprice", "slprice"),
    "take_profit": ("tp", "takeprofit", "target", "takeprofitprice", "tpprice"),
    "ticket": (
        "ticket", "id", "order", "orderid", "deal", "dealid", "position", "positionid",
        "tradeid", "trade", "tradeno", "no", "num",
    ),
    "commission": ("commission", "commissions", "fee", "fees", "comm"),
    "swap": ("swap", "swaps", "rollover", "financing", "overnight"),
    "currency": ("currency", "devise", "ccy", "cur"),
}


def fingerprint_bytes(data: bytes) -> str:
    """Empreinte SHA-256 hexadécimale des octets d'entrée."""
    return hashlib.sha256(data).hexdigest()


def decode_bytes(data: bytes) -> str:
    """Décode en essayant les encodages usuels des exports de plateformes.

    L'UTF-16 n'est tenté qu'en présence d'une marque d'ordre des octets : le
    codec accepte n'importe quelle suite d'octets de longueur paire, et un
    fichier ANSI (cp1252) de longueur paire sortirait en charabia. Sinon : UTF-8
    (avec ou sans BOM), puis cp1252 en dernier recours.
    """
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def normalise_header(name: str) -> str:
    """Minuscules, accents retirés (« Clôture » → « cloture »), rien d'autre que
    [a-z0-9] : la clé de comparaison des en-têtes."""
    decomposed = unicodedata.normalize("NFKD", name.strip().lower())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", plain)


def infer_mapping(columns: Sequence[str]) -> dict[str, str]:
    """Correspondance champ canonique → colonne, par synonymes d'en-tête."""
    normalised = {normalise_header(c): c for c in columns}
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for field_name in ALL_FIELDS:
        for candidate in (normalise_header(field_name), *SYNONYMS.get(field_name, ())):
            column = normalised.get(candidate)
            if column is not None and column not in taken:
                mapping[field_name] = column
                taken.add(column)
                break
    return mapping


def _looks_like_datetime(values: Iterable[Cell]) -> bool:
    """Vrai si les premières valeurs non vides sont des horodatages *lisibles*
    (date ou date-heure textuelle). Une colonne de nombres purs — identifiants,
    epochs — n'est jamais déduite : sans en-tête reconnu, c'est la porte E1."""
    seen = 0
    for value in values:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str | np.datetime64 | datetime) or (
            isinstance(value, str) and _NUMERIC.match(value.strip())
        ):
            return False
        try:
            parse_datetime(value)
        except ValueError:
            return False
        seen += 1
        if seen >= 5:
            break
    return seen > 0


def deduce_time_columns(
    columns: Sequence[str], rows: Sequence[Sequence[Cell]], mapping: Mapping[str, str]
) -> dict[str, str]:
    """Déduction par le contenu : les colonnes non attribuées dont les valeurs
    se lisent comme des horodatages deviennent, dans l'ordre, ouverture puis
    clôture. Rien d'autre n'est deviné (porte E1 sinon)."""
    out = dict(mapping)
    taken = set(out.values())
    needed = [f for f in ("open_time", "close_time") if f not in out]
    if not needed:
        return out
    for pos, column in enumerate(columns):
        if column in taken or not needed:
            continue
        if _looks_like_datetime(row[pos] for row in rows[:50]):
            out[needed.pop(0)] = column
            taken.add(column)
    return out


def missing_required_fields(mapping: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(f for f in REQUIRED_FIELDS if f not in mapping)
