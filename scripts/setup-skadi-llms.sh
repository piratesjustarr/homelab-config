#!/bin/bash
# Skadi LLM Setup Script
# GTX 1650 Ti (4GB)
# Sets up granite3.1-moe:1b (ultra-fast)

set -e

SKADI_HOST="skadi.nessie-hippocampus.ts.net"
PORT=8080

echo "=== Skadi LLM Setup ==="
echo "Setting up model on $SKADI_HOST"
echo ""

# Check if ramalama is installed
if ! command -v ramalama &> /dev/null; then
    echo "ERROR: ramalama not found. Install with:"
    echo "  brew install container-tools/skopeo/ramalama"
    exit 1
fi

echo "[1/1] Starting granite3.1-moe:1b on :$PORT (ultra-fast simple tasks)"
ramalama serve -d \
    --name skadi-fast \
    --port $PORT \
    --host 0.0.0.0 \
    ollama://granite3.1-moe:1b

echo "Waiting for model to start..."
sleep 3

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Verifying model..."
echo ""

# Check if port is responding
if curl -s http://localhost:$PORT/v1/models | jq . > /dev/null 2>&1; then
    echo "✓ granite3.1-moe:1b on :$PORT is responding"
else
    echo "✗ granite3.1-moe:1b on :$PORT not responding yet (may still be loading)"
fi

echo ""
echo "Model running:"
podman ps --filter "name=skadi" --format "{{.Names}}\t{{.Ports}}"

echo ""
echo "To check status:"
echo "  podman logs skadi-fast"
echo ""
echo "To stop model:"
echo "  podman stop skadi-fast"
