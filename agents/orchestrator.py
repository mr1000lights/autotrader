"""
agents/orchestrator.py
──────────────────────
Orchestrator Agent
The brain of AutoTrader. Coordinates all sub-agents in the right order,
handles the trading loop, and delegates AI-powered reasoning to Claude
when signals are ambiguous.

Flow per cycle:
  1. MarketAgent  → signals for each symbol
  2. RiskAgent    → evaluate each signal
  3. ExecutionAgent → execute approved decisions
  4. LoggerAgent  → record all events
  5. Claude AI    → optional commentary on ambiguous signals
  6. Check exits  (SL / TP)
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import anthropic

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import config
from logger import get_logger
from agents.market_agent    import MarketAgent
from agents.risk_agent      import RiskAgent
from agents.execution_agent import ExecutionAgent
from agents.logger_agent    import LoggerAgent

log = get_logger("Orchestrator")

AI_CONFIDENCE_THRESHOLD = 0.60   # below this ask Claude for a second opinion


class Orchestrator:
    """
    Coordinates all agents and drives the main trading loop.
    """

    def __init__(self, alpaca_api=None):
        log.info("="*60)
        log.info("  AUTOTRADER — Orchestrator starting up")
        log.info("="*60)

        self.market_agent    = MarketAgent(api=alpaca_api)
        self.risk_agent      = RiskAgent()
        self.exec_agent      = ExecutionAgent(api=alpaca_api)
        self.logger_agent    = LoggerAgent()

        # Anthropic client for AI second-opinions
        try:
            self.claude = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            log.info("Claude AI client initialised.")
        except Exception as exc:
            self.claude = None
            log.warning(f"Claude AI unavailable: {exc}")

        self._cycle_count = 0

    # ── public ─────────────────────────────────────────────────────────────────

    def run_cycle(self) -> dict:
        """Execute one full trading cycle. Returns a summary dict."""
        self._cycle_count += 1
        cycle_start = datetime.now(timezone.utc)
        log.info(f"\n{'─'*55}")
        log.info(f"  CYCLE #{self._cycle_count}  —  {cycle_start.strftime('%H:%M:%S UTC')}")
        log.info(f"{'─'*55}")

        portfolio = self.exec_agent.portfolio_state()
        daily_pnl = self.exec_agent.realised_pnl()

        # ── 1. Market Analysis ─────────────────────────────────────────────────
        log.info("[1/5] Running Market Analysis Agent…")
        signals = self.market_agent.analyse(config.SYMBOLS)
        for sym, sig in signals.items():
            self.logger_agent.log_event(
                "MarketAgent", "SIGNAL", sym,
                f"action={sig['action']} rsi={sig['rsi']:.1f} conf={sig['confidence']:.2f} trend={sig['trend']}",
            )

        # ── 2. Risk Evaluation ─────────────────────────────────────────────────
        log.info("[2/5] Running Risk Agent…")
        open_positions = self.exec_agent.open_position_prices()
        decisions = {}
        for sym, sig in signals.items():
            decision = self.risk_agent.evaluate(
                sig,
                capital=portfolio.get("cash", config.TRADING_CAPITAL),
                open_positions=open_positions,
                daily_pnl=daily_pnl,
            )
            decisions[sym] = decision
            status = "✅ APPROVED" if decision.approved else "❌ REJECTED"
            self.logger_agent.log_event(
                "RiskAgent", "RISK_CHECK", sym,
                f"{status} — {decision.reason}",
            )

            # ── 2b. Claude second opinion for borderline signals ───────────────
            sig_conf = sig.get("confidence", 1.0)
            if (decision.approved and sig_conf < AI_CONFIDENCE_THRESHOLD and self.claude):
                ai_view = self._ask_claude(sym, sig)
                log.info(f"  🤖 Claude says ({sym}): {ai_view}")
                self.logger_agent.log_event("OrchestratorAI", "INFO", sym, f"Claude: {ai_view}")

        # ── 3. Execution ───────────────────────────────────────────────────────
        log.info("[3/5] Running Execution Agent…")
        for sym, decision in decisions.items():
            if decision.approved:
                # Inject price from market signal for simulation
                price = signals[sym].get("price", 100.0)
                decision = _patch_decision_price(decision, price)

                record = self.exec_agent.execute(decision)
                self.logger_agent.log_event(
                    "ExecutionAgent", "ORDER", sym,
                    f"{record.status.upper()} {record.side.upper()} {record.qty}x @ ${record.price:.2f}",
                    value=record.pnl,
                )

        # ── 4. Exit checks (SL / TP) ───────────────────────────────────────────
        log.info("[4/5] Checking stop-loss / take-profit exits…")
        current_prices = {sym: sig["price"] for sym, sig in signals.items()}
        exits = self.exec_agent.check_exits(current_prices)
        for ex in exits:
            self.logger_agent.log_event(
                "ExecutionAgent", "EXIT", ex.symbol,
                f"Exit @ ${ex.price:.2f} P&L=${ex.pnl:+.2f}",
                value=ex.pnl,
            )

        # ── 5. Logging ─────────────────────────────────────────────────────────
        log.info("[5/5] Logging cycle results…")
        portfolio = self.exec_agent.portfolio_state()
        exec_summary = self.exec_agent.summary()

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        log.info(f"Cycle #{self._cycle_count} complete in {elapsed:.1f}s | "
                 f"cash=${portfolio.get('cash',0):.2f} | "
                 f"P&L=${exec_summary.get('realised_pnl',0):+.2f}")

        return {
            "cycle":         self._cycle_count,
            "signals":       signals,
            "decisions":     {k: {"approved": v.approved, "reason": v.reason,
                                  "qty": v.qty} for k, v in decisions.items()},
            "exec_summary":  exec_summary,
            "portfolio":     portfolio,
        }

    def run_session(self, cycles: int = 3, delay_seconds: int = 5) -> str:
        """
        Run multiple cycles and generate a final report.
        Returns the path to the HTML report.
        """
        log.info(f"Starting session: {cycles} cycles, {delay_seconds}s between each.")
        for i in range(cycles):
            self.run_cycle()
            if i < cycles - 1:
                log.info(f"Waiting {delay_seconds}s before next cycle…")
                time.sleep(delay_seconds)

        return self._generate_final_report()

    def _generate_final_report(self) -> str:
        signals      = self.market_agent.analyse(config.SYMBOLS)
        risk_summary = self.risk_agent.summary()
        exec_summary = self.exec_agent.summary()
        portfolio    = self.exec_agent.portfolio_state()

        report_path = self.logger_agent.generate_report(
            market_signals=signals,
            risk_summary=risk_summary,
            exec_summary=exec_summary,
            portfolio=portfolio,
        )
        return report_path

    def _ask_claude(self, symbol: str, signal: dict) -> str:
        """Ask Claude for a brief second opinion on a borderline signal."""
        try:
            prompt = (
                f"You are a concise trading assistant. Analyse this signal for {symbol}:\n"
                f"  Price: ${signal.get('price',0):.2f}\n"
                f"  RSI:   {signal.get('rsi',50):.1f}\n"
                f"  MACD:  {signal.get('macd',0):.5f}\n"
                f"  Trend: {signal.get('trend','neutral')}\n"
                f"  Action suggested: {signal.get('action','HOLD')}\n"
                f"  Confidence: {signal.get('confidence',0):.0%}\n\n"
                f"In 1-2 sentences, should a beginner trader proceed or wait? Be direct."
            )
            resp = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as exc:
            return f"AI unavailable: {exc}"


# ── helper ─────────────────────────────────────────────────────────────────────

def _patch_decision_price(decision, price: float):
    """Execution agent needs the current price to simulate fills."""
    decision._price = price
    return decision


# ── standalone ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    orch = Orchestrator(alpaca_api=None)
    report = orch.run_session(cycles=2, delay_seconds=2)
    print(f"\n✅ Session complete. Report → {report}")
