#!/bin/bash
# Yggdrasil LLM Infrastructure Setup
# Configures all hosts with their model suite

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║   Yggdrasil LLM Infrastructure Setup                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Detect which host we're on
HOSTNAME=$(hostname)

case "$HOSTNAME" in
    surtr|surtr.*)
        echo "Running on Surtr (RTX 2070)"
        echo "Setting up: granite-code:8b (port 8080) + gpt-oss:20b (port 8081)"
        echo ""
        $SCRIPT_DIR/setup-surtr-llms.sh
        ;;
    fenrir|fenrir.*)
        echo "Running on Fenrir (RTX 4050 + 64GB RAM)"
        echo "Setting up: granite3.1-moe:3b (port 8080) + qwen2.5:7b (port 8081)"
        echo ""
        $SCRIPT_DIR/setup-fenrir-llms.sh
        ;;
    skadi|skadi.*)
        echo "Running on Skadi (GTX 1650 Ti)"
        echo "Setting up: granite3.1-moe:1b (port 8080)"
        echo ""
        $SCRIPT_DIR/setup-skadi-llms.sh
        ;;
    *)
        echo "ERROR: Unknown host: $HOSTNAME"
        echo ""
        echo "This script must be run on one of:"
        echo "  - surtr (RTX 2070)"
        echo "  - fenrir (RTX 4050)"  
        echo "  - skadi (GTX 1650 Ti)"
        echo ""
        echo "Or manually run:"
        echo "  $SCRIPT_DIR/setup-surtr-llms.sh    # On surtr"
        echo "  $SCRIPT_DIR/setup-fenrir-llms.sh   # On fenrir"
        echo "  $SCRIPT_DIR/setup-skadi-llms.sh    # On skadi"
        exit 1
        ;;
esac

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║   Setup Complete!                                         ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Run on each host (surtr, fenrir, skadi)"
echo "  2. Wait for models to load (check with 'podman logs')"
echo "  3. Run: ygg status  (from main machine)"
echo ""
