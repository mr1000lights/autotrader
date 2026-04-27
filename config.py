"""
config.py - Central configuration loader for AutoTrader
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Alpaca
    ALPACA_API_KEY     = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY  = os.getenv("ALPACA_SECRET_KEY", "")
    ALPACA_BASE_URL    = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    # Anthropic
    ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")

    # Trading parameters
    TRADING_CAPITAL    = float(os.getenv("TRADING_CAPITAL", "1000.0"))
    MAX_POSITION_SIZE  = float(os.getenv("MAX_POSITION_SIZE", "0.10"))
    MAX_DAILY_LOSS     = float(os.getenv("MAX_DAILY_LOSS", "0.02"))
    SYMBOLS            = os.getenv("SYMBOLS", "SPY,QQQ,AAPL,MSFT,NVDA").split(",")

    # Dirs
    LOG_LEVEL          = os.getenv("LOG_LEVEL", "INFO")
    REPORT_DIR         = os.getenv("REPORT_DIR", "reports")
    LOG_DIR            = os.getenv("LOG_DIR", "logs")

    @classmethod
    def validate(cls):
        missing = []
        if not cls.ALPACA_API_KEY or cls.ALPACA_API_KEY == "your_paper_api_key_here":
            missing.append("ALPACA_API_KEY")
        if not cls.ALPACA_SECRET_KEY or cls.ALPACA_SECRET_KEY == "your_paper_secret_key_here":
            missing.append("ALPACA_SECRET_KEY")
        if not cls.ANTHROPIC_API_KEY or cls.ANTHROPIC_API_KEY == "your_anthropic_key_here":
            missing.append("ANTHROPIC_API_KEY")
        if missing:
            raise EnvironmentError(
                f"\n❌ Missing required environment variables: {missing}\n"
                f"   Copy .env.example → .env and fill in your keys.\n"
            )
        return True

config = Config()
