#!/usr/bin/env bash
# Install linc_codebuddy as a global CLI command.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
WRAPPER="${BIN_DIR}/linc-codebuddy"

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

echo "Installed: ${WRAPPER}"

# Prompt the user to add ~/.local/bin to PATH if needed
if ! echo "$PATH" | tr ':' '\n' | grep -qF "$BIN_DIR"; then
    echo ""
    echo "Add this line to your shell profile (~/.zshrc or ~/.bashrc):"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
