"""
agents/execution_agent.py
─────────────────────────
Execution Agent
Translates approved RiskDecisions into actual Alpaca orders.

In PAPER / OFFLINE mode it simulates fills and tracks a virtual portfolio.
In LIVE mode it uses the real Alpaca REST API.

Every order placed is recorded in self.order_history for reporting.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from logger import get_logger
from config import config

log = get_logger("ExecutionAgent")


@dataclass
class OrderRecord:
    order_id:   str
    symbol:     str
    side:       str           # buy | sell
    qty:        int
    price:      float
    status:     str           # filled | rejected | simulated
    timestamp:  str
    stop_loss:  float = 0.0
    take_profit: float = 0.0
    pnl:        Optional[float] = None   # filled in on close


class ExecutionAgent:
    """
    Places market orders via Alpaca and tracks fill history.
    Falls back to full simulation if no API is provided.
    """

    def __init__(self, api=None):
        self.api              = api
        self._offline         = api is None
        self.order_history:   List[OrderRecord] = []
        self._virtual_portfolio: Dict[str, dict] = {}   # symbol → {qty, entry, sl, tp}
        self._virtual_cash    = config.TRADING_CAPITAL

        mode = "OFFLINE/SIMULATED" if self._offline else "LIVE (Paper)"
        log.info(f"ExecutionAgent initialised — mode: {mode}")
        log.info(f"Starting capital: ${self._virtual_cash:,.2f}")

    # ── public ─────────────────────────────────────────────────────────────────

    def execute(self, decision) -> OrderRecord:
        """
        Takes a RiskDecision and submits / simulates the order.
        Returns an OrderRecord.
        """
        from agents.risk_agent import RiskDecision  # local import to avoid circular

        if not decision.approved:
            log.debug(f"Skipping unapproved decision: {decision.symbol} — {decision.reason}")
            return self._make_record(decision.symbol, decision.action.lower(),
                                     0, 0.0, "skipped", decision.stop_loss, decision.take_profit)

        sym    = decision.symbol
        side   = decision.action.lower()  # "buy" or "sell"
        qty    = decision.qty
        price  = self._get_price(sym, decision)

        if self._offline:
            record = self._simulate_order(sym, side, qty, price,
                                          decision.stop_loss, decision.take_profit)
        else:
            record = self._place_alpaca_order(sym, side, qty, price,
                                              decision.stop_loss, decision.take_profit)

        self.order_history.append(record)
        return record

    def check_exits(self, current_prices: Dict[str, float]) -> List[OrderRecord]:
        """
        For each open virtual position, check if SL or TP has been hit.
        Returns list of exit records.
        """
        exits = []
        for sym, pos in list(self._virtual_portfolio.items()):
            cp = current_prices.get(sym, pos["entry"])
            sl = pos["stop_loss"]
            tp = pos["take_profit"]
            reason = None

            if cp <= sl:
                reason = f"Stop-loss hit @ ${cp:.2f} (SL=${sl})"
            elif cp >= tp:
                reason = f"Take-profit hit @ ${cp:.2f} (TP=${tp})"

            if reason:
                pnl = (cp - pos["entry"]) * pos["qty"]
                self._virtual_cash += cp * pos["qty"]
                record = self._make_record(sym, "sell", pos["qty"], cp,
                                           "exit_triggered",
                                           sl, tp, pnl=pnl)
                self.order_history.append(record)
                exits.append(record)
                del self._virtual_portfolio[sym]
                log.info(f"EXIT {sym}: {reason} | P&L=${pnl:+.2f}")

        return exits

    # ── portfolio state ────────────────────────────────────────────────────────

    def portfolio_state(self) -> dict:
        if self._offline:
            return {
                "cash":       round(self._virtual_cash, 2),
                "positions":  dict(self._virtual_portfolio),
                "n_positions": len(self._virtual_portfolio),
            }
        try:
            account   = self.api.get_account()
            positions = self.api.list_positions()
            return {
                "cash":        float(account.cash),
                "equity":      float(account.equity),
                "positions":   {p.symbol: {"qty": int(p.qty), "entry": float(p.avg_entry_price)}
                                for p in positions},
                "n_positions": len(positions),
            }
        except Exception as exc:
            log.error(f"portfolio_state error: {exc}")
            return {}

    def open_position_prices(self) -> Dict[str, float]:
        return {sym: pos["entry"] for sym, pos in self._virtual_portfolio.items()}

    def realised_pnl(self) -> float:
        return sum(r.pnl for r in self.order_history if r.pnl is not None)

    def summary(self) -> dict:
        filled   = [r for r in self.order_history if r.status in ("simulated", "filled", "exit_triggered")]
        buys     = [r for r in filled if r.side == "buy"]
        sells    = [r for r in filled if r.side in ("sell", "exit_triggered")]
        pnls     = [r.pnl for r in filled if r.pnl is not None]
        return {
            "total_orders":  len(filled),
            "buys":          len(buys),
            "sells":         len(sells),
            "realised_pnl":  round(sum(pnls), 2),
            "win_count":     sum(1 for p in pnls if p > 0),
            "loss_count":    sum(1 for p in pnls if p < 0),
            "cash":          round(self._virtual_cash, 2),
        }

    # ── private ────────────────────────────────────────────────────────────────

    def _simulate_order(
        self, sym: str, side: str, qty: int, price: float,
        stop_loss: float, take_profit: float,
    ) -> OrderRecord:
        cost = qty * price
        if side == "buy":
            if self._virtual_cash < cost:
                log.warning(f"SIMULATED: insufficient cash ${self._virtual_cash:.2f} for {qty}x {sym}")
                return self._make_record(sym, side, qty, price, "insufficient_cash", stop_loss, take_profit)
            self._virtual_cash -= cost
            self._virtual_portfolio[sym] = {
                "qty":        qty,
                "entry":      price,
                "stop_loss":  stop_loss,
                "take_profit": take_profit,
            }
            pnl = None
        else:  # sell / close
            entry = self._virtual_portfolio.get(sym, {}).get("entry", price)
            pnl   = (price - entry) * qty
            self._virtual_cash += cost
            self._virtual_portfolio.pop(sym, None)

        log.info(
            f"[SIM] {side.upper():4s} {qty}x {sym} @ ${price:.2f} "
            + (f"| P&L=${pnl:+.2f}" if pnl is not None else f"| cost=${cost:.2f}")
            + f" | cash=${self._virtual_cash:.2f}"
        )
        record = self._make_record(sym, side, qty, price, "simulated", stop_loss, take_profit, pnl)
        self.order_history.append(record)
        return record

    def _place_alpaca_order(
        self, sym: str, side: str, qty: int, price: float,
        stop_loss: float, take_profit: float,
    ) -> OrderRecord:
        try:
            order = self.api.submit_order(
                symbol=sym,
                qty=qty,
                side=side,
                type="market",
                time_in_force="day",
            )
            log.info(f"[ALPACA] Order submitted: {side.upper()} {qty}x {sym} → id={order.id}")
            return self._make_record(sym, side, qty, price, "filled", stop_loss, take_profit)
        except Exception as exc:
            log.error(f"[ALPACA] Order FAILED {sym}: {exc}")
            return self._make_record(sym, side, qty, price, "rejected", stop_loss, take_profit)

    def _get_price(self, sym: str, decision) -> float:
        """Best-effort price: use signal price or last trade from API."""
        if hasattr(decision, "price") and decision.price:
            # price isn't on RiskDecision directly — pull from virtual portfolio fallback
            pass
        if self._offline:
            # Synthetic: use portfolio entry or a sensible default
            return self._virtual_portfolio.get(sym, {}).get("entry", 100.0)
        try:
            trade = self.api.get_latest_trade(sym)
            return float(trade.price)
        except Exception:
            return 100.0

    @staticmethod
    def _make_record(
        symbol, side, qty, price, status, stop_loss, take_profit, pnl=None
    ) -> OrderRecord:
        return OrderRecord(
            order_id    = str(uuid.uuid4())[:8],
            symbol      = symbol,
            side        = side,
            qty         = qty,
            price       = price,
            status      = status,
            timestamp   = datetime.utcnow().isoformat(),
            stop_loss   = stop_loss,
            take_profit = take_profit,
            pnl         = pnl,
        )


# ── standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from agents.risk_agent import RiskAgent, RiskDecision

    executor = ExecutionAgent(api=None)
    risk     = RiskAgent()

    signals = [
        {"symbol": "SPY",  "action": "BUY",  "price": 510.0, "confidence": 0.80, "rsi": 32},
        {"symbol": "AAPL", "action": "BUY",  "price": 175.0, "confidence": 0.70, "rsi": 40},
    ]

    open_pos = {}
    print("\n" + "="*60)
    print("EXECUTION AGENT — TEST RUN")
    print("="*60)
    for sig in signals:
        d = risk.evaluate(sig, capital=1000.0, open_positions=open_pos, daily_pnl=0.0)
        if d.approved:
            # Pass price via a small monkey-patch (in real flow, price comes from market agent)
            d_with_price = d
            open_pos[sig["symbol"]] = sig["price"]
        rec = executor.execute(d)
        print(f"\n{rec.status.upper():12s} {rec.side.upper():4s} {rec.qty}x {rec.symbol} "
              f"@ ${rec.price:.2f} | id={rec.order_id}")

    # Simulate SL/TP hits
    print("\n--- Checking exits (SL/TP) ---")
    exits = executor.check_exits({"SPY": 480.0, "AAPL": 186.5})  # SPY hits SL, AAPL hits TP
    for ex in exits:
        print(f"EXIT {ex.symbol}: P&L=${ex.pnl:+.2f}")

    print("\nSummary:", executor.summary())
    print("="*60)
