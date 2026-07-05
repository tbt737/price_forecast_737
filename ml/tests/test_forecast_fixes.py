"""ML-FIX-1: metric-label correctness (select_candidate) + causal exog imputation
(impute_exog). Pure — no DB/network."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ml.forecast import impute_exog, select_candidate


def test_select_candidate_naive_win_reports_naive_mape() -> None:
    # The label bug: when the best candidate does NOT beat naive by the margin, naive holds
    # — the reported MAPE must be the naive benchmark's, not the losing candidate's.
    used, mape = select_candidate({"ridge_ar": 9.9}, naive_mape=10.0, margin=0.02)
    assert used == "naive"
    assert mape == 10.0  # was buggy: returned 9.9 (ridge_ar's), mislabeling naive's error


def test_select_candidate_winner_reports_its_own_mape() -> None:
    used, mape = select_candidate({"ridge_ar": 5.0, "gbm": 7.0}, naive_mape=10.0, margin=0.02)
    assert used == "ridge_ar" and mape == 5.0


def test_select_candidate_within_margin_keeps_naive() -> None:
    # Beats naive numerically (9.81 < 10.0) but not by >=2% margin ⇒ naive holds, mape == naive's.
    used, mape = select_candidate({"ridge_ar": 9.81}, naive_mape=10.0, margin=0.02)
    assert used == "naive" and mape == 10.0


def test_select_candidate_all_nan_reports_naive() -> None:
    used, mape = select_candidate({"ridge_ar": float("nan")}, naive_mape=8.0, margin=0.02)
    assert used == "naive" and mape == 8.0


def test_impute_exog_is_causal_no_future_leak() -> None:
    # The imputation bug: a full-history median filled leading NaN using FUTURE rows. Causal
    # imputation must make the leading/early fill independent of any future value.
    dates = [date(2026, 1, d) for d in (1, 2, 3, 4)]
    base = pd.DataFrame({"f": [np.nan, np.nan, 100.0, 5.0]}, index=dates)
    future_extreme = pd.DataFrame({"f": [np.nan, np.nan, 100.0, 9_999_999.0]}, index=dates)
    a = impute_exog(base, dates)["f"].tolist()
    b = impute_exog(future_extreme, dates)["f"].tolist()
    assert a[:3] == b[:3]  # a future value cannot change past rows ⇒ no look-ahead leak
    assert a[0] == 0.0 and a[1] == 0.0  # leading NaN (no past) ⇒ neutral 0.0, not a global median


def test_impute_exog_forward_fills_causally() -> None:
    dates = [date(2026, 1, d) for d in (1, 2, 3, 4)]
    df = pd.DataFrame({"f": [10.0, np.nan, np.nan, 40.0]}, index=dates)
    out = impute_exog(df, dates)["f"].tolist()
    assert out == [10.0, 10.0, 10.0, 40.0]  # interior gaps carried forward from last known past value
