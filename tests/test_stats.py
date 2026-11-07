# SPDX-License-Identifier: AGPL-3.0-or-later
"""PSR, DSR, courbe de sensibilité, Benjamini-Hochberg — vérifiés contre des
calculs indépendants (bibliothèque standard : ``statistics.NormalDist``)."""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pytest

from qaudit.core.stats import (
    EULER_GAMMA,
    VARIANCE_GIVEN,
    VARIANCE_LO_APPROX,
    benjamini_hochberg,
    dsr,
    dsr_sensitivity,
    expected_max_sharpe,
    lo_variance,
    normal_cdf,
    psr,
)

N = NormalDist()

# Cas calculé à la main (stdlib, hors scipy) : SR = 0,10 par trade, T = 500,
# γ₃ = −0,5, γ₄ = 4, N = 10 essais, V inconnue (Lo).
#   V   = (1 + 0,1²/2)/500                       = 0,00201
#   √V  = 0,044833023542919785
#   Z⁻¹(0,9) = 1,2815515655446008 ; Z⁻¹(1 − 1/(10e)) = 1,7892417645816279
#   SR₀ = √V·[(1−γ)·1,28155 + γ·1,78924]         = 0,07059400271487551
#   dén = √(1 − (−0,5)(0,1) + (4−1)/4·0,01)       = 1,0283481900601568
#   z   = (0,1 − SR₀)·√499 / dén                 = 0,6387721862297612
#   DSR = Φ(z)                                    = 0,7385144276295583
#   PSR(0) = Φ(0,1·√499/dén)                      = 0,9850816470003185
HAND_SR, HAND_T, HAND_SKEW, HAND_KURT, HAND_N = 0.10, 500, -0.5, 4.0, 10
HAND_SR0 = 0.07059400271487551
HAND_DSR = 0.7385144276295583
HAND_PSR0 = 0.9850816470003185


def test_normal_cdf_matches_stdlib() -> None:
    for z in (-3.0, -0.5, 0.0, 0.7, 2.5):
        assert normal_cdf(z) == pytest.approx(N.cdf(z), abs=1e-15)


def test_psr_against_hand_computation() -> None:
    assert psr(HAND_SR, HAND_SKEW, HAND_KURT, HAND_T) == pytest.approx(HAND_PSR0, abs=1e-12)
    # zéro asymétrie, kurtosis normal : PSR = Φ(SR·√(T−1))
    assert psr(0.05, 0.0, 3.0, 101) == pytest.approx(N.cdf(0.05 * 10 / math.sqrt(1 + 0.5 * 0.0025)))


def test_psr_undefined_cases() -> None:
    assert math.isnan(psr(0.1, 0.0, 3.0, 1))
    assert math.isnan(psr(math.nan, 0.0, 3.0, 100))
    assert math.isnan(psr(0.1, math.inf, 3.0, 100))
    # dénominateur non réel : forte asymétrie positive et SR élevé
    assert math.isnan(psr(2.0, 1.0, 1.0, 100))


def test_lo_variance() -> None:
    assert lo_variance(HAND_SR, HAND_T) == pytest.approx(0.00201)
    assert math.isnan(lo_variance(0.1, 1))
    assert math.isnan(lo_variance(math.nan, 100))


def test_expected_max_sharpe_against_hand_computation() -> None:
    assert expected_max_sharpe(HAND_N, 0.00201) == pytest.approx(HAND_SR0, abs=1e-12)
    assert expected_max_sharpe(1, 0.5) == 0.0
    assert expected_max_sharpe(0, 0.5) == 0.0
    assert math.isnan(expected_max_sharpe(10, math.nan))
    assert math.isnan(expected_max_sharpe(10, -1.0))
    # formule recomposée avec la stdlib pour un autre N
    v = 0.003
    z1, z2 = N.inv_cdf(1 - 1 / 50), N.inv_cdf(1 - 1 / (50 * math.e))
    manual = math.sqrt(v) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)
    assert expected_max_sharpe(50, v) == pytest.approx(manual, abs=1e-12)


def test_dsr_against_hand_computation() -> None:
    result = dsr(HAND_SR, HAND_SKEW, HAND_KURT, HAND_T, HAND_N)
    assert result.dsr == pytest.approx(HAND_DSR, abs=1e-12)
    assert result.sr0 == pytest.approx(HAND_SR0, abs=1e-12)
    assert result.var_sr == pytest.approx(0.00201)
    assert result.variance_source == VARIANCE_LO_APPROX
    assert result.n_trials == HAND_N


def test_dsr_with_given_variance() -> None:
    result = dsr(HAND_SR, HAND_SKEW, HAND_KURT, HAND_T, HAND_N, var_sr=0.0005)
    assert result.variance_source == VARIANCE_GIVEN
    assert result.var_sr == 0.0005
    assert result.dsr > HAND_DSR  # variance plus faible → SR₀ plus bas → DSR plus haut


def test_dsr_with_one_trial_equals_psr() -> None:
    assert dsr(HAND_SR, HAND_SKEW, HAND_KURT, HAND_T, 1).dsr == pytest.approx(HAND_PSR0)


def test_sensitivity_curve_is_decreasing_and_reports_tipping_point() -> None:
    curve = dsr_sensitivity(HAND_SR, HAND_SKEW, HAND_KURT, HAND_T, threshold=0.5)
    values = [pt.dsr for pt in curve.points]
    assert [pt.n_trials for pt in curve.points] == [1, 10, 50, 100, 300, 1000]
    assert values == sorted(values, reverse=True)
    assert curve.dsr_at(10) == pytest.approx(HAND_DSR)
    assert math.isnan(curve.dsr_at(7))
    tip = curve.tipping_n_trials
    assert tip is not None
    assert not curve.beyond_grid
    # définition : plus grand N tel que DSR(N) ≥ 0,5
    assert dsr(HAND_SR, HAND_SKEW, HAND_KURT, HAND_T, tip).dsr >= 0.5
    assert dsr(HAND_SR, HAND_SKEW, HAND_KURT, HAND_T, tip + 1).dsr < 0.5


def test_sensitivity_never_significant_gives_zero() -> None:
    # SR négatif : même sans biais de sélection (N = 1), PSR(0) < 0,5
    curve = dsr_sensitivity(-0.1, 0.0, 3.0, 100, threshold=0.5)
    assert curve.tipping_n_trials == 0
    assert curve.dsr_at(1) < 0.5


def test_sensitivity_zero_sharpe_boundary() -> None:
    # SR = 0 : DSR(1) = 0,5 exactement ≥ seuil, DSR(10) < 0,5 → bascule entre 1 et 9
    curve = dsr_sensitivity(0.0, 0.0, 3.0, 100, threshold=0.5)
    assert curve.dsr_at(1) == pytest.approx(0.5)
    assert curve.dsr_at(10) < 0.5
    assert curve.tipping_n_trials == 1


def test_sensitivity_beyond_grid() -> None:
    curve = dsr_sensitivity(1.0, 0.0, 3.0, 10_000, threshold=0.5)
    assert curve.tipping_n_trials is None
    assert curve.beyond_grid


def test_sensitivity_with_nan_sharpe_is_never_significant() -> None:
    curve = dsr_sensitivity(math.nan, 0.0, 3.0, 100, threshold=0.5)
    assert curve.tipping_n_trials == 0
    assert all(math.isnan(pt.dsr) for pt in curve.points)


# ---------------------------------------------------------------------------
# Benjamini-Hochberg
# ---------------------------------------------------------------------------


def test_benjamini_hochberg_textbook_example() -> None:
    # exemple classique : m = 5, p triés 0,01 0,02 0,03 0,04 0,05 ; alpha 0,05
    # ajustés = min_{j≥i}(m·p_(j)/j) = 0,05 pour tous → tous rejetés à 0,05
    p = np.array([0.03, 0.01, 0.05, 0.02, 0.04])
    res = benjamini_hochberg(p, alpha=0.05)
    np.testing.assert_allclose(res.adjusted, [0.05, 0.05, 0.05, 0.05, 0.05])
    assert res.reject.all()
    assert res.n_tests == 5


def test_benjamini_hochberg_partial_rejection() -> None:
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.60])
    res = benjamini_hochberg(p, alpha=0.05)
    # calcul manuel : m=5 ; bruts = 0,005 0,02 0,065 0,05125 0,60 ; step-up :
    # adj_5 = 0,60 ; adj_4 = min(0,05125, 0,60) = 0,05125 ; adj_3 = min(0,065, 0,05125) = 0,05125
    # adj_2 = 0,02 ; adj_1 = 0,005
    np.testing.assert_allclose(res.adjusted, [0.005, 0.02, 0.05125, 0.05125, 0.60])
    assert res.reject.tolist() == [True, True, False, False, False]


def test_benjamini_hochberg_ignores_nan() -> None:
    p = np.array([0.01, math.nan, 0.04])
    res = benjamini_hochberg(p, alpha=0.05)
    assert math.isnan(res.adjusted[1])
    assert not res.reject[1]
    assert res.n_tests == 2
    np.testing.assert_allclose(res.adjusted[[0, 2]], [0.02, 0.04])
    empty = benjamini_hochberg(np.array([math.nan]), alpha=0.05)
    assert empty.n_tests == 0
