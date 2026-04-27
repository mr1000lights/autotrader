#!/bin/bash
# setup_git.sh — Initialize repo and push to GitHub
# Run this from inside your autotrader/ folder

set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   AutoTrader — Git Setup & Push Script   ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Step 1: init repo ──────────────────────────────────────────────────────────
echo "▶ Initialising git repo..."
git init
git branch -M main

# ── Step 2: stage all files ────────────────────────────────────────────────────
echo "▶ Staging files..."
git add .
git status

# ── Step 3: first commit ───────────────────────────────────────────────────────
echo "▶ Creating initial commit..."
git commit -m "🚀 Initial commit — AutoTrader multi-agent system

Agents:
  - MarketAgent   : RSI, MACD, Bollinger Bands, trend scoring
  - RiskAgent     : Position sizing, daily loss limit, SL/TP
  - ExecutionAgent: Simulated order fills, SL/TP exit triggers
  - LoggerAgent   : JSON event log + HTML performance reports
  - Orchestrator  : Coordinates all agents + Claude AI second opinions

Tests:
  - Full pytest suite for all agents
  - End-to-end 3-cycle simulation test

Config: .env.example provided — copy to .env and add API keys"

# ── Step 4: add remote & push ──────────────────────────────────────────────────
echo ""
echo "▶ Adding GitHub remote..."
echo "   You need to create the repo first at:"
echo "   https://github.com/new  (name it: autotrader)"
echo ""
read -p "   Press ENTER once you've created the repo on GitHub..."

git remote add origin https://github.com/mr1000lights/autotrader.git
echo "▶ Pushing to GitHub..."
git push -u origin main

echo ""
echo "✅ Done! Repo live at: https://github.com/mr1000lights/autotrader"
echo ""
