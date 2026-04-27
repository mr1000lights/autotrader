"""
main.py
───────
AutoTrader — main entry point.

Usage:
  python main.py              # single session (3 cycles)
  python main.py --cycles 5  # custom cycle count
  python main.py --live       # live Alpaca (paper) mode
"""

import argparse
import sys

from config import config
from logger import get_logger
from agents.orchestrator import Orchestrator

log = get_logger("Main")


def main():
    parser = argparse.ArgumentParser(description="AutoTrader — Multi-Agent Paper Trading System")
    parser.add_argument("--cycles",  type=int, default=3,  help="Number of trading cycles (default: 3)")
    parser.add_argument("--delay",   type=int, default=5,  help="Seconds between cycles (default: 5)")
    parser.add_argument("--live",    action="store_true",   help="Connect to real Alpaca API (paper mode)")
    args = parser.parse_args()

    api = None
    if args.live:
        try:
            config.validate()
            import alpaca_trade_api as tradeapi
            api = tradeapi.REST(
                config.ALPACA_API_KEY,
                config.ALPACA_SECRET_KEY,
                config.ALPACA_BASE_URL,
            )
            account = api.get_account()
            log.info(f"✅ Connected to Alpaca | equity=${float(account.equity):,.2f}")
        except EnvironmentError as exc:
            print(exc)
            sys.exit(1)
        except Exception as exc:
            log.error(f"Alpaca connection failed: {exc}")
            log.warning("Falling back to offline/simulated mode.")
            api = None

    orch = Orchestrator(alpaca_api=api)
    report_path = orch.run_session(cycles=args.cycles, delay_seconds=args.delay)

    print(f"\n{'═'*55}")
    print(f"  ✅ Session complete!")
    print(f"  📊 Report: {report_path}")
    print(f"{'═'*55}\n")


if __name__ == "__main__":
    main()
