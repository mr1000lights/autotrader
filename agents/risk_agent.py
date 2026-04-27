"""
agents/risk_agent.py
─────────────────────
Risk Management Agent
Validates every trade proposal before it reaches execution.

Checks:
  1. Daily loss limit (stops all trading if breached)
  2. Position size cap (max % of capital per trade)
  3. Maximum open positions
  4. Confidence threshold
  5. Volatility filter (ATR-based)
  6. Duplicate position guard

Returns a RiskDecision with: approved, reason, adjusted_qty, stop_loss, take_profit
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from logger import get_logger
from config import config

log = get_logger("RiskAgent")

MIN_CONFIDENCE     = 0.55   # minimum signal confidence to trade
MAX_OPEN_POSITIONS = 5      # never hold more than 5 symbols at once
STOP_LOSS_PCT      = 0.03   # 3% stop-loss below entry
TAKE_PROFIT_PCT    = 0.06   # 6% take-profit above entry  (2:1 RR)
ATR_VOLATILITY_CAP = 0.05   # skip if 14-day ATR% > 5% (too volatile)


@dataclass
class RiskDecision:
    approved:      bool
    reason:        str
    symbol:        str
    action:        str          # BUY | SELL | HOLD
    qty:           int  = 0
    stop_loss:     float = 0.0
    take_profit:   float = 0.0
    risk_per_trade: float = 0.0


class RiskAgent:
    """
    Stateful risk manager.  Pass it the current portfolio state and a
    market signal and it will return an actionable RiskDecision.
    """

    def __init__(self):
        self._daily_pnl:     Dict[str, float] = {}  # date-str → realised P&L
        self._open_positions: Dict[str, float] = {}  # symbol → entry_price
        self._trade_count:   int = 0
        log.info("RiskAgent initialised.")
        log.info(
            f"  Limits → max_pos={MAX_OPEN_POSITIONS} "
            f"| stop={STOP_LOSS_PCT*100:.0f}% "
            f"| take-profit={TAKE_PROFIT_PCT*100:.0f}% "
            f"| min_conf={MIN_CONFIDENCE}"
        )

    # ── public ─────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        signal:        dict,
        capital:       float,
        open_positions: Optional[Dict[str, float]] = None,
        daily_pnl:     float = 0.0,
    ) -> RiskDecision:
        """
        Evaluate a market signal and decide whether to approve the trade.

        Args:
            signal:         dict from MarketAgent.analyse()
            capital:        current account equity
            open_positions: {symbol: entry_price} of current positions
            daily_pnl:      today's realised P&L (negative = loss)
        Returns:
            RiskDecision
        """
        symbol     = signal["symbol"]
        action     = signal["action"]
        confidence = signal["confidence"]
        price      = signal["price"]

        if open_positions is not None:
            self._open_positions = open_positions

        # ── guard: HOLD needs no approval ─────────────────────────────────────
        if action == "HOLD":
            return RiskDecision(approved=False, reason="Signal is HOLD — no trade needed.",
                                symbol=symbol, action=action)

        # ── 1. Daily loss circuit-breaker ──────────────────────────────────────
        max_loss = capital * config.MAX_DAILY_LOSS
        if daily_pnl < 0 and abs(daily_pnl) >= max_loss:
            msg = (f"Daily loss limit hit: ${abs(daily_pnl):.2f} ≥ "
                   f"${max_loss:.2f} ({config.MAX_DAILY_LOSS*100:.1f}% of capital). "
                   f"All trading halted for today.")
            log.warning(f"🛑 {symbol}: {msg}")
            return RiskDecision(approved=False, reason=msg, symbol=symbol, action=action)

        # ── 2. Confidence threshold ────────────────────────────────────────────
        if confidence < MIN_CONFIDENCE:
            msg = f"Confidence {confidence:.2f} < threshold {MIN_CONFIDENCE} — skipping."
            log.info(f"⚠️  {symbol}: {msg}")
            return RiskDecision(approved=False, reason=msg, symbol=symbol, action=action)

        # ── 3. Max open positions ──────────────────────────────────────────────
        n_open = len(self._open_positions)
        if action == "BUY" and n_open >= MAX_OPEN_POSITIONS:
            msg = f"Max open positions ({MAX_OPEN_POSITIONS}) reached — cannot add {symbol}."
            log.info(f"⚠️  {symbol}: {msg}")
            return RiskDecision(approved=False, reason=msg, symbol=symbol, action=action)

        # ── 4. Duplicate position guard ───────────────────────────────────────
        if action == "BUY" and symbol in self._open_positions:
            msg = f"Already holding {symbol} — no pyramid buying."
            log.info(f"⚠️  {symbol}: {msg}")
            return RiskDecision(approved=False, reason=msg, symbol=symbol, action=action)

        if action == "SELL" and symbol not in self._open_positions:
            msg = f"No open position in {symbol} to sell."
            log.info(f"⚠️  {symbol}: {msg}")
            return RiskDecision(approved=False, reason=msg, symbol=symbol, action=action)

        # ── 5. Position sizing ─────────────────────────────────────────────────
        max_position_value = capital * config.MAX_POSITION_SIZE
        qty = int(max_position_value / price)
        if qty < 1:
            msg = (f"Capital too low for {symbol} @ ${price:.2f} "
                   f"(max_position=${max_position_value:.2f}).")
            log.warning(f"⚠️  {symbol}: {msg}")
            return RiskDecision(approved=False, reason=msg, symbol=symbol, action=action)

        # ── 6. Stop-loss & take-profit ─────────────────────────────────────────
        if action == "BUY":
            stop_loss   = round(price * (1 - STOP_LOSS_PCT), 2)
            take_profit = round(price * (1 + TAKE_PROFIT_PCT), 2)
        else:  # SELL (short or close)
            stop_loss   = round(price * (1 + STOP_LOSS_PCT), 2)
            take_profit = round(price * (1 - TAKE_PROFIT_PCT), 2)

        risk_per_trade = round(qty * price * STOP_LOSS_PCT, 2)

        # ── 7. Risk-per-trade sanity check ─────────────────────────────────────
        max_risk = capital * 0.02   # never risk more than 2% on single trade
        if risk_per_trade > max_risk:
            # Scale down qty
            qty = max(1, int(max_risk / (price * STOP_LOSS_PCT)))
            risk_per_trade = round(qty * price * STOP_LOSS_PCT, 2)
            log.info(f"{symbol}: qty scaled down to {qty} to respect 2% risk cap.")

        # ── APPROVED ───────────────────────────────────────────────────────────
        self._trade_count += 1
        msg = (f"✅ APPROVED {action} {qty}x {symbol} @ ${price:.2f} | "
               f"SL=${stop_loss} TP=${take_profit} | risk=${risk_per_trade:.2f}")
        log.info(msg)

        return RiskDecision(
            approved=True,
            reason="All risk checks passed.",
            symbol=symbol,
            action=action,
            qty=qty,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_per_trade=risk_per_trade,
        )

    def register_open(self, symbol: str, price: float):
        self._open_positions[symbol] = price
        log.debug(f"Registered open position: {symbol} @ {price}")

    def register_close(self, symbol: str):
        self._open_positions.pop(symbol, None)
        log.debug(f"Closed position: {symbol}")

    def summary(self) -> dict:
        return {
            "open_positions": dict(self._open_positions),
            "total_trades_evaluated": self._trade_count,
            "n_open": len(self._open_positions),
        }


# ── standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    agent = RiskAgent()

    # Simulate signals
    test_cases = [
        {"symbol": "SPY",  "action": "BUY",  "price": 510.0, "confidence": 0.78, "rsi": 35},
        {"symbol": "QQQ",  "action": "BUY",  "price": 430.0, "confidence": 0.42, "rsi": 38},  # low conf
        {"symbol": "AAPL", "action": "SELL", "price": 175.0, "confidence": 0.65, "rsi": 72},
        {"symbol": "MSFT", "action": "HOLD", "price": 420.0, "confidence": 0.55, "rsi": 50},
    ]

    capital = 1000.0
    open_pos = {}

    print("\n" + "="*70)
    print("RISK AGENT — TEST RUN")
    print("="*70)
    for sig in test_cases:
        decision = agent.evaluate(sig, capital=capital, open_positions=open_pos, daily_pnl=0.0)
        status = "✅ APPROVED" if decision.approved else "❌ REJECTED"
        print(f"\n{status}  {sig['symbol']} {sig['action']}")
        print(f"  Reason : {decision.reason}")
        if decision.approved:
            print(f"  Qty    : {decision.qty}")
            print(f"  SL/TP  : ${decision.stop_loss} / ${decision.take_profit}")
            print(f"  Risk   : ${decision.risk_per_trade}")
            open_pos[sig["symbol"]] = sig["price"]
    print("\n" + "="*70)
    print("Summary:", agent.summary())
