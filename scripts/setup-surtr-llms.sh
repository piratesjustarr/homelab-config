#!/bin/bash
# Surtr LLM Setup Script  
# RTX 2070 (8GB)
# Sets up granite-code:8b and gpt-oss:20b

set -e

SURTR_HOST="surtr.nessie-hippocampus.ts.net"
PORT1=8080
PORT2=8081

echo "=== Surtr LLM Setup ==="
echo "Setting up models on $SURTR_HOST"
echo ""

# Check if ramalama is installed
if ! command -v ramalama &> /dev/null; then
    echo "ERROR: ramalama not found. Install with:"
    echo "  brew install container-tools/skopeo/ramalama"
    exit 1
fi

echo "[1/2] Starting granite-code:8b on :$PORT1 (code generation)"
ramalama serve -d \
    --name surtr-code \
    --port $PORT1 \
    --host 0.0.0.0 \
    ollama://granite-code:8b

echo "Waiting for model to start..."
sleep 5

echo ""
echo "[2/2] Starting gpt-oss:20b on :$PORT2 (reasoning)"
echo "This is a large model - may take time to load"
ramalama serve -d \
    --name surtr-reasoning \
    --port $PORT2 \
    --host 0.0.0.0 \
    ollama://gpt-oss:20b

echo "Waiting for model to start..."
sleep 10

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Verifying models..."
echo ""

# Check if ports are responding
if curl -s http://localhost:$PORT1/v1/models | jq . > /dev/null 2>&1; then
    echo "✓ granite-code:8b on :$PORT1 is responding"
else
    echo "✗ granite-code:8b on :$PORT1 not responding yet (may still be loading)"
fi

if curl -s http://localhost:$PORT2/v1/models | jq . > /dev/null 2>&1; then
    echo "✓ gpt-oss:20b on :$PORT2 is responding"
else
    echo "✗ gpt-oss:20b on :$PORT2 not responding yet (may still be loading)"
fi

echo ""
echo "Models running:"
podman ps --filter "name=surtr" --format "{{.Names}}\t{{.Ports}}"

echo ""
echo "To check status:"
echo "  podman logs surtr-code"
echo "  podman logs surtr-reasoning"
echo ""
echo "To stop models:"
echo "  podman stop surtr-code surtr-reasoning"
