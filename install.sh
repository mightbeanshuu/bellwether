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
# Prefer pip's console-script entry point: it runs with a clean sys.path, so it
# is never shadowed by a same-named folder in the current directory (unlike
# `python -m bellwether`, which injects cwd onto the path).
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
if [ -x "$VENV/bin/bellwether" ]; then
  exec "$VENV/bin/bellwether" "\$@"
else
  exec "$VENV/bin/python" -m bellwether "\$@"
fi
EOF
chmod +x "$LAUNCHER"
echo "  • launcher installed at $LAUNCHER"

# 3) make sure BIN_DIR is on PATH, persisting to the right shell profile
NEEDS_SOURCE=""
case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;  # already on PATH
  *)
    case "$(basename "${SHELL:-/bin/zsh}")" in
      zsh)  RC="$HOME/.zshrc" ;;
      bash) RC="$HOME/.bashrc" ;;
      *)    RC="$HOME/.profile" ;;
    esac
    LINE="export PATH=\"$BIN_DIR:\$PATH\""
    if [ ! -f "$RC" ] || ! grep -qF "$BIN_DIR" "$RC"; then
      printf '\n# Added by Bellwether installer\n%s\n' "$LINE" >> "$RC"
      echo "  • added $BIN_DIR to PATH in $RC"
    fi
    NEEDS_SOURCE="$RC"
    ;;
esac

echo
echo "✅ Done. Try:  bellwether            (instant crypto scan)"
echo "             bellwether live        (auto-refreshing dashboard)"
echo "             bellwether scan --source yahoo NVDA AAPL"
if [ -n "$NEEDS_SOURCE" ]; then
  echo
  echo "👉 Activate it in THIS terminal now:   source $NEEDS_SOURCE"
  echo "   (new terminal windows will pick it up automatically)"
fi
