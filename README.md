# 🤖 AutoTrader Multi-Agent System

A modular, multi-agent trading framework powered by Anthropic's Claude. This system automates market analysis, strategy generation, and execution.

## 📂 Project Structure
- `main.py`: Entry point for the trading bot.
- `agents/`: Logic for specialized agents (Analyst, Strategist, Execution).
- `config.py`: Centralized configuration and environment loading.
- `logs/`: (Local only) Execution logs and audit trails.

## 🚀 Quick Start

1. **Clone & Setup**
   ```bash
   git clone https://github.com
   cd autotrader
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configuration**
   Create a `.env` file in the root directory:
   ```text
   ANTHROPIC_API_KEY=your_api_key_here
   TRADING_MODE=paper
   ```

3. **Run**
   ```bash
   python main.py
   ```

## ⚠️ Security
Never commit your `.env` file. It is ignored by Git to protect your API credentials.
