# SPDX-License-Identifier: AGPL-3.0-or-later
"""Génère les fixtures dorées (CSV) de façon déterministe.

Exécuter : ``python tests/fixtures/generate.py``. Les fichiers produits sont
versionnés ; ce script documente comment chaque dossier a été truqué (ou pas).
Toute modification ici doit être suivie d'une régénération et d'une relecture
des verdicts attendus dans ``tests/test_golden.py``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
COLUMNS = (
    "ticket", "open_time", "close_time", "symbol", "direction", "volume",
    "open_price", "close_price", "sl", "tp", "profit",
)
START = np.datetime64("2021-01-04T08:00:00")
PIP = 0.0001
LOT_VALUE = 100_000.0  # 1 lot EURUSD = 100 000 unités → 1 pip = 10 $ par lot


@dataclass
class Trade:
    open_ns: int
    close_ns: int
    direction: int
    volume: float
    open_price: float
    profit: float
    sl: float | None
    symbol: str = "EURUSD"

    def row(self, ticket: int) -> list[str]:
        move = self.profit / (self.volume * LOT_VALUE)  # variation de prix
        close_price = self.open_price + self.direction * move
        tp = self.open_price + self.direction * 60 * PIP
        return [
            str(ticket),
            _iso(self.open_ns),
            _iso(self.close_ns),
            self.symbol,
            "buy" if self.direction > 0 else "sell",
            f"{self.volume:.2f}",
            f"{self.open_price:.5f}",
            f"{close_price:.5f}",
            "" if self.sl is None else f"{self.sl:.5f}",
            f"{tp:.5f}",
            f"{self.profit:.2f}",
        ]


def _iso(ns: int) -> str:
    return str(np.datetime64(int(ns) // 1_000_000_000, "s")).replace("T", " ")


def _hours(h: float) -> int:
    return round(h * 3_600_000_000_000)


def write(name: str, trades: list[Trade], folder: Path | None = None) -> None:
    trades.sort(key=lambda t: (t.close_ns, t.open_ns))
    path = (folder or HERE) / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator=chr(10))
        writer.writerow(COLUMNS)
        for i, t in enumerate(trades, start=1):
            writer.writerow(t.row(i))


def price_walk(rng: np.random.Generator, n: int) -> np.ndarray:
    return 1.1000 + np.cumsum(rng.normal(0.0, 8 * PIP, n))


# ---------------------------------------------------------------------------
# 1. témoin sain : edge réel modeste, iid, stops, volume constant, quelques
#    positions concurrentes (qui ne sont PAS une grille)
# ---------------------------------------------------------------------------


def healthy_witness() -> list[Trade]:
    rng = np.random.default_rng(101)
    n = 600
    gaps_h = rng.exponential(1.8 * 24, n)
    opens = START.astype("datetime64[ns]").astype(np.int64) + np.cumsum(
        np.array([_hours(g) for g in gaps_h])
    )
    prices = price_walk(rng, n)
    trades = []
    for i in range(n):
        direction = 1 if rng.random() < 0.5 else -1
        hold = rng.uniform(4, 30)
        win = rng.random() < 0.47
        profit = rng.gamma(4.0, 42.5) if win else -rng.gamma(8.0, 12.5)
        sl = prices[i] - direction * 50 * PIP
        trades.append(Trade(int(opens[i]), int(opens[i]) + _hours(hold), direction, 0.10,
                            float(prices[i]), round(float(profit), 2), float(sl)))
    return trades


# ---------------------------------------------------------------------------
# 2. martingale : volume doublé après chaque perte, remis à 0,01 après un gain
# ---------------------------------------------------------------------------


def martingale() -> list[Trade]:
    rng = np.random.default_rng(202)
    n = 600
    t = START.astype("datetime64[ns]").astype(np.int64)
    prices = price_walk(rng, n)
    volume = 0.01
    trades = []
    for i in range(n):
        t += _hours(rng.uniform(6, 30))
        direction = 1 if rng.random() < 0.5 else -1
        units = volume / 0.01
        win = rng.random() < 0.75
        profit = 15.0 * units if win else -40.0 * units
        trades.append(Trade(t, t + _hours(rng.uniform(1, 12)), direction, volume,
                            float(prices[i]), round(profit, 2), None))
        volume = 0.01 if win else min(volume * 2, 0.64)
    return trades


# ---------------------------------------------------------------------------
# 3. grille : ajouts de même sens à prix pire, volume ×1,5, clôture en panier
# ---------------------------------------------------------------------------


def grid() -> list[Trade]:
    rng = np.random.default_rng(303)
    t = START.astype("datetime64[ns]").astype(np.int64)
    price = 1.1000
    trades: list[Trade] = []
    while len(trades) < 600:
        levels = int(rng.choice([1, 2, 3, 4, 5], p=[0.40, 0.25, 0.15, 0.10, 0.10]))
        direction = 1 if rng.random() < 0.5 else -1
        opens = []
        volume = 0.10
        entry = price
        for _level in range(levels):
            t += _hours(rng.uniform(2, 8))
            opens.append((t, entry, volume))
            entry = entry - direction * 20 * PIP  # le prix va contre la position
            volume = round(volume * 1.5, 2)
        close_t = t + _hours(rng.uniform(3, 10))
        stopped_out = levels == 5 and rng.random() < 0.5
        if stopped_out:
            exit_price = entry - direction * 30 * PIP
        else:
            avg = sum(p * v for _, p, v in opens) / sum(v for _, _, v in opens)
            exit_price = avg + direction * 10 * PIP
        for open_t, open_p, vol in opens:
            profit = direction * (exit_price - open_p) * vol * LOT_VALUE
            trades.append(Trade(open_t, close_t, direction, vol, open_p, round(profit, 2), None))
        price = exit_price + rng.normal(0, 15 * PIP)
        t = close_t
    return trades[:600]


# ---------------------------------------------------------------------------
# 4. sans stop, asymétrie extrême : 96 % de petits gains, pertes 12× plus grosses
# ---------------------------------------------------------------------------


def no_stop_asymmetry() -> list[Trade]:
    rng = np.random.default_rng(404)
    n = 500
    t = START.astype("datetime64[ns]").astype(np.int64)
    prices = price_walk(rng, n)
    trades = []
    for i in range(n):
        t += _hours(rng.uniform(8, 40))
        direction = 1 if rng.random() < 0.5 else -1
        win = rng.random() < 0.96
        profit = rng.uniform(8, 16) if win else -rng.uniform(120, 180)
        trades.append(Trade(t, t + _hours(rng.uniform(2, 48)), direction, 0.10,
                            float(prices[i]), round(float(profit), 2), None))
    return trades


# ---------------------------------------------------------------------------
# 5. bruit sans edge : profits N(0, 100), stops présents, volume constant
# ---------------------------------------------------------------------------


def no_edge_noise() -> list[Trade]:
    rng = np.random.default_rng(505)
    n = 500
    t = START.astype("datetime64[ns]").astype(np.int64)
    prices = price_walk(rng, n)
    trades = []
    for i in range(n):
        t += _hours(rng.uniform(8, 40))
        direction = 1 if rng.random() < 0.5 else -1
        profit = rng.normal(0.0, 100.0)
        sl = prices[i] - direction * 50 * PIP
        trades.append(Trade(t, t + _hours(rng.uniform(2, 30)), direction, 0.10,
                            float(prices[i]), round(float(profit), 2), float(sl)))
    return trades


# ---------------------------------------------------------------------------
# 6. ruine : compte de 5 000, série de pertes qui met l'equity à zéro
# ---------------------------------------------------------------------------


def ruined() -> list[Trade]:
    rng = np.random.default_rng(606)
    n = 200
    t = START.astype("datetime64[ns]").astype(np.int64)
    prices = price_walk(rng, n)
    trades = []
    for i in range(n):
        t += _hours(rng.uniform(8, 30))
        direction = 1 if rng.random() < 0.5 else -1
        if i < 100:
            profit = rng.normal(15.0, 60.0)
        elif i < 130:
            profit = -rng.uniform(150, 260)  # 30 pertes ≈ −6 150 : ruine certaine
        else:
            profit = rng.normal(10.0, 60.0)
        sl = prices[i] - direction * 50 * PIP
        trades.append(Trade(t, t + _hours(rng.uniform(2, 30)), direction, 0.10,
                            float(prices[i]), round(float(profit), 2), float(sl)))
    return trades


FIXTURES = {
    "healthy_witness": healthy_witness,
    "martingale": martingale,
    "grid": grid,
    "no_stop_asymmetry": no_stop_asymmetry,
    "no_edge_noise": no_edge_noise,
    "ruined": ruined,
}


def main() -> None:
    for name, builder in FIXTURES.items():
        write(name, builder())
    main_extra()
    main_formats()
    main_borderline()
    main_tester()


def main_tester() -> None:
    """Rapport du Strategy Tester (HTML UTF-16 + Open XML) construit depuis le témoin."""
    import sys

    sys.path.insert(0, str(HERE.parents[1]))  # exécution directe : rendre « tests » importable
    from tests.fixtures.tester_fixture import write_tester

    write_tester(HERE, healthy_witness())


def main_mt4() -> None:
    """Rapport détaillé MT4 (windows-1252) construit depuis le témoin."""
    import sys

    sys.path.insert(0, str(HERE.parents[1]))
    from tests.fixtures.mt4_fixture import write_mt4

    write_mt4(HERE, healthy_witness())


# ---------------------------------------------------------------------------
# séries de prix : barres horaires cohérentes avec les trades (le prix
# d'ouverture et de clôture de chaque trade tombe dans la fourchette de sa barre)
# ---------------------------------------------------------------------------

HOUR_NS = 3_600_000_000_000


def _exit_price(t: Trade) -> float:
    return t.open_price + t.direction * t.profit / (t.volume * LOT_VALUE)


def build_bars(trades: list[Trade], seed: int) -> list[list[str]]:
    """Barres horaires construites AUTOUR des trades : le chemin de clôture
    interpole les prix d'entrée et de sortie (points d'ancrage) avec un bruit
    modeste ; chaque prix de trade tombe strictement à l'intérieur de sa barre
    (marge aléatoire de 1 à 6 pips : un système honnête n'entre pas sur
    l'extrême exact)."""
    rng = np.random.default_rng(seed)
    start = min(t.open_ns for t in trades) // HOUR_NS * HOUR_NS - HOUR_NS
    end = max(t.close_ns for t in trades) // HOUR_NS * HOUR_NS + 2 * HOUR_NS
    n = int((end - start) // HOUR_NS)
    anchors: dict[int, list[float]] = {}
    for t in trades:
        anchors.setdefault(int((t.open_ns - start) // HOUR_NS), []).append(t.open_price)
        anchors.setdefault(int((t.close_ns - start) // HOUR_NS), []).append(_exit_price(t))
    idx = np.array(sorted(anchors))
    vals = np.array([float(np.mean(anchors[i])) for i in idx])
    close = np.interp(np.arange(n), idx, vals) + rng.normal(0.0, 2 * PIP, n)
    open_ = np.concatenate(([close[0]], close[:-1]))
    high = np.maximum(open_, close) + np.abs(rng.normal(0.0, 2 * PIP, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.0, 2 * PIP, n))
    for t in trades:
        for bar, price in ((int((t.open_ns - start) // HOUR_NS), t.open_price),
                           (int((t.close_ns - start) // HOUR_NS), _exit_price(t))):
            margin = rng.uniform(1, 6) * PIP
            high[bar] = max(high[bar], price + margin)
            low[bar] = min(low[bar], price - margin)
    return [
        [_iso(start + k * HOUR_NS), f"{open_[k]:.5f}", f"{high[k]:.5f}", f"{low[k]:.5f}",
         f"{close[k]:.5f}"]
        for k in range(n)
    ]


def write_bars(name: str, rows: list[list[str]]) -> None:
    path = HERE / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator=chr(10))
        writer.writerow(("time", "open", "high", "low", "close"))
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# 7. look-ahead : chaque entrée est au plus bas exact (achat) ou au plus haut
#    exact (vente) de sa barre horaire — impossible sans connaître l'avenir
# ---------------------------------------------------------------------------


def lookahead() -> tuple[list[Trade], list[list[str]]]:
    rng = np.random.default_rng(707)
    n = 400
    t = START.astype("datetime64[ns]").astype(np.int64)
    prices = price_walk(rng, n)
    trades: list[Trade] = []
    for i in range(n):
        t += _hours(rng.uniform(8, 30))
        direction = 1 if rng.random() < 0.5 else -1
        hold = rng.uniform(2, 20)
        profit = rng.normal(40.0, 60.0)
        trades.append(Trade(t, t + _hours(hold), direction, 0.10, float(prices[i]),
                            round(float(profit), 2), None))
    rows = build_bars(trades, 708)
    start = min(tr.open_ns for tr in trades) // HOUR_NS * HOUR_NS - HOUR_NS
    for tr in trades:
        i = int((tr.open_ns - start) // HOUR_NS)
        low, high = float(rows[i][3]), float(rows[i][2])
        tr.open_price = low if tr.direction > 0 else high  # le truquage
        j = int((tr.close_ns - start) // HOUR_NS)
        exit_price = _exit_price(tr)
        rows[j][2] = f"{max(float(rows[j][2]), exit_price + 2 * PIP):.5f}"
        rows[j][3] = f"{min(float(rows[j][3]), exit_price - 2 * PIP):.5f}"
    return trades, rows


# ---------------------------------------------------------------------------
# candidats walk-forward du témoin sain : la stratégie A est le témoin lui-même,
# B et C sont des jeux de paramètres moins bons (taux de réussite plus faible)
# ---------------------------------------------------------------------------


def witness_variant(seed: int, win_rate: float) -> list[Trade]:
    rng = np.random.default_rng(seed)
    n = 600
    gaps_h = rng.exponential(1.8 * 24, n)
    opens = START.astype("datetime64[ns]").astype(np.int64) + np.cumsum(
        np.array([_hours(g) for g in gaps_h])
    )
    prices = price_walk(rng, n)
    trades = []
    for i in range(n):
        direction = 1 if rng.random() < 0.5 else -1
        hold = rng.uniform(4, 30)
        win = rng.random() < win_rate
        profit = rng.gamma(4.0, 42.5) if win else -rng.gamma(8.0, 12.5)
        sl = prices[i] - direction * 50 * PIP
        trades.append(Trade(int(opens[i]), int(opens[i]) + _hours(hold), direction, 0.10,
                            float(prices[i]), round(float(profit), 2), float(sl)))
    return trades


def main_extra() -> None:
    witness = healthy_witness()
    write_bars("healthy_witness_prices", build_bars(witness, 111))
    la_trades, la_bars = lookahead()
    write("lookahead", la_trades)
    write_bars("lookahead_prices", la_bars)
    wf_dir = HERE / "walkforward" / "healthy_witness"
    wf_dir.mkdir(parents=True, exist_ok=True)
    write("A", witness, wf_dir)
    write("B", witness_variant(112, 0.45), wf_dir)
    write("C", witness_variant(113, 0.42), wf_dir)


# ---------------------------------------------------------------------------
# formats réels : CSV MT5 (positions), rapport HTML MT5, table des profits Deriv,
# CSV à colonnes exotiques (porte E1)
# ---------------------------------------------------------------------------


def _mt5_rows(trades: list[Trade]) -> list[list[str]]:
    rows = []
    for i, t in enumerate(sorted(trades, key=lambda x: (x.close_ns, x.open_ns)), start=1):
        exit_price = _exit_price(t)
        rows.append([
            _iso(t.open_ns).replace("-", "."), str(100000 + i), t.symbol,
            "buy" if t.direction > 0 else "sell", f"{t.volume:.2f}", f"{t.open_price:.5f}",
            "" if t.sl is None else f"{t.sl:.5f}", f"{t.open_price + t.direction * 60 * PIP:.5f}",
            _iso(t.close_ns).replace("-", "."), f"{exit_price:.5f}", "-0.70", "0.00",
            f"{t.profit + 0.70:.2f}",
        ])
    return rows


MT5_HEADER = ["Time", "Position", "Symbol", "Type", "Volume", "Price", "S / L", "T / P", "Time",
              "Price", "Commission", "Swap", "Profit"]


def write_mt5_csv(trades: list[Trade]) -> None:
    path = HERE / "mt5_positions.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator=chr(10))
        writer.writerow(MT5_HEADER)
        writer.writerow(["2021.01.04 00:00:00", "1", "", "balance", "", "", "", "", "", "", "", "",
                         "10 000.00"])
        writer.writerows(_mt5_rows(trades))


def write_mt5_html(trades: list[Trade]) -> None:
    rows = _mt5_rows(trades)
    cells = "".join(f"<td>{c}</td>" for c in MT5_HEADER)
    body = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    html = (
        "<html><head><meta charset='utf-8'><title>Trade History Report</title></head><body>\n"
        "<table><tr><th colspan='13'>Trade History Report</th></tr>\n"
        "<tr><td>Name:</td><td>Demo Trader</td><td>Account:</td><td>12345 (USD, Demo)</td></tr>\n"
        "<tr><td>Currency:</td><td>USD</td><td>Leverage:</td><td>1:100</td></tr>\n"
        "<tr><th colspan='13'>Positions</th></tr>\n"
        f"<tr>{cells}</tr>\n{body}\n"
        "<tr><td colspan='13'></td></tr>\n"
        "<tr><th colspan='13'>Deals</th></tr>\n"
        "<tr><td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td>"
        "<td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td>"
        "<td>Profit</td><td>Balance</td><td>Comment</td></tr>\n"
        "<tr><td>2021.01.04 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td></td>"
        "<td></td><td></td><td>0.00</td><td>0.00</td><td>10 000.00</td><td>10 000.00</td>"
        "<td>Deposit</td></tr>\n"
        "</table></body></html>\n"
    )
    (HERE / "mt5_report.html").write_text(html, encoding="utf-8", newline=chr(10))


def write_deriv(trades: list[Trade]) -> None:
    path = HERE / "deriv_profit_table.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator=chr(10))
        writer.writerow(["Ref. ID", "Contract", "Market", "Buy time", "Buy price", "Sell time",
                         "Sell price", "Profit/Loss"])
        for i, t in enumerate(sorted(trades, key=lambda x: (x.close_ns, x.open_ns)), start=1):
            stake = 10.0
            payout = round(stake + t.profit / 10.0, 2)
            writer.writerow([f"{500000 + i}", "Rise/Fall", "Volatility 75 Index",
                             _iso(t.open_ns), f"{stake:.2f}", _iso(t.close_ns), f"{payout:.2f}",
                             f"{payout - stake:.2f}"])


def write_exotic(trades: list[Trade]) -> None:
    path = HERE / "exotic_columns.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator=chr(10))
        writer.writerow(["Instrument", "Sens", "Lots", "Ouverture", "Fermeture", "Résultat net"])
        for t in sorted(trades, key=lambda x: (x.close_ns, x.open_ns)):
            writer.writerow([t.symbol, "Achat" if t.direction > 0 else "Vente", f"{t.volume:.2f}",
                             _iso(t.open_ns), _iso(t.close_ns),
                             f"{t.profit:.2f}".replace(".", ",")])


def main_formats() -> None:
    witness = healthy_witness()
    write_mt5_csv(witness)
    write_mt5_html(witness)
    write_deriv(witness)
    write_exotic(witness)


# ---------------------------------------------------------------------------
# 8. dossier en bande d'indécision (porte E3) : les trades du témoin sain, dans
#    un ordre choisi pour que le drawdown observé tombe vers le 6ᵉ centile des
#    permutations — la barrière « centile du drawdown » (NO-GO < 5, bande 3-8)
#    passe mais reste dans la bande : verdict rendu avec revue_humaine = true
# ---------------------------------------------------------------------------


def borderline() -> list[Trade]:
    trades = healthy_witness()
    trades.sort(key=lambda t: (t.close_ns, t.open_ns))
    profits = np.array([t.profit for t in trades])
    rng = np.random.default_rng(808)
    perms = np.array([rng.permutation(profits.size) for _ in range(4000)])
    cum = np.cumsum(profits[perms], axis=1)
    peak = np.maximum.accumulate(np.maximum(cum, 0.0), axis=1)
    dd = np.max(peak - cum, axis=1)
    order = np.argsort(dd)
    chosen = perms[order[int(0.06 * dd.size)]]
    reordered = profits[chosen]
    for t, p in zip(trades, reordered.tolist(), strict=True):
        t.profit = p
    return trades


def main_borderline() -> None:
    write("borderline", borderline())


if __name__ == "__main__":
    main()
