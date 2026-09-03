#!/usr/bin/env bash
# Install GameSphere Import Tool on Linux (Bazzite, Steam Deck, generic).
set -euo pipefail

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
BIN_LINK="${GAMESPHERE_IMPORT_BIN:-$HOME/.local/bin/gamesphere-import}"

echo "==> GameSphere Import Tool — Linux setup"
echo "    Install dir: $INSTALL_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "==> Updating existing checkout..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "==> Cloning repository..."
  git clone https://github.com/trevlars/Gamesphere-Import-Tool.git "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
uv sync

echo "==> Writing .env from auto-detected paths..."
uv run main.py --auto-config

mkdir -p "$(dirname "$BIN_LINK")"
cat >"$BIN_LINK" <<EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR"
exec uv run main.py "\$@"
EOF
chmod +x "$BIN_LINK"

echo ""
echo "Done. Run:"
echo "  gamesphere-import --dry-run    # preview"
echo "  gamesphere-import              # import Steam library into Sunshine"
echo ""
echo "Optional DeckyLoader plugin: see decky/README.md"
