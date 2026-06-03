#!/usr/bin/env bash
# Bellwether one-command installer.
#   curl -fsSL .../install.sh | bash      (or just: ./install.sh)
# Creates an isolated venv, installs everything, and drops a `bellwether`
# launcher on your PATH so you can run the engine by typing `bellwether`.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_DIR/.venv"
BIN_DIR="${BELLWETHER_BIN:-$HOME/.local/bin}"
PY="${PYTHON:-python3}"

echo "🐏 Installing Bellwether from $REPO_DIR"

# 1) venv + dependencies
if [ ! -d "$VENV" ]; then
  echo "  • creating virtualenv …"
  "$PY" -m venv "$VENV"
fi
echo "  • installing dependencies …"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -e "$REPO_DIR"

# 2) launcher on PATH
mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/bellwether"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" -m bellwether "\$@"
EOF
chmod +x "$LAUNCHER"

echo "  • launcher installed at $LAUNCHER"
echo
if ! command -v bellwether >/dev/null 2>&1; then
  echo "⚠️  $BIN_DIR is not on your PATH. Add this to your shell profile:"
  echo "     export PATH=\"$BIN_DIR:\$PATH\""
  echo
fi
echo "✅ Done. Try:  bellwether            (instant crypto scan)"
echo "             bellwether live        (auto-refreshing dashboard)"
echo "             bellwether scan --source yahoo NVDA AAPL"
