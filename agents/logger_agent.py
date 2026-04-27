"""
agents/logger_agent.py
──────────────────────
Logger / Reporting Agent
Collects events from all other agents and produces:
  • JSON trade log (machine-readable)
  • HTML performance report (human-readable, opens in browser)
  • Console summary table

Call  log_event()   after each agent action.
Call  generate_report() at end of session / on-demand.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from logger import get_logger
from config import config

log = get_logger("LoggerAgent")

os.makedirs(config.REPORT_DIR, exist_ok=True)


@dataclass
class TradeEvent:
    ts:         str
    agent:      str
    event_type: str   # SIGNAL | RISK_CHECK | ORDER | EXIT | ERROR | INFO
    symbol:     str
    detail:     str
    value:      Optional[float] = None


class LoggerAgent:

    def __init__(self):
        self.events:        List[TradeEvent] = []
        self.session_start: str = datetime.utcnow().isoformat()
        self._json_path:    str = os.path.join(
            config.REPORT_DIR,
            f"trade_log_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        )
        log.info(f"LoggerAgent ready — JSON log: {self._json_path}")

    # ── public ─────────────────────────────────────────────────────────────────

    def log_event(
        self,
        agent:      str,
        event_type: str,
        symbol:     str,
        detail:     str,
        value:      Optional[float] = None,
    ):
        ev = TradeEvent(
            ts=datetime.utcnow().isoformat(),
            agent=agent,
            event_type=event_type,
            symbol=symbol,
            detail=detail,
            value=value,
        )
        self.events.append(ev)
        self._append_json(ev)

    def generate_report(
        self,
        market_signals: Optional[dict]  = None,
        risk_summary:   Optional[dict]  = None,
        exec_summary:   Optional[dict]  = None,
        portfolio:      Optional[dict]  = None,
    ) -> str:
        """Produce an HTML report and return its file path."""
        html_path = os.path.join(
            config.REPORT_DIR,
            f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
        )
        html = self._build_html(market_signals, risk_summary, exec_summary, portfolio)
        with open(html_path, "w") as f:
            f.write(html)
        log.info(f"📊 Report saved → {html_path}")
        self._print_console_summary(exec_summary, portfolio)
        return html_path

    # ── private ────────────────────────────────────────────────────────────────

    def _append_json(self, ev: TradeEvent):
        try:
            if os.path.exists(self._json_path):
                with open(self._json_path) as f:
                    data = json.load(f)
            else:
                data = []
            data.append(asdict(ev))
            with open(self._json_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            log.error(f"JSON log write failed: {exc}")

    def _print_console_summary(self, exec_summary, portfolio):
        print("\n" + "═"*65)
        print("  AUTOTRADER SESSION SUMMARY")
        print("═"*65)
        if exec_summary:
            pnl = exec_summary.get("realised_pnl", 0.0)
            pnl_sign = "+" if pnl >= 0 else ""
            print(f"  Total Orders  : {exec_summary.get('total_orders', 0)}")
            print(f"  Buys / Sells  : {exec_summary.get('buys', 0)} / {exec_summary.get('sells', 0)}")
            print(f"  Win / Loss    : {exec_summary.get('win_count', 0)} / {exec_summary.get('loss_count', 0)}")
            print(f"  Realised P&L  : {pnl_sign}${pnl:.2f}")
        if portfolio:
            print(f"  Cash Balance  : ${portfolio.get('cash', 0):.2f}")
            print(f"  Open Positions: {portfolio.get('n_positions', 0)}")
        print(f"  Events Logged : {len(self.events)}")
        print("═"*65 + "\n")

    def _build_html(self, market_signals, risk_summary, exec_summary, portfolio) -> str:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        # ── signals table ──────────────────────────────────────────────────────
        sig_rows = ""
        if market_signals:
            for sym, s in market_signals.items():
                action_color = {"BUY": "#00c853", "SELL": "#d50000", "HOLD": "#ff6d00"}.get(s.get("action",""), "#aaa")
                sig_rows += f"""
                <tr>
                  <td>{sym}</td>
                  <td>${s.get('price',0):.2f}</td>
                  <td>{s.get('rsi',0):.1f}</td>
                  <td>{s.get('macd',0):.5f}</td>
                  <td style="color:{action_color};font-weight:700">{s.get('action','—')}</td>
                  <td>{s.get('confidence',0):.0%}</td>
                  <td>{s.get('trend','—')}</td>
                </tr>"""

        # ── event log table ────────────────────────────────────────────────────
        ev_rows = ""
        for ev in self.events[-50:]:  # last 50
            badge_color = {
                "SIGNAL":     "#1565c0",
                "RISK_CHECK": "#6a1b9a",
                "ORDER":      "#00695c",
                "EXIT":       "#e65100",
                "ERROR":      "#b71c1c",
                "INFO":       "#37474f",
            }.get(ev.event_type, "#555")
            val_str = f"${ev.value:+.2f}" if ev.value is not None else ""
            ev_rows += f"""
            <tr>
              <td style="font-size:11px;color:#777">{ev.ts[11:19]}</td>
              <td><span style="background:{badge_color};color:#fff;padding:2px 7px;border-radius:4px;font-size:11px">{ev.event_type}</span></td>
              <td>{ev.agent}</td>
              <td><strong>{ev.symbol}</strong></td>
              <td style="font-size:12px">{ev.detail}</td>
              <td style="font-weight:700;color:{'#00c853' if ev.value and ev.value>0 else '#d50000' if ev.value and ev.value<0 else '#555'}">{val_str}</td>
            </tr>"""

        # ── stats cards ────────────────────────────────────────────────────────
        pnl     = exec_summary.get("realised_pnl", 0.0)   if exec_summary else 0.0
        orders  = exec_summary.get("total_orders",  0)     if exec_summary else 0
        wins    = exec_summary.get("win_count",      0)     if exec_summary else 0
        losses  = exec_summary.get("loss_count",     0)     if exec_summary else 0
        cash    = portfolio.get("cash",            config.TRADING_CAPITAL) if portfolio else config.TRADING_CAPITAL
        wr      = f"{wins/(wins+losses)*100:.0f}%" if (wins+losses) > 0 else "—"
        pnl_color = "#00c853" if pnl >= 0 else "#d50000"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AutoTrader Report — {now}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');
  :root {{
    --bg: #0d0d0d; --surface: #161616; --border: #2a2a2a;
    --text: #e0e0e0; --muted: #777; --accent: #00e5ff;
    --green: #00c853; --red: #d50000; --orange: #ff6d00;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'IBM Plex Sans', sans-serif;
          font-size: 14px; line-height: 1.6; padding: 40px 32px; max-width: 1200px; margin: 0 auto; }}
  header {{ border-bottom: 1px solid var(--border); padding-bottom: 24px; margin-bottom: 36px; }}
  header h1 {{ font-size: 28px; font-weight: 700; letter-spacing: -0.5px; color: #fff; }}
  header h1 span {{ color: var(--accent); }}
  header p {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
  .cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 36px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
           padding: 20px; }}
  .card .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 8px; }}
  .card .value {{ font-size: 26px; font-weight: 700; font-family: 'IBM Plex Mono', monospace; }}
  section {{ margin-bottom: 40px; }}
  section h2 {{ font-size: 15px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;
                color: var(--muted); margin-bottom: 16px; border-left: 3px solid var(--accent);
                padding-left: 12px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted);
        padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #1e1e1e; font-family: 'IBM Plex Mono', monospace;
        font-size: 13px; }}
  tr:hover td {{ background: #1e1e1e; }}
  .footer {{ margin-top: 48px; color: var(--muted); font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>Auto<span>Trader</span> — Session Report</h1>
  <p>Generated: {now} &nbsp;|&nbsp; Mode: Paper Trading &nbsp;|&nbsp; Capital: ${config.TRADING_CAPITAL:,.2f}</p>
</header>

<div class="cards">
  <div class="card"><div class="label">Realised P&L</div>
    <div class="value" style="color:{pnl_color}">{"+" if pnl>=0 else ""}${pnl:.2f}</div></div>
  <div class="card"><div class="label">Cash Balance</div>
    <div class="value">${cash:,.2f}</div></div>
  <div class="card"><div class="label">Total Orders</div>
    <div class="value">{orders}</div></div>
  <div class="card"><div class="label">Win Rate</div>
    <div class="value">{wr}</div></div>
  <div class="card"><div class="label">Wins / Losses</div>
    <div class="value"><span style="color:var(--green)">{wins}</span> / <span style="color:var(--red)">{losses}</span></div></div>
</div>

<section>
  <h2>Market Signals</h2>
  <table>
    <thead><tr>
      <th>Symbol</th><th>Price</th><th>RSI</th><th>MACD</th>
      <th>Action</th><th>Confidence</th><th>Trend</th>
    </tr></thead>
    <tbody>{sig_rows}</tbody>
  </table>
</section>

<section>
  <h2>Event Log (last 50)</h2>
  <table>
    <thead><tr>
      <th>Time</th><th>Type</th><th>Agent</th><th>Symbol</th><th>Detail</th><th>Value</th>
    </tr></thead>
    <tbody>{ev_rows if ev_rows else "<tr><td colspan='6' style='color:#555;text-align:center'>No events logged</td></tr>"}</tbody>
  </table>
</section>

<div class="footer">AutoTrader · Paper Trading Mode · Not financial advice.</div>
</body>
</html>"""


# ── standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    agent = LoggerAgent()

    # Log some test events
    agent.log_event("MarketAgent",    "SIGNAL",     "SPY",  "BUY signal | RSI=32 MACD=+0.003", None)
    agent.log_event("RiskAgent",      "RISK_CHECK", "SPY",  "Approved BUY 1x @ $510", None)
    agent.log_event("ExecutionAgent", "ORDER",      "SPY",  "Simulated BUY 1x @ $510", -510.0)
    agent.log_event("ExecutionAgent", "EXIT",       "SPY",  "Take-profit hit @ $541", 31.0)
    agent.log_event("MarketAgent",    "SIGNAL",     "QQQ",  "HOLD signal — confidence too low", None)

    signals = {
        "SPY":  {"price": 510, "rsi": 32, "macd": 0.003, "action": "BUY",  "confidence": 0.80, "trend": "bullish"},
        "QQQ":  {"price": 430, "rsi": 55, "macd": -0.001,"action": "HOLD", "confidence": 0.40, "trend": "neutral"},
    }
    exec_s  = {"total_orders": 2, "buys": 1, "sells": 1, "realised_pnl": 31.0, "win_count": 1, "loss_count": 0}
    port    = {"cash": 1031.0, "n_positions": 0}

    path = agent.generate_report(market_signals=signals, exec_summary=exec_s, portfolio=port)
    print(f"\n✅ Report: {path}")
