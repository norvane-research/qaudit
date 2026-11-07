# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mode lot : N systèmes en parallèle, Benjamini-Hochberg, synthèse (N-04)."""

from __future__ import annotations

import csv
import time
from pathlib import Path

import numpy as np

from qaudit import i18n
from qaudit.core.audit import AuditOptions, run_audit
from qaudit.core.validate import ValidationResult
from qaudit.io.batch import audit_task, run_batch, summarize, write_batch
from qaudit.io.document import loads
from qaudit.io.method import load_method
from qaudit.io.profile import load_profile
from tests.helpers import make_tradeset

FIXTURES = Path(__file__).resolve().parent / "fixtures"
COLUMNS = (
    "ticket",
    "open_time",
    "close_time",
    "symbol",
    "direction",
    "volume",
    "open_price",
    "close_price",
    "sl",
    "tp",
    "profit",
)


def write_system(path: Path, seed: int, n: int, edge: float) -> None:
    """Système synthétique : gains gamma, pertes gamma, taux de réussite ``edge``."""
    rng = np.random.default_rng(seed)
    t = np.datetime64("2021-01-04T08:00:00", "s")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUMNS)
        for i in range(n):
            t = t + np.timedelta64(int(rng.uniform(6, 40) * 3600), "s")
            close = t + np.timedelta64(int(rng.uniform(1, 30) * 3600), "s")
            win = rng.random() < edge
            profit = rng.gamma(4.0, 40.0) if win else -rng.gamma(8.0, 12.5)
            price = 1.1 + rng.normal(0, 0.002)
            writer.writerow(
                [
                    i + 1,
                    str(t).replace("T", " "),
                    str(close).replace("T", " "),
                    "EURUSD",
                    "buy" if rng.random() < 0.5 else "sell",
                    "0.10",
                    f"{price:.5f}",
                    f"{price + 0.001:.5f}",
                    f"{price - 0.005:.5f}",
                    f"{price + 0.006:.5f}",
                    f"{profit:.2f}",
                ]
            )


def test_audit_task_reports_engine_errors_by_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    from qaudit.io.batch import BatchTask

    name, doc, error = audit_task(
        BatchTask("bad", str(bad), None, None, "auto", None, None, AuditOptions(n_iter=200), None)
    )
    assert (name, doc, error) == ("bad", None, "schema.missing_fields")


def test_batch_of_eight_systems_with_bh_correction(tmp_path: Path) -> None:
    paths = []
    for k in range(8):
        edge = 0.55 if k < 3 else 0.40  # trois systèmes avec edge, cinq sans
        path = tmp_path / f"sys{k:02d}.csv"
        write_system(path, seed=100 + k, n=250, edge=edge)
        paths.append(path)
    result = run_batch(paths, options=AuditOptions(seed=5, n_iter=800), jobs=1,
                       initial_balance=10_000.0, alpha=0.05)
    assert not result.errors
    assert len(result.documents) == 8
    summary = result.summary
    assert summary["n_systems"] == 8
    assert summary["n_tests"] == 8
    rows = {r["system"]: r for r in summary["systems"]}
    assert set(rows) == {p.stem for p in paths}
    with_edge = [rows[f"sys{k:02d}"] for k in range(3)]
    without = [rows[f"sys{k:02d}"] for k in range(3, 8)]
    assert all(r["survives_bh"] for r in with_edge)
    assert not any(r["survives_bh"] for r in without)
    # les p ajustées dominent les p brutes et le verdict individuel est inchangé
    for r in summary["systems"]:
        p_raw, p_adj = float(r["null_p_value"]), float(r["null_p_adjusted"])
        assert p_adj >= p_raw
        assert r["decision"] == result.documents[r["system"]]["verdict"]["decision"]
    assert sum(summary["counts"].values()) == 8
    out = write_batch(result, tmp_path / "out", i18n.load("fr"), load_profile("portefeuille"))
    assert out.name == "portfolio.html"
    html = out.read_text(encoding="utf-8")
    assert "Synthèse de portefeuille" in html
    assert "sys00" in html
    assert "sys07" in html
    portfolio = loads((tmp_path / "out" / "portfolio.json").read_text(encoding="utf-8"))
    assert portfolio["schema"] == "qaudit.portfolio"
    for p in paths:
        assert (tmp_path / "out" / "archive" / f"{p.stem}.json").exists()
        assert (tmp_path / "out" / f"{p.stem}.html").exists()


def test_parallel_batch_gives_the_same_documents_as_sequential(tmp_path: Path) -> None:
    paths = []
    for k in range(4):
        path = tmp_path / f"s{k}.csv"
        write_system(path, seed=200 + k, n=200, edge=0.5)
        paths.append(path)
    options = AuditOptions(seed=1, n_iter=500)
    seq = run_batch(paths, options=options, jobs=1, initial_balance=10_000.0, alpha=0.05)
    par = run_batch(list(reversed(paths)), options=options, jobs=4, initial_balance=10_000.0,
                    alpha=0.05)
    assert seq.documents == par.documents
    assert seq.summary == par.summary


def test_summary_of_empty_batch() -> None:
    summary = summarize({}, alpha=0.05)
    assert summary["n_systems"] == 0
    assert summary["systems"] == []


def test_N04_eighty_systems_in_parallel_under_three_minutes(tmp_path: Path) -> None:  # noqa: N802
    """N-04 : 80 systèmes, audit complet (10 000 itérations), en parallèle, < 3 min."""
    paths = []
    rng = np.random.default_rng(0)
    for k in range(80):
        path = tmp_path / f"p{k:02d}.csv"
        write_system(
            path, seed=1000 + k, n=int(rng.integers(300, 700)), edge=float(rng.uniform(0.38, 0.55))
        )
        paths.append(path)
    start = time.perf_counter()
    result = run_batch(paths, options=AuditOptions(seed=7), jobs=8, initial_balance=10_000.0,
                       alpha=0.05)
    elapsed = time.perf_counter() - start
    assert not result.errors
    assert len(result.documents) == 80
    assert result.summary["n_tests"] == 80
    assert elapsed < 180.0, f"{elapsed:.1f} s"


def test_N03_full_audit_1000_trades_10000_iterations_under_8_seconds(  # noqa: N802
    tmp_path: Path,
) -> None:
    """N-03 : audit complet (validation, détecteurs, bootstrap par blocs,
    permutation, nulle, régimes) sur 1 000 trades et 10 000 itérations < 8 s.
    Mesure réelle, jamais ajustée : si le budget est dépassé, le test le dit."""
    rng = np.random.default_rng(3)
    profits = np.where(rng.random(1000) < 0.47, rng.gamma(4.0, 42.5, 1000),
                       -rng.gamma(8.0, 12.5, 1000))
    ts = make_tradeset(profits, step_hours=20.0, stop_loss=np.full(1000, 1.09))
    validation = ValidationResult(ts, (), None)
    config = load_method()
    start = time.perf_counter()
    result = run_audit(validation, config, AuditOptions(seed=1, n_iter=10_000))
    elapsed = time.perf_counter() - start
    assert result.n_iter == 10_000
    assert result.metrics.n == 1000
    assert elapsed < 8.0, f"audit complet en {elapsed:.2f} s (budget N-03 : 8 s)"
