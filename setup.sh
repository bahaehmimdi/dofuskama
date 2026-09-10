#!/usr/bin/env bash
# dofuskama setup — macOS / Linux / WSL / Git Bash
set -e

cd "$(dirname "$0")"

PYTHON=python3
command -v python3 >/dev/null 2>&1 || PYTHON=python

echo "== Using $($PYTHON --version) =="

$PYTHON -m venv .venv

if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
else
    source .venv/Scripts/activate
fi

pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "== Created .env from .env.example — edit it now and set DISCORD_TOKEN =="
else
    echo "== .env already exists, left untouched =="
fi

echo ""
echo "== Setup done =="
echo "1) Edit .env and set DISCORD_TOKEN (and GUILD_ID for instant command sync)."
echo "2) Run the bot:"
echo "   source .venv/bin/activate   (or .venv/Scripts/activate on Windows)"
echo "   python3 bot.py"
echo ""
echo "== Cloudflare Worker (privacy/terms pages), optional =="
echo "   cd worker"
echo "   wrangler login"
echo "   wrangler deploy"
