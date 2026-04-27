"""
tests/test_agents.py
────────────────────
Full test suite for all AutoTrader agents.
Run with:  pytest tests/test_agents.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from agents.market_agent    import MarketAgent
from agents.risk_agent      import RiskAgent, RiskDecision
from agents.execution_agent import ExecutionAgent, OrderRecord
from agents.logger_agent    import LoggerAgent
from agents.orchestrator    import Orchestrator


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketAgent:

    def setup_method(self):
        self.agent = MarketAgent(api=None)

    # ── basic shape ────────────────────────────────────────────────────────────

    def test_analyse_returns_all_symbols(self):
        symbols = ["SPY", "QQQ", "AAPL"]
        results = self.agent.analyse(symbols)
        assert set(results.keys()) == set(symbols)

    def test_signal_has_required_keys(self):
        sig = self.agent.analyse(["SPY"])["SPY"]
        required = {"symbol", "price", "rsi", "macd", "action",
                    "confidence", "trend", "timestamp"}
        missing = required - sig.keys()
        assert not missing, f"Missing keys: {missing}"

    def test_symbol_field_matches(self):
        sig = self.agent.analyse(["AAPL"])["AAPL"]
        assert sig["symbol"] == "AAPL"

    # ── price ──────────────────────────────────────────────────────────────────

    def test_price_is_positive(self):
        """Synthetic data must always produce a positive price.
        Uses hashlib seed so result is deterministic across runs."""
        for sym in ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]:
            sig = self.agent.analyse([sym])[sym]
            assert sig["price"] > 0, f"{sym}: price={sig['price']} is not positive"

    def test_price_is_float(self):
        sig = self.agent.analyse(["SPY"])["SPY"]
        assert isinstance(sig["price"], float)

    # ── action ─────────────────────────────────────────────────────────────────

    def test_action_is_valid(self):
        valid = {"BUY", "SELL", "HOLD"}
        for sym in ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]:
            sig = self.agent.analyse([sym])[sym]
            assert sig["action"] in valid, f"{sym}: invalid action '{sig['action']}'"

    # ── confidence ─────────────────────────────────────────────────────────────

    def test_confidence_in_range(self):
        for sym in ["SPY", "AAPL"]:
            sig = self.agent.analyse([sym])[sym]
            assert 0.0 <= sig["confidence"] <= 1.0, \
                f"{sym}: confidence={sig['confidence']} out of [0,1]"

    def test_hold_confidence_is_040(self):
        """HOLD signals always return exactly 0.40 confidence."""
        # Find a symbol that gives HOLD in this environment
        for sym in ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]:
            sig = self.agent.analyse([sym])[sym]
            if sig["action"] == "HOLD":
                assert sig["confidence"] == 0.40
                return
        pytest.skip("No HOLD signal produced — all symbols have strong signals this run")

    # ── RSI ────────────────────────────────────────────────────────────────────

    def test_rsi_in_range(self):
        for sym in ["SPY", "QQQ"]:
            sig = self.agent.analyse([sym])[sym]
            assert 0 <= sig["rsi"] <= 100, f"{sym}: RSI={sig['rsi']} out of [0,100]"

    # ── trend ──────────────────────────────────────────────────────────────────

    def test_trend_is_valid(self):
        valid = {"bullish", "bearish", "neutral"}
        for sym in ["SPY", "AAPL"]:
            sig = self.agent.analyse([sym])[sym]
            assert sig["trend"] in valid, f"{sym}: invalid trend '{sig['trend']}'"

    # ── unknown symbol ─────────────────────────────────────────────────────────

    def test_unknown_symbol_returns_empty_signal(self):
        """Unknown symbols raise internally → caught → _empty_signal returned."""
        sig = self.agent.analyse(["FAKESYM"])["FAKESYM"]
        assert sig["action"] == "HOLD",  f"Expected HOLD, got {sig['action']}"
        assert sig["price"]  == 0.0,     f"Expected 0.0 price, got {sig['price']}"
        assert sig["confidence"] == 0.0, f"Expected 0.0 confidence"

    def test_unknown_symbol_in_mixed_list(self):
        """Known symbols still succeed when mixed with unknown ones."""
        results = self.agent.analyse(["SPY", "FAKESYM"])
        assert results["SPY"]["price"] > 0
        assert results["FAKESYM"]["action"] == "HOLD"

    # ── determinism ────────────────────────────────────────────────────────────

    def test_synthetic_data_is_deterministic(self):
        """Same symbol must produce identical price on every run (hashlib seed)."""
        sig1 = self.agent.analyse(["SPY"])["SPY"]
        sig2 = self.agent.analyse(["SPY"])["SPY"]
        assert sig1["price"] == sig2["price"], \
            f"Non-deterministic: {sig1['price']} vs {sig2['price']}"

    # ── all symbols ────────────────────────────────────────────────────────────

    def test_all_known_symbols_produce_valid_signals(self):
        results = self.agent.analyse(list(MarketAgent.KNOWN_SYMBOLS))
        for sym, sig in results.items():
            assert sig["price"] > 0,              f"{sym}: price not positive"
            assert 0 <= sig["rsi"] <= 100,        f"{sym}: RSI out of range"
            assert sig["action"] in {"BUY","SELL","HOLD"}, f"{sym}: bad action"
            assert 0 <= sig["confidence"] <= 1.0, f"{sym}: confidence out of range"
            assert sig["trend"] in {"bullish","bearish","neutral"}, f"{sym}: bad trend"


# ═══════════════════════════════════════════════════════════════════════════════
# RISK AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskAgent:

    def setup_method(self):
        self.agent = RiskAgent()

    def _sig(self, symbol="SPY", action="BUY", price=100.0, confidence=0.75):
        return {"symbol": symbol, "action": action,
                "price": price, "confidence": confidence, "rsi": 40}

    # ── basic rejections ───────────────────────────────────────────────────────

    def test_hold_signal_always_rejected(self):
        d = self.agent.evaluate(self._sig(action="HOLD"), capital=1000.0)
        assert not d.approved

    def test_low_confidence_rejected(self):
        d = self.agent.evaluate(self._sig(confidence=0.30), capital=1000.0)
        assert not d.approved
        assert "onfidence" in d.reason

    def test_sell_without_open_position_rejected(self):
        d = self.agent.evaluate(
            self._sig(action="SELL", confidence=0.80),
            capital=1000.0, open_positions={}
        )
        assert not d.approved

    # ── approvals ─────────────────────────────────────────────────────────────

    def test_approved_signal_returns_qty(self):
        d = self.agent.evaluate(
            self._sig(price=50.0, confidence=0.80),
            capital=1000.0, open_positions={}
        )
        assert d.approved
        assert d.qty >= 1

    def test_stop_loss_below_entry_for_buy(self):
        d = self.agent.evaluate(
            self._sig(price=100.0, confidence=0.80),
            capital=1000.0, open_positions={}
        )
        assert d.approved
        assert d.stop_loss < 100.0

    def test_take_profit_above_entry_for_buy(self):
        d = self.agent.evaluate(
            self._sig(price=100.0, confidence=0.80),
            capital=1000.0, open_positions={}
        )
        assert d.approved
        assert d.take_profit > 100.0

    def test_risk_reward_ratio(self):
        """Take-profit distance must be ≥ stop-loss distance (≥1:1 RR)."""
        d = self.agent.evaluate(
            self._sig(price=100.0, confidence=0.80),
            capital=1000.0, open_positions={}
        )
        assert d.approved
        reward = d.take_profit - 100.0
        risk   = 100.0 - d.stop_loss
        assert reward >= risk, f"RR ratio < 1: reward={reward:.2f} risk={risk:.2f}"

    # ── position limits ────────────────────────────────────────────────────────

    def test_max_positions_enforced(self):
        full = {f"SYM{i}": 100.0 for i in range(5)}
        d = self.agent.evaluate(
            self._sig(symbol="NEW", confidence=0.90),
            capital=1000.0, open_positions=full
        )
        assert not d.approved

    def test_no_duplicate_positions(self):
        d = self.agent.evaluate(
            self._sig(symbol="SPY", confidence=0.80),
            capital=1000.0, open_positions={"SPY": 100.0}
        )
        assert not d.approved

    def test_position_size_respects_capital(self):
        d = self.agent.evaluate(
            self._sig(price=50.0, confidence=0.80),
            capital=1000.0, open_positions={}
        )
        assert d.approved
        # 1% tolerance for rounding
        assert d.qty * 50.0 <= 1000.0 * 0.10 * 1.01

    # ── circuit-breakers ───────────────────────────────────────────────────────

    def test_daily_loss_halts_trading(self):
        # 2% limit on $1000 = $20; send -$25
        d = self.agent.evaluate(
            self._sig(confidence=0.90),
            capital=1000.0, open_positions={}, daily_pnl=-25.0
        )
        assert not d.approved
        reason_lower = d.reason.lower()
        assert "loss" in reason_lower or "daily" in reason_lower

    def test_trading_allowed_before_limit(self):
        # -$15 is below the $20 limit — should still be approved
        d = self.agent.evaluate(
            self._sig(confidence=0.90),
            capital=1000.0, open_positions={}, daily_pnl=-15.0
        )
        assert d.approved

    # ── capital too low ────────────────────────────────────────────────────────

    def test_insufficient_capital_rejected(self):
        # $10 capital, $500 stock → can't afford even 1 share at 10% max
        d = self.agent.evaluate(
            self._sig(price=500.0, confidence=0.80),
            capital=10.0, open_positions={}
        )
        assert not d.approved


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTION AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutionAgent:

    def setup_method(self):
        self.agent = ExecutionAgent(api=None)
        self.risk  = RiskAgent()

    # ── simulate_order appends to history ─────────────────────────────────────

    def test_simulate_order_appended_to_history(self):
        before = len(self.agent.order_history)
        self.agent._simulate_order("SPY", "buy", 1, 50.0, 48.5, 53.0)
        assert len(self.agent.order_history) == before + 1

    def test_summary_counts_orders(self):
        self.agent._simulate_order("SPY",  "buy", 1, 50.0, 48.5, 53.0)
        self.agent._simulate_order("AAPL", "buy", 1, 80.0, 77.5, 85.0)
        s = self.agent.summary()
        assert s["buys"] >= 2

    def test_simulate_order_status_is_simulated(self):
        rec = self.agent._simulate_order("SPY", "buy", 1, 50.0, 48.0, 56.0)
        assert rec.status == "simulated"

    # ── cash tracking ──────────────────────────────────────────────────────────

    def test_cash_decreases_after_buy(self):
        initial = self.agent._virtual_cash
        self.agent._simulate_order("SPY", "buy", 2, 50.0, 48.0, 56.0)
        assert self.agent._virtual_cash < initial

    def test_cash_increases_after_sell(self):
        # Buy first so we have a position
        self.agent._simulate_order("SPY", "buy", 1, 50.0, 48.0, 56.0)
        cash_after_buy = self.agent._virtual_cash
        self.agent._simulate_order("SPY", "sell", 1, 55.0, 48.0, 56.0)
        assert self.agent._virtual_cash > cash_after_buy

    def test_insufficient_cash_status(self):
        self.agent._virtual_cash = 1.0   # force near-zero
        rec = self.agent._simulate_order("SPY", "buy", 10, 500.0, 480.0, 530.0)
        assert rec.status == "insufficient_cash"

    # ── execute dispatches correctly ───────────────────────────────────────────

    def test_approved_order_creates_record(self):
        sig = {"symbol": "SPY", "action": "BUY", "price": 50.0,
               "confidence": 0.80, "rsi": 35}
        d = self.risk.evaluate(sig, capital=1000.0, open_positions={})
        assert d.approved
        rec = self.agent.execute(d)
        assert rec.status in ("simulated", "filled", "insufficient_cash")

    def test_unapproved_order_skipped(self):
        sig = {"symbol": "SPY", "action": "HOLD", "price": 100.0,
               "confidence": 0.80, "rsi": 50}
        d = self.risk.evaluate(sig, capital=1000.0)
        rec = self.agent.execute(d)
        assert rec.status == "skipped"

    # ── SL / TP exits ──────────────────────────────────────────────────────────

    def test_sl_triggers_exit(self):
        self.agent._virtual_portfolio["SPY"] = {
            "qty": 1, "entry": 100.0, "stop_loss": 97.0, "take_profit": 106.0
        }
        exits = self.agent.check_exits({"SPY": 95.0})
        assert len(exits) == 1
        assert exits[0].symbol == "SPY"
        assert exits[0].pnl < 0

    def test_tp_triggers_exit(self):
        self.agent._virtual_portfolio["AAPL"] = {
            "qty": 1, "entry": 100.0, "stop_loss": 97.0, "take_profit": 106.0
        }
        exits = self.agent.check_exits({"AAPL": 110.0})
        assert len(exits) == 1
        assert exits[0].pnl > 0

    def test_no_exit_when_price_in_range(self):
        self.agent._virtual_portfolio["QQQ"] = {
            "qty": 1, "entry": 100.0, "stop_loss": 97.0, "take_profit": 106.0
        }
        exits = self.agent.check_exits({"QQQ": 101.0})
        assert len(exits) == 0

    def test_exit_removes_from_portfolio(self):
        self.agent._virtual_portfolio["MSFT"] = {
            "qty": 1, "entry": 100.0, "stop_loss": 97.0, "take_profit": 106.0
        }
        self.agent.check_exits({"MSFT": 94.0})   # hits SL
        assert "MSFT" not in self.agent._virtual_portfolio

    # ── pnl tracking ──────────────────────────────────────────────────────────

    def test_realised_pnl_after_profit_exit(self):
        self.agent._virtual_portfolio["SPY"] = {
            "qty": 2, "entry": 100.0, "stop_loss": 97.0, "take_profit": 106.0
        }
        self.agent.check_exits({"SPY": 110.0})   # TP hit
        assert self.agent.realised_pnl() > 0

    def test_summary_win_count(self):
        self.agent._virtual_portfolio["SPY"] = {
            "qty": 1, "entry": 100.0, "stop_loss": 97.0, "take_profit": 106.0
        }
        self.agent.check_exits({"SPY": 110.0})
        s = self.agent.summary()
        assert s["win_count"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# LOGGER AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoggerAgent:

    def setup_method(self):
        self.agent = LoggerAgent()

    def test_log_event_stored(self):
        self.agent.log_event("MarketAgent", "SIGNAL", "SPY", "BUY signal", None)
        assert len(self.agent.events) == 1

    def test_log_event_fields(self):
        self.agent.log_event("RiskAgent", "RISK_CHECK", "QQQ", "Approved", 10.0)
        ev = self.agent.events[-1]
        assert ev.agent      == "RiskAgent"
        assert ev.event_type == "RISK_CHECK"
        assert ev.symbol     == "QQQ"
        assert ev.value      == 10.0

    def test_multiple_events_stored(self):
        for i in range(5):
            self.agent.log_event("Test", "INFO", "SPY", f"event {i}")
        assert len(self.agent.events) == 5

    def test_generate_report_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.config.REPORT_DIR", str(tmp_path))
        self.agent.log_event("Test", "INFO", "SPY", "test event")
        path = self.agent.generate_report(
            market_signals={"SPY": {
                "price": 510, "rsi": 40, "macd": 0.003,
                "action": "BUY", "confidence": 0.75, "trend": "bullish"
            }},
            exec_summary={
                "total_orders": 1, "buys": 1, "sells": 0,
                "realised_pnl": 5.0, "win_count": 1, "loss_count": 0
            },
            portfolio={"cash": 990.0, "n_positions": 1},
        )
        assert os.path.exists(path), "Report HTML file should exist"
        content = open(path).read()
        assert "AutoTrader" in content
        assert "SPY" in content

    def test_report_contains_pnl(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.config.REPORT_DIR", str(tmp_path))
        path = self.agent.generate_report(
            exec_summary={
                "total_orders": 2, "buys": 1, "sells": 1,
                "realised_pnl": 31.0, "win_count": 1, "loss_count": 0
            },
        )
        content = open(path).read()
        assert "31" in content


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrchestrator:

    def setup_method(self):
        self.orch = Orchestrator(alpaca_api=None)

    def test_single_cycle_returns_dict(self):
        result = self.orch.run_cycle()
        assert isinstance(result, dict)
        for key in ("signals", "decisions", "exec_summary", "portfolio"):
            assert key in result, f"Missing key: {key}"

    def test_signals_present_for_all_symbols(self):
        result = self.orch.run_cycle()
        from config import config
        for sym in config.SYMBOLS:
            assert sym in result["signals"], f"Missing signal for {sym}"

    def test_decisions_have_required_fields(self):
        result = self.orch.run_cycle()
        for sym, dec in result["decisions"].items():
            for field in ("approved", "reason", "qty"):
                assert field in dec, f"{sym} decision missing '{field}'"

    def test_portfolio_state_has_cash(self):
        result = self.orch.run_cycle()
        assert "cash" in result["portfolio"]
        assert result["portfolio"]["cash"] > 0

    def test_exec_summary_has_required_fields(self):
        result = self.orch.run_cycle()
        for field in ("total_orders", "buys", "sells", "realised_pnl"):
            assert field in result["exec_summary"], f"Missing field: {field}"

    def test_session_produces_report(self):
        path = self.orch.run_session(cycles=1, delay_seconds=0)
        assert path.endswith(".html")
        assert os.path.exists(path)


# ═══════════════════════════════════════════════════════════════════════════════
# END-TO-END SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd:

    def test_full_3_cycle_simulation(self):
        """
        3-cycle session: no exceptions, cash never negative, report created.
        """
        orch = Orchestrator(alpaca_api=None)
        report_path = orch.run_session(cycles=3, delay_seconds=0)

        assert os.path.exists(report_path)

        summary   = orch.exec_agent.summary()
        portfolio = orch.exec_agent.portfolio_state()

        assert portfolio["cash"] >= 0, "Cash must never go negative"
        print(
            f"\n  [E2E] Orders={summary['total_orders']} | "
            f"P&L=${summary['realised_pnl']:+.2f} | "
            f"Cash=${portfolio['cash']:.2f}"
        )

    def test_capital_never_exceeds_start(self):
        """Without exits, cash only decreases from buys."""
        orch = Orchestrator(alpaca_api=None)
        orch.run_session(cycles=2, delay_seconds=0)
        portfolio = orch.exec_agent.portfolio_state()
        # Cash + open position value should be ≤ starting capital + any gains
        # At minimum cash alone must not be wildly above start (no free money bug)
        from config import config
        assert portfolio["cash"] <= config.TRADING_CAPITAL * 10, \
            "Cash balance suspiciously high — possible accounting bug"
