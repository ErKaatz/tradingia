import pandas as pd

from src.research.phase25 import add_plateau_metrics, classify_phase25, trade_regime_report


def test_plateau_requires_neighbors_not_single_spike():
    rows = []
    entries = [96, 120, 144]
    exits = [36, 48, 60]
    for e in entries:
        for x in exits:
            rows.append({"entry_lookback": e, "exit_lookback": x, "total_return": 1.0})
    rows[4]["total_return"] = 10.0  # center is an isolated spike
    out = add_plateau_metrics(pd.DataFrame(rows), entries, exits)
    center = out[(out.entry_lookback == 120) & (out.exit_lookback == 48)].iloc[0]
    assert not bool(center.plateau_flag)
    assert center.candidate_vs_neighbor_median == 10.0


def test_plateau_accepts_broad_region():
    entries = [96, 120, 144]
    exits = [36, 48, 60]
    rows = [{"entry_lookback": e, "exit_lookback": x, "total_return": 1.0 + 0.01 * i}
            for i, (e, x) in enumerate((e, x) for e in entries for x in exits)]
    out = add_plateau_metrics(pd.DataFrame(rows), entries, exits)
    center = out[(out.entry_lookback == 120) & (out.exit_lookback == 48)].iloc[0]
    assert bool(center.plateau_flag)


def test_stricter_classifier_rejects_year_inconsistency():
    row = pd.Series({
        "num_trades": 100, "years_evaluated": 7, "positive_years": 3,
        "total_return": 5.0, "plateau_flag": True,
        "excess_return_vs_buy_hold": 1.0, "drawdown_reduction_vs_buy_hold": 30.0,
    })
    label, reason = classify_phase25(row, 1.0)
    assert label == "REJECTED"
    assert "60%" in reason


def test_stricter_classifier_allows_drawdown_advantage_without_excess_return():
    row = pd.Series({
        "num_trades": 100, "years_evaluated": 7, "positive_years": 6,
        "total_return": 5.0, "plateau_flag": True,
        "excess_return_vs_buy_hold": -1.0, "drawdown_reduction_vs_buy_hold": 25.0,
    })
    label, _ = classify_phase25(row, 1.0)
    assert label == "PROMISING BUT UNPROVEN"


def test_trade_regime_uses_entry_timestamp():
    n = 2300
    ts = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "close": pd.Series(range(1, n + 1), dtype=float)})
    trades = pd.DataFrame({
        "entry_time": [ts[-1]],
        "return_pct": [0.05],
    })
    report = trade_regime_report(df, trades)
    assert report.trades.sum() == 1
    assert report.iloc[0].trend_regime == "bull"


def test_phase25_holdout_unlock_is_rejected_before_data_access(tmp_path):
    import yaml
    from src.research.phase25 import run_phase25
    cfg = tmp_path / "bad.yaml"
    cfg.write_text(yaml.safe_dump({"allow_final_holdout_evaluation": True}))
    try:
        run_phase25(cfg, raw_dir=tmp_path / "missing")
        assert False, "expected PermissionError"
    except PermissionError:
        pass
