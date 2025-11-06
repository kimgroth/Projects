#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "[ffarm] Starting macOS install"

if ! xcode-select -p >/dev/null 2>&1; then
  echo "[ffarm] Installing Xcode Command Line Tools..."
  xcode-select --install || true
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "[ffarm] Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

brew update

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[ffarm] Installing FFmpeg..."
  brew install ffmpeg
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ffarm] Installing Python 3..."
  brew install python@3
fi

if [ ! -d "$ROOT_DIR/.venv" ]; then
  echo "[ffarm] Creating virtual environment..."
  python3 -m venv "$ROOT_DIR/.venv"
fi

source "$ROOT_DIR/.venv/bin/activate"
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "[ffarm] Install complete."
