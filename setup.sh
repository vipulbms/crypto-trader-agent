#!/usr/bin/env bash
# setup.sh — Kryptos automated setup script
# Usage: ./setup.sh
set -e

PYTHON_MIN="3.11"
VENV_DIR=".venv"
ENV_FILE=".env"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'  # No Colour

info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
success() { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     Kryptos — Setup Script           ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""

# ── 1. Check Python version ───────────────────────────────────────────────────
info "Checking Python version..."

PYTHON_BIN=""
for cmd in python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VERSION=$("$cmd" --version 2>&1 | awk '{print $2}')
        MAJOR=$(echo "$VERSION" | cut -d. -f1)
        MINOR=$(echo "$VERSION" | cut -d. -f2)
        if [[ "$MAJOR" -ge 3 && "$MINOR" -ge 11 ]]; then
            PYTHON_BIN="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    error "Python $PYTHON_MIN or higher is required but was not found.
       Install it from https://python.org and re-run setup.sh."
fi

success "Python $VERSION found at: $(command -v $PYTHON_BIN)"

# ── 2. Create virtual environment ─────────────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
    warn "Virtual environment '$VENV_DIR' already exists — skipping creation."
else
    info "Creating virtual environment in '$VENV_DIR'..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    success "Virtual environment created."
fi

# Activate venv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── 3. Upgrade pip ────────────────────────────────────────────────────────────
info "Upgrading pip..."
pip install --quiet --upgrade pip
success "pip upgraded."

# ── 4. Install dependencies ───────────────────────────────────────────────────
info "Installing Python dependencies from requirements.txt..."
pip install --quiet -r requirements.txt
success "Dependencies installed."

# ── 5. Create required directories ───────────────────────────────────────────
info "Creating data/ and logs/ directories..."
mkdir -p data logs
success "Directories ready."

# ── 6. Choose LLM provider ───────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Choose your LLM provider:${NC}"
echo "  1) Groq        — Free API, fast, cloud (recommended)"
echo "  2) Google Gemini — Free tier, cloud"
echo "  3) Ollama      — Local/private, no API key needed"
echo ""
read -rp "Enter choice [1/2/3]: " LLM_CHOICE

LLM_API_KEY_VAR=""
LLM_HINT=""

case "$LLM_CHOICE" in
    1)
        LLM_API_KEY_VAR="GROQ_API_KEY"
        LLM_HINT="Get a free key at: https://console.groq.com"
        ;;
    2)
        LLM_API_KEY_VAR="GEMINI_API_KEY"
        LLM_HINT="Get a free key at: https://aistudio.google.com"
        ;;
    3)
        warn "Ollama selected. Ensure 'ollama serve' is running before starting Kryptos."
        warn "Pull a model: ollama pull qwen2.5:14b"
        warn "Update config.yaml → llm.provider to 'ollama' and llm.model to your model name."
        LLM_API_KEY_VAR=""
        LLM_HINT=""
        ;;
    *)
        warn "Invalid choice. Defaulting to Groq."
        LLM_API_KEY_VAR="GROQ_API_KEY"
        LLM_HINT="Get a free key at: https://console.groq.com"
        ;;
esac

# ── 7. Write .env template ───────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    warn ".env already exists — will not overwrite. Edit it manually if needed."
else
    info "Writing .env template..."
    {
        echo "# ================================================================"
        echo "# Kryptos .env — DO NOT COMMIT THIS FILE"
        echo "# ================================================================"
        echo ""
        if [[ -n "$LLM_API_KEY_VAR" ]]; then
            echo "# LLM Provider API Key"
            echo "# $LLM_HINT"
            echo "${LLM_API_KEY_VAR}=your_key_here"
            echo ""
        fi
        echo "# Kraken API (only required for live mode)"
        echo "KRAKEN_API_KEY="
        echo "KRAKEN_API_SECRET="
        echo ""
        echo "# Telegram Notifications (optional but recommended)"
        echo "# See SETUP.md §8 for how to get these values"
        echo "TELEGRAM_BOT_TOKEN="
        echo "TELEGRAM_CHAT_ID="
    } > "$ENV_FILE"
    success ".env template written. Fill in your API key before starting."
fi

# ── 8. Summary ────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║  Setup complete!  Next steps:                            ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

if [[ -n "$LLM_API_KEY_VAR" ]]; then
    echo -e "  1. Edit ${BOLD}.env${NC} and set ${BOLD}${LLM_API_KEY_VAR}${NC}"
    echo -e "     ${LLM_HINT}"
    echo ""
fi

echo -e "  2. Activate virtual environment:"
echo -e "     ${BOLD}source $VENV_DIR/bin/activate${NC}"
echo ""
echo -e "  3. Start paper trading:"
echo -e "     ${BOLD}python main.py --paper${NC}"
echo ""
echo -e "  4. Open the interactive CLI (in a second terminal):"
echo -e "     ${BOLD}python kryptos.py${NC}"
echo ""
echo -e "  5. Watch the logs:"
echo -e "     ${BOLD}tail -f logs/agent.log${NC}"
echo ""
echo -e "  Full setup guide: ${BOLD}SETUP.md${NC}"
echo ""
