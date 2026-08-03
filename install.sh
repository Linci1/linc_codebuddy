#!/usr/bin/env bash
# Install linc_codebuddy for direct use from Codex and the shell.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
WRAPPER="${BIN_DIR}/linc-codebuddy"
VENV_DIR="${SKILL_DIR}/.venv-mcp"

mkdir -p "$BIN_DIR"

cat > "$WRAPPER" << 'WRAPPER_EOF'
#!/usr/bin/env bash
# linc_codebuddy — personal development assistant wrapper
SKILL_DIR="SKILL_DIR_PLACEHOLDER"
exec python3 "${SKILL_DIR}/scripts/run_agent.py" "$@"
WRAPPER_EOF

# Replace placeholder with the absolute skill directory path
sed -i '' "s|SKILL_DIR_PLACEHOLDER|${SKILL_DIR}|g" "$WRAPPER"

chmod +x "$WRAPPER"

echo "Installed CLI: ${WRAPPER}"

# Keep MCP dependencies isolated from the system Python.
if command -v uv >/dev/null 2>&1; then
    uv venv --quiet --allow-existing "$VENV_DIR"
    uv pip install --quiet --python "$VENV_DIR/bin/python" -r "$SKILL_DIR/requirements-mcp.txt"
else
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --quiet -r "$SKILL_DIR/requirements-mcp.txt"
fi

python3 "$SKILL_DIR/scripts/install_codex.py" --repo "$SKILL_DIR"

echo "Installed Codex Skill and MCP server. Restart Codex or open a new task to load them."

# Prompt the user to add ~/.local/bin to PATH if needed
if ! echo "$PATH" | tr ':' '\n' | grep -qF "$BIN_DIR"; then
    echo ""
    echo "Add this line to your shell profile (~/.zshrc or ~/.bashrc):"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
