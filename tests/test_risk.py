from bellwether import risk
from bellwether.portfolio import Portfolio, Position


def test_risk_ratio_scales_down_in_high_vol():
    calm = risk.scaled_risk_ratio(0.01)
    elevated = risk.scaled_risk_ratio(0.04)
    extreme = risk.scaled_risk_ratio(0.20)
    assert calm == risk.BASE_RISK_RATIO
    assert elevated < calm
    assert extreme == risk.MIN_RISK_RATIO  # clamped at the floor


def test_position_size_formula():
    # capital 100k, 1.5% risk = $1,500 risked; $5 per-unit risk -> 300 units.
    res = risk.position_size(100_000, entry=100.0, stop=95.0, atr_pct=0.01)
    assert res.units == 300
    assert res.per_unit_risk == 5.0
    assert res.risk_capital == 1500.0


def test_position_size_no_leverage_cap():
    # Tiny per-unit risk would imply a huge position; notional is capped to cash.
    res = risk.position_size(10_000, entry=100.0, stop=99.99, atr_pct=0.01)
    assert res.units * 100.0 <= 10_000


def test_position_size_degenerate_stop_is_zero():
    res = risk.position_size(100_000, entry=100.0, stop=100.0, atr_pct=0.01)
    assert res.units == 0


def test_circuit_breaker_threshold():
    assert risk.circuit_breaker_tripped(-0.02)
    assert risk.circuit_breaker_tripped(-0.05)
    assert not risk.circuit_breaker_tripped(-0.0199)
    assert not risk.circuit_breaker_tripped(0.03)


def test_portfolio_open_close_pnl():
    pf = Portfolio(starting_capital=100_000, cash=100_000, day_start_equity=100_000)
    pf.open_position(Position("AAPL", units=100, entry=150.0, stop=145.0, take_profit=160.0, opened="t"))
    assert pf.cash == 100_000 - 15_000
    pnl = pf.close_position("AAPL", exit_price=160.0)
    assert pnl == 1000.0
    assert pf.realized_pnl == 1000.0
    assert "AAPL" not in pf.positions


def test_daily_pnl_pct():
    pf = Portfolio(starting_capital=100_000, cash=100_000, day_start_equity=100_000)
    pf.open_position(Position("AAPL", units=100, entry=150.0, stop=145.0, take_profit=160.0, opened="t"))
    # Price drops to 140 -> equity = 85,000 cash + 14,000 = 99,000 -> -1%.
    assert round(pf.daily_pnl_pct({"AAPL": 140.0}), 4) == -0.01
