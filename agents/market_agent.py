"""
agents/market_agent.py
─────────────────────
Market Analysis Agent
Fetches OHLCV bars, computes technical indicators, and produces
a structured signal dict for each symbol.

Signals returned:
  trend   : "bullish" | "bearish" | "neutral"
  momentum: float (-1 to +1)
  rsi     : float
  macd    : float
  price   : float
  action  : "BUY" | "SELL" | "HOLD"
  confidence: float (0–1)
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from logger import get_logger
from config import config

log = get_logger("MarketAgent")


class MarketAgent:
    """
    Fetches market data and produces trading signals.
    Works with real Alpaca data when connected, or uses synthetic
    data for offline / paper-testing mode.
    """

    # Symbols supported in offline/demo mode
    KNOWN_SYMBOLS = {"SPY", "QQQ", "AAPL", "MSFT", "NVDA"}

    # Base prices for synthetic data
    _BASE_PRICES = {"SPY": 510, "QQQ": 430, "AAPL": 175, "MSFT": 420, "NVDA": 800}

    def __init__(self, api=None):
        self.api = api
        self._offline = api is None
        if self._offline:
            log.warning("MarketAgent running in OFFLINE / DEMO mode (no Alpaca API).")
        else:
            log.info("MarketAgent initialised with live Alpaca connection.")

    # ── public interface ───────────────────────────────────────────────────────

    def analyse(self, symbols: Optional[List[str]] = None) -> Dict[str, dict]:
        symbols = symbols or config.SYMBOLS
        log.info(f"Analysing {len(symbols)} symbol(s): {symbols}")
        results = {}
        for sym in symbols:
            try:
                bars = self._fetch_bars(sym)
                signal = self._compute_signal(sym, bars)
                results[sym] = signal
                log.info(
                    f"{sym:6s} | price={signal['price']:.2f} "
                    f"rsi={signal['rsi']:.1f} macd={signal['macd']:.4f} "
                    f"→ {signal['action']} (conf={signal['confidence']:.2f})"
                )
            except Exception as exc:
                log.error(f"{sym}: analysis failed — {exc}")
                results[sym] = self._empty_signal(sym)
        return results

    # ── private helpers ────────────────────────────────────────────────────────

    def _fetch_bars(self, symbol: str, days: int = 60) -> pd.DataFrame:
        if self._offline:
            return self._synthetic_bars(symbol, days)

        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        bars  = self.api.get_bars(
            symbol,
            "1Day",
            start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            adjustment="raw",
            feed='iex'
        ).df
        if bars.empty:
            raise ValueError(f"No bars returned for {symbol}.")
        bars.index = pd.to_datetime(bars.index)
        bars = bars[["open", "high", "low", "close", "volume"]].copy()
        return bars

    def _synthetic_bars(self, symbol: str, days: int = 60) -> pd.DataFrame:
        """
        Generate deterministic synthetic OHLCV for offline testing.
        Uses hashlib (not hash()) so the seed is stable across Python processes.
        Unknown symbols raise ValueError so analyse() falls back to _empty_signal.
        """
        if symbol not in self.KNOWN_SYMBOLS:
            raise ValueError(f"Unknown symbol in offline mode: '{symbol}'")

        # hashlib gives a stable seed regardless of PYTHONHASHSEED
        seed = int(hashlib.md5(symbol.encode()).hexdigest(), 16) % (2 ** 32)
        rng  = np.random.RandomState(seed)

        base    = self._BASE_PRICES[symbol]
        dates   = pd.date_range(
            end=datetime.now(timezone.utc).date(), periods=days, freq="B"
        )
        returns = rng.normal(0.0003, 0.012, days)
        closes  = base * np.cumprod(1 + returns)
        highs   = closes * (1 + np.abs(rng.normal(0, 0.005, days)))
        lows    = closes * (1 - np.abs(rng.normal(0, 0.005, days)))
        opens   = np.roll(closes, 1)
        opens[0] = closes[0]
        vols    = rng.randint(20_000_000, 80_000_000, days)

        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows,
             "close": closes, "volume": vols},
            index=dates,
        )

        # Sanity check — should never happen with realistic params
        if df["close"].iloc[-1] <= 0:
            raise ValueError(f"Synthetic price went non-positive for {symbol}")

        return df

    def _compute_signal(self, symbol: str, bars: pd.DataFrame) -> dict:
        close = bars["close"]

        # ── RSI ──
        rsi = self._rsi(close, 14)

        # ── MACD ──
        macd_line, macd_signal = self._macd(close)
        macd_hist = macd_line - macd_signal

        # ── Moving averages ──
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        ema9  = close.ewm(span=9, adjust=False).mean()

        # ── Bollinger Bands ──
        bb_mid   = sma20
        bb_std   = close.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std

        # ── Latest values ──
        price   = float(close.iloc[-1])
        rsi_val = float(rsi.iloc[-1])
        macd_val = float(macd_hist.iloc[-1])
        sma20_v  = float(sma20.iloc[-1])
        sma50_v  = float(sma50.iloc[-1])
        bb_u    = float(bb_upper.iloc[-1])
        bb_l    = float(bb_lower.iloc[-1])
        ema9_v  = float(ema9.iloc[-1])

        # Guard against NaN bleeding through
        for name, val in [("price", price), ("rsi", rsi_val), ("sma20", sma20_v)]:
            if np.isnan(val) or not np.isfinite(val):
                raise ValueError(f"NaN/Inf in computed indicator '{name}' for {symbol}")

        if price <= 0:
            raise ValueError(f"Non-positive price computed for {symbol}: {price}")

        # ── Scoring ────────────────────────────────────────────────────────────
        score = 0.0

        if rsi_val < 30:    score += 2.0
        elif rsi_val < 45:  score += 0.5
        elif rsi_val > 70:  score -= 2.0
        elif rsi_val > 60:  score -= 0.5

        if macd_val > 0:  score += 1.5
        else:             score -= 1.5

        if price > sma20_v > sma50_v:   score += 1.5
        elif price < sma20_v < sma50_v: score -= 1.5

        if price < bb_l:   score += 1.0
        elif price > bb_u: score -= 1.0

        if ema9_v > sma20_v: score += 0.5
        else:                score -= 0.5

        # ── Action ────────────────────────────────────────────────────────────
        max_score  = 6.5
        norm_score = max(-1.0, min(1.0, score / max_score))

        if score >= 2.5:
            action, confidence = "BUY",  min(0.95, 0.5 + norm_score * 0.5)
        elif score <= -2.5:
            action, confidence = "SELL", min(0.95, 0.5 + abs(norm_score) * 0.5)
        else:
            action, confidence = "HOLD", 0.40

        trend = (
            "bullish" if score > 1 else
            "bearish" if score < -1 else
            "neutral"
        )

        return {
            "symbol":     symbol,
            "price":      round(price, 2),
            "rsi":        round(rsi_val, 2),
            "macd":       round(macd_val, 6),
            "sma20":      round(sma20_v, 2),
            "sma50":      round(sma50_v, 2),
            "bb_upper":   round(bb_u, 2),
            "bb_lower":   round(bb_l, 2),
            "score":      round(score, 2),
            "trend":      trend,
            "momentum":   round(norm_score, 4),
            "action":     action,
            "confidence": round(confidence, 4),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }

    # ── indicator implementations ──────────────────────────────────────────────

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta    = series.diff()
        gain     = delta.clip(lower=0)
        loss     = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
        rs  = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    @staticmethod
    def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        ema_fast    = series.ewm(span=fast,   adjust=False).mean()
        ema_slow    = series.ewm(span=slow,   adjust=False).mean()
        macd_line   = ema_fast - ema_slow
        macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line, macd_signal

    @staticmethod
    def _empty_signal(symbol: str) -> dict:
        return {
            "symbol": symbol, "price": 0.0, "rsi": 50.0, "macd": 0.0,
            "sma20": 0.0, "sma50": 0.0, "bb_upper": 0.0, "bb_lower": 0.0,
            "score": 0.0, "trend": "neutral", "momentum": 0.0,
            "action": "HOLD", "confidence": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    agent = MarketAgent(api=None)
    results = agent.analyse()
    print("\n" + "="*60)
    for sym, sig in results.items():
        print(f"{sym}: {sig['action']:4s} | RSI={sig['rsi']:.1f} | "
              f"MACD={sig['macd']:.5f} | conf={sig['confidence']:.2f} | trend={sig['trend']}")
    print("="*60)
