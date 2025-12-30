#!/bin/bash
# Yggdrasil BeeAI Agent Container
# Runs the agent in Python 3.12 for BeeAI compatibility

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEADS_DIR="/var/home/matt/homelab-config/yggdrasil-beads"
VAULT_DIR="/var/home/matt/obsidian-vault"
CONTAINER_NAME="ygg-beeai"
IMAGE_NAME="yggdrasil-beeai:latest"

echo "=== Yggdrasil BeeAI Agent ==="
echo ""

# Build image if not exists
if ! podman image exists $IMAGE_NAME 2>/dev/null; then
    echo "Building BeeAI image..."
    podman build -f "$SCRIPT_DIR/Dockerfile.beeai" -t $IMAGE_NAME "$SCRIPT_DIR"
    echo "✓ Image built"
    echo ""
fi

# Parse command
CMD="${1:-status}"

case "$CMD" in
    status|run|sync|loop)
        echo "Running: ygg $CMD"
        podman run --rm \
            --network host \
            -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
            -v "$BEADS_DIR:/beads:Z" \
            -v "$VAULT_DIR:/vault:Z" \
            -v "$SCRIPT_DIR:/app:Z" \
            $IMAGE_NAME $CMD
        ;;
    build)
        echo "Building image..."
        podman build -f "$SCRIPT_DIR/Dockerfile.beeai" -t $IMAGE_NAME "$SCRIPT_DIR"
        echo "✓ Image built: $IMAGE_NAME"
        ;;
    shell)
        echo "Starting shell in BeeAI container..."
        podman run -it --rm \
            --network host \
            -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
            -v "$BEADS_DIR:/beads:Z" \
            -v "$VAULT_DIR:/vault:Z" \
            -v "$SCRIPT_DIR:/app:Z" \
            $IMAGE_NAME /bin/bash
        ;;
    *)
        echo "Unknown command: $CMD"
        echo ""
        echo "Usage: $0 {status|run|sync|loop|build|shell}"
        exit 1
        ;;
esac
