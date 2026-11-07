# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèles du noyau — tous immuables (``frozen=True``).

Un traitement ne modifie jamais son entrée : les tableaux numpy sont copiés à la
construction puis passés en lecture seule. Aucune chaîne destinée à
l'utilisateur n'apparaît ici : les constats portent des clés i18n.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from qaudit.core.errors import InternalError

FloatArray = NDArray[np.float64]
TimeArray = NDArray[np.datetime64]
IntArray = NDArray[np.int64]
Int8Array = NDArray[np.int8]
StrArray = NDArray[np.str_]
BoolArray = NDArray[np.bool_]
IndexArray = NDArray[np.intp]

ParamValue = float | int | str | bool
Params = tuple[tuple[str, ParamValue], ...]
Cell = str | float | int | bool | np.datetime64 | datetime | None

NS_PER_DAY = 86_400_000_000_000
DAYS_PER_YEAR = 365.25

# Champs canoniques d'un jeu de trades. Les trois premiers sont obligatoires ;
# les autres, s'ils manquent, désactivent proprement les analyses qui en dépendent.
REQUIRED_FIELDS: tuple[str, ...] = ("open_time", "close_time", "profit")
OPTIONAL_FIELDS: tuple[str, ...] = (
    "direction",
    "volume",
    "symbol",
    "open_price",
    "close_price",
    "stop_loss",
    "take_profit",
    "ticket",
    "commission",
    "swap",
    "currency",
)
ALL_FIELDS: tuple[str, ...] = REQUIRED_FIELDS + OPTIONAL_FIELDS


class Severity(IntEnum):
    """Gravité d'un constat. L'ordre est significatif (comparable)."""

    INFO = 0
    MINOR = 1
    MAJOR = 2
    BLOCKING = 3


class Decision(StrEnum):
    """Verdict rendu. Les valeurs sont celles écrites dans le JSON."""

    GO = "GO"
    CONDITIONAL = "GO_CONDITIONAL"
    NO_GO = "NO_GO"


def time_to_iso(t: np.datetime64) -> str:
    """Horodatage ISO 8601 à la seconde, sans fuseau (convention du noyau)."""
    return str(np.datetime_as_string(t.astype("datetime64[ns]"), unit="s"))


def _params(items: dict[str, ParamValue]) -> Params:
    """Ordre lexicographique des paramètres : déterminisme du rendu et du JSON."""
    return tuple(sorted(items.items()))


@dataclass(frozen=True, slots=True)
class Finding:
    """Constat émis par la validation ou par un détecteur.

    ``code`` est un identifiant stable (ex. ``"martingale"``), ``message_key``
    la clé i18n du texte, ``source`` le composant émetteur.
    """

    code: str
    severity: Severity
    message_key: str
    source: str
    params: Params = ()

    @staticmethod
    def make(
        code: str,
        severity: Severity,
        message_key: str,
        source: str,
        **params: ParamValue,
    ) -> Finding:
        return Finding(code, severity, message_key, source, _params(params))

    def param(self, name: str) -> ParamValue:
        for key, value in self.params:
            if key == name:
                return value
        raise InternalError("internal.missing_param", name=name, code=self.code)

    def has_param(self, name: str) -> bool:
        return any(key == name for key, _ in self.params)

    def number(self, name: str) -> float:
        """Paramètre numérique ; une chaîne à cette place est un défaut interne."""
        value = self.param(name)
        if isinstance(value, str):
            raise InternalError("internal.param_not_numeric", name=name, code=self.code)
        return float(value)


@dataclass(frozen=True, slots=True)
class Condition:
    """Condition de mise en production attachée à un verdict conditionnel."""

    code: str
    message_key: str
    params: Params = ()

    @staticmethod
    def make(code: str, message_key: str, **params: ParamValue) -> Condition:
        return Condition(code, message_key, _params(params))

    def param(self, name: str) -> ParamValue:
        for key, value in self.params:
            if key == name:
                return value
        raise InternalError("internal.missing_param", name=name, code=self.code)

    def number(self, name: str) -> float:
        value = self.param(name)
        if isinstance(value, str):
            raise InternalError("internal.param_not_numeric", name=name, code=self.code)
        return float(value)


BarrierSense = Literal["below", "at_or_above"]


@dataclass(frozen=True, slots=True)
class BarrierResult:
    """Résultat d'une barrière de décision.

    ``sense`` dit quand la barrière se déclenche : ``"below"`` → NO-GO si
    ``value < threshold`` ; ``"at_or_above"`` → NO-GO si ``value >= threshold``.
    ``indecision`` est vrai quand la valeur tombe dans la bande [band_low, band_high]
    (porte E3). Une barrière non évaluée n'est ni déclenchée ni en indécision.
    """

    name: str
    value: float | None
    threshold: float
    band_low: float | None
    band_high: float | None
    sense: BarrierSense
    evaluated: bool
    triggered: bool
    indecision: bool
    message_key: str


@dataclass(frozen=True, slots=True)
class Verdict:
    """Verdict mécanique : découle des barrières déclenchées, jamais d'un score."""

    decision: Decision
    barriers: tuple[BarrierResult, ...]
    findings: tuple[Finding, ...]
    conditions: tuple[Condition, ...]
    human_review: bool
    method_version: str

    def count(self, severity: Severity) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    @property
    def blocking_count(self) -> int:
        return self.count(Severity.BLOCKING)

    @property
    def major_count(self) -> int:
        return self.count(Severity.MAJOR)


def _frozen_array(values: object, dtype: str | type[np.generic]) -> NDArray[Any]:
    """Copie toujours (jamais de vue sur l'entrée), puis interdit l'écriture."""
    arr = np.array(values, dtype=dtype, copy=True)
    if arr.ndim != 1:
        raise InternalError("internal.array_ndim", ndim=int(arr.ndim))
    arr.setflags(write=False)
    return arr


@dataclass(frozen=True, eq=False)
class RawTable:
    """Table brute produite par un lecteur, avant validation.

    ``line_numbers[i]`` est le numéro de ligne de ``rows[i]`` dans la source
    (1 = première ligne du fichier), pour que toute erreur nomme sa ligne.
    ``fingerprint`` est l'empreinte SHA-256 hexadécimale des octets d'entrée.
    """

    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    line_numbers: tuple[int, ...]
    fingerprint: str
    source: str
    initial_balance: float | None = None
    currency: str | None = None
    notes: tuple[tuple[str, Params], ...] = ()  # constats « info » du lecteur (clé, paramètres)

    def __post_init__(self) -> None:
        if len(self.rows) != len(self.line_numbers):
            raise InternalError(
                "internal.length_mismatch",
                field="line_numbers",
                expected=len(self.rows),
                actual=len(self.line_numbers),
            )
        width = len(self.columns)
        for row, line in zip(self.rows, self.line_numbers, strict=True):
            if len(row) != width:
                raise InternalError(
                    "internal.row_width", line=line, expected=width, actual=len(row)
                )

    @property
    def n(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, eq=False)
class TradeSet:
    """Historique de trades clos, canonique : trié par heure de clôture.

    Conventions :
    - ``profit`` est le résultat net par trade dans la devise du compte
      (commissions et swaps inclus) ;
    - ``direction`` vaut +1 (achat), -1 (vente) ou 0 (inconnu) ;
    - les grandeurs inconnues sont ``NaN`` ; ``known_fields`` dit lesquelles
      étaient réellement présentes dans la source ;
    - ``initial_balance`` peut être inconnu (``None``) : les métriques relatives à
      l'equity sont alors indisponibles, les métriques en devise restent calculables.
    """

    open_time: TimeArray
    close_time: TimeArray
    profit: FloatArray
    direction: Int8Array
    volume: FloatArray
    symbol: StrArray
    open_price: FloatArray
    close_price: FloatArray
    stop_loss: FloatArray
    take_profit: FloatArray
    ticket: IntArray
    currency: str
    initial_balance: float | None
    fingerprint: str
    known_fields: frozenset[str]

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "open_time", _frozen_array(self.open_time, "datetime64[ns]"))
        set_(self, "close_time", _frozen_array(self.close_time, "datetime64[ns]"))
        set_(self, "profit", _frozen_array(self.profit, np.float64))
        set_(self, "direction", _frozen_array(self.direction, np.int8))
        set_(self, "volume", _frozen_array(self.volume, np.float64))
        set_(self, "symbol", _frozen_array(self.symbol, np.str_))
        set_(self, "open_price", _frozen_array(self.open_price, np.float64))
        set_(self, "close_price", _frozen_array(self.close_price, np.float64))
        set_(self, "stop_loss", _frozen_array(self.stop_loss, np.float64))
        set_(self, "take_profit", _frozen_array(self.take_profit, np.float64))
        set_(self, "ticket", _frozen_array(self.ticket, np.int64))
        n = len(self.profit)
        for name in _TRADE_ARRAYS:
            actual = len(getattr(self, name))
            if actual != n:
                raise InternalError(
                    "internal.length_mismatch", field=name, expected=n, actual=actual
                )
        if self.initial_balance is not None and not self.initial_balance > 0:
            raise InternalError("internal.bad_initial_balance", value=self.initial_balance)

    # -- taille et étendue ---------------------------------------------------

    def __len__(self) -> int:
        return len(self.profit)

    @property
    def n(self) -> int:
        return len(self.profit)

    @property
    def span_days(self) -> float:
        """Durée réelle couverte, en jours : du premier ouvert au dernier clos."""
        if self.n == 0:
            return 0.0
        first = self.open_time.min().astype("datetime64[ns]").astype(np.int64)
        last = self.close_time.max().astype("datetime64[ns]").astype(np.int64)
        return float(last - first) / NS_PER_DAY

    @property
    def span_years(self) -> float:
        return self.span_days / DAYS_PER_YEAR

    def has(self, name: str) -> bool:
        """Le champ était-il présent dans la source ?"""
        return name in self.known_fields

    # -- dérivés ---------------------------------------------------------------

    @property
    def cum_profit(self) -> FloatArray:
        return np.cumsum(self.profit, dtype=np.float64)

    @property
    def equity(self) -> FloatArray:
        """Equity après chaque trade. Exige un solde initial connu."""
        if self.initial_balance is None:
            raise InternalError("internal.no_initial_balance")
        return self.initial_balance + self.cum_profit

    def take(self, index: slice | IndexArray | BoolArray) -> TradeSet:
        """Sous-ensemble (nouvel objet ; l'original est intact)."""
        return TradeSet(
            open_time=self.open_time[index],
            close_time=self.close_time[index],
            profit=self.profit[index],
            direction=self.direction[index],
            volume=self.volume[index],
            symbol=self.symbol[index],
            open_price=self.open_price[index],
            close_price=self.close_price[index],
            stop_loss=self.stop_loss[index],
            take_profit=self.take_profit[index],
            ticket=self.ticket[index],
            currency=self.currency,
            initial_balance=self.initial_balance,
            fingerprint=self.fingerprint,
            known_fields=self.known_fields,
        )

    def with_profit(self, profit: FloatArray) -> TradeSet:
        """Même historique avec un autre vecteur de profits (tests d'invariance)."""
        return TradeSet(
            open_time=self.open_time,
            close_time=self.close_time,
            profit=profit,
            direction=self.direction,
            volume=self.volume,
            symbol=self.symbol,
            open_price=self.open_price,
            close_price=self.close_price,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
            ticket=self.ticket,
            currency=self.currency,
            initial_balance=self.initial_balance,
            fingerprint=self.fingerprint,
            known_fields=self.known_fields,
        )


_TRADE_ARRAYS: tuple[str, ...] = (
    "open_time",
    "close_time",
    "profit",
    "direction",
    "volume",
    "symbol",
    "open_price",
    "close_price",
    "stop_loss",
    "take_profit",
    "ticket",
)


@dataclass(frozen=True, eq=False)
class PriceSeries:
    """Série OHLC optionnelle, triée par heure d'ouverture de barre."""

    time: TimeArray
    open: FloatArray
    high: FloatArray
    low: FloatArray
    close: FloatArray
    symbol: str
    fingerprint: str

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "time", _frozen_array(self.time, "datetime64[ns]"))
        for name in ("open", "high", "low", "close"):
            set_(self, name, _frozen_array(getattr(self, name), np.float64))
        n = len(self.time)
        for name in ("open", "high", "low", "close"):
            actual = len(getattr(self, name))
            if actual != n:
                raise InternalError(
                    "internal.length_mismatch", field=name, expected=n, actual=actual
                )
        if n > 1 and bool(np.any(np.diff(self.time.astype(np.int64)) <= 0)):
            raise InternalError("internal.prices_unsorted")

    @property
    def n(self) -> int:
        return len(self.time)

    @property
    def bar_seconds(self) -> float:
        """Durée médiane d'une barre, en secondes (0 si moins de deux barres)."""
        if self.n < 2:
            return 0.0
        diffs = np.diff(self.time.astype(np.int64)).astype(np.float64)
        return float(np.median(diffs)) / 1e9
