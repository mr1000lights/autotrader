#!/bin/bash
# quickstart.sh — AutoTrader setup for M1 Mac
# Requires Python 3.11 or 3.12 (NOT 3.13 or 3.14)

set -e

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   AutoTrader — M1 Mac Quickstart                 ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Find a compatible Python (3.11 or 3.12, not 3.13+) ────────────────────────
find_python() {
  for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
      ver=$("$cmd" -c 'import sys; print(sys.version_info[:2])')
      if [[ "$ver" == "(3, 12)" || "$ver" == "(3, 11)" ]]; then
        echo "$cmd"
        return
      fi
    fi
  done
  echo ""
}

PYTHON=$(find_python)

if [ -z "$PYTHON" ]; then
  echo "❌ Python 3.11 or 3.12 not found."
  echo ""
  echo "   You have Python 3.14 which pandas does not support yet."
  echo "   Install Python 3.12 via Homebrew:"
  echo ""
  echo "     brew install python@3.12"
  echo ""
  echo "   Then re-run: bash quickstart.sh"
  exit 1
fi

PY_VER=$($PYTHON --version 2>&1)
echo "✔ Using: $PY_VER  ($PYTHON)"
echo ""

# ── Remove old broken venv if it used an incompatible Python ──────────────────
if [ -d "venv" ]; then
  VENV_VER=$(venv/bin/python --version 2>/dev/null || echo "unknown")
  if [[ "$VENV_VER" == *"3.14"* ]] || [[ "$VENV_VER" == *"3.13"* ]]; then
    echo "⚠️  Removing old incompatible venv ($VENV_VER)..."
    rm -rf venv
  fi
fi

# ── Create venv ────────────────────────────────────────────────────────────────
if [ ! -d "venv" ]; then
  echo "▶ Creating virtual environment with $PYTHON..."
  $PYTHON -m venv venv
fi

echo "▶ Activating venv..."
source venv/bin/activate

ACTIVE_VER=$(python --version 2>&1)
echo "✔ Active: $ACTIVE_VER"
echo ""

# ── Install dependencies (pinned versions compatible with Python 3.12 + M1) ───
echo "▶ Installing dependencies (takes ~1 min)..."
pip install --upgrade pip --quiet

pip install \
  "pandas==2.2.2" \
  "numpy==1.26.4" \
  "ta==0.11.0" \
  "colorlog==6.8.2" \
  "pytest==8.1.1" \
  "pytest-asyncio==0.23.6" \
  "tabulate==0.9.0" \
  "python-dotenv==1.0.1" \
  "anthropic==0.25.0" \
  "requests==2.31.0" \
  "schedule==1.2.1" \
  --quiet

echo "✔ All dependencies installed."
echo ""

# ── .env setup ─────────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "▶ Creating .env from template..."
  cp .env.example .env
  echo "   ➡️  Edit .env and add your API keys for live mode."
  echo ""
fi

# ── Run tests ──────────────────────────────────────────────────────────────────
echo "▶ Running test suite..."
echo "──────────────────────────────────────────────────"
pytest tests/test_agents.py -v --tb=short
echo "──────────────────────────────────────────────────"
echo ""

# ── Run offline demo ───────────────────────────────────────────────────────────
echo "▶ Running offline demo (3 cycles, no API keys needed)..."
echo "──────────────────────────────────────────────────"
python main.py --cycles 3 --delay 1
echo "──────────────────────────────────────────────────"
echo ""

# ── Open report ────────────────────────────────────────────────────────────────
REPORT=$(ls -t reports/report_*.html 2>/dev/null | head -1)
if [ -n "$REPORT" ]; then
  echo "▶ Opening report in browser..."
  open "$REPORT"
fi

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅ Setup complete!                              ║"
echo "║                                                  ║"
echo "║  Next steps:                                     ║"
echo "║  1. Add API keys to .env                         ║"
echo "║  2. source venv/bin/activate                     ║"
echo "║  3. python main.py --live   (paper trading)      ║"
echo "║  4. bash setup_git.sh       (push to GitHub)     ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
