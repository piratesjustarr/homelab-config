#!/bin/bash
# Fenrir LLM Setup Script
# RTX 4050 (6GB) + 64GB RAM
# Sets up granite3.1-moe:3b and qwen2.5:7b

set -e

FENRIR_HOST="fenrir.nessie-hippocampus.ts.net"
PORT1=8080
PORT2=8081

echo "=== Fenrir LLM Setup ==="
echo "Setting up models on $FENRIR_HOST"
echo ""

# Check if ramalama is installed
if ! command -v ramalama &> /dev/null; then
    echo "ERROR: ramalama not found. Install with:"
    echo "  brew install container-tools/skopeo/ramalama"
    exit 1
fi

echo "[1/2] Starting granite3.1-moe:3b on :$PORT1 (MoE - dense on GPU, experts on CPU RAM)"
echo "Using --ngl 32 --n-cpu-moe 8: dense+router on GPU, experts 1-8 on CPU RAM"
ramalama serve -d \
    --name fenrir-fast \
    --port $PORT1 \
    --host 0.0.0.0 \
    --ngl 32 \
    --ctx-size 8192 \
    --threads 8 \
    --runtime-args="--n-cpu-moe 8" \
    ollama://granite3.1-moe:3b

echo "Waiting for model to start..."
sleep 5

echo ""
echo "[2/2] Starting qwen2.5:7b on :$PORT2 (dense model, partial GPU offload)"
echo "Using --ngl 22 --ctx-size 8192: keep ~4.5GB on GPU, rest on CPU RAM"
ramalama serve -d \
    --name fenrir-chat \
    --port $PORT2 \
    --host 0.0.0.0 \
    --ngl 22 \
    --ctx-size 8192 \
    --threads 8 \
    ollama://qwen2.5:7b

echo "Waiting for model to start..."
sleep 5

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Verifying models..."
echo ""

# Check if ports are responding
if curl -s http://localhost:$PORT1/v1/models | jq . > /dev/null 2>&1; then
    echo "✓ granite3.1-moe:3b on :$PORT1 is responding"
else
    echo "✗ granite3.1-moe:3b on :$PORT1 not responding yet (may still be loading)"
fi

if curl -s http://localhost:$PORT2/v1/models | jq . > /dev/null 2>&1; then
    echo "✓ qwen2.5:7b on :$PORT2 is responding"
else
    echo "✗ qwen2.5:7b on :$PORT2 not responding yet (may still be loading)"
fi

echo ""
echo "Models running:"
podman ps --filter "name=fenrir" --format "{{.Names}}\t{{.Ports}}"

echo ""
echo "To check status:"
echo "  podman logs fenrir-fast"
echo "  podman logs fenrir-chat"
echo ""
echo "To stop models:"
echo "  podman stop fenrir-fast fenrir-chat"
