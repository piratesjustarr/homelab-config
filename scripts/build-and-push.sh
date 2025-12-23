#!/bin/bash
# Build all Yggdrasil agent images and push to registry

set -e

REGISTRY="${REGISTRY:-localhost:5000}"
VERSION="${VERSION:-v0.2.0}"
BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Building Yggdrasil agent images..."
echo "Registry: $REGISTRY"
echo "Version: $VERSION"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Build executor images
for executor in fenrir surtr huginn; do
    echo -e "${BLUE}Building $executor executor...${NC}"
    podman build \
        -t "$REGISTRY/yggdrasil-executor:$VERSION" \
        -t "$REGISTRY/yggdrasil-executor-$executor:$VERSION" \
        --build-arg EXECUTOR_TYPE=$executor \
        -f "$BUILD_DIR/docker/Dockerfile.executor" \
        "$BUILD_DIR"
    
    echo -e "${GREEN}✓ Built $executor executor${NC}"
done

# Tag as latest
echo -e "${BLUE}Tagging as latest...${NC}"
podman tag "$REGISTRY/yggdrasil-executor:$VERSION" "$REGISTRY/yggdrasil-executor:latest"

# Build coordinator
echo -e "${BLUE}Building coordinator...${NC}"
podman build \
    -t "$REGISTRY/yggdrasil-coordinator:$VERSION" \
    -t "$REGISTRY/yggdrasil-coordinator:latest" \
    -f "$BUILD_DIR/docker/Dockerfile.coordinator" \
    "$BUILD_DIR"

echo -e "${GREEN}✓ Built coordinator${NC}"

# Build code agent
echo -e "${BLUE}Building code agent...${NC}"
podman build \
    -t "$REGISTRY/yggdrasil-code-agent:$VERSION" \
    -t "$REGISTRY/yggdrasil-code-agent:latest" \
    -f "$BUILD_DIR/docker/Dockerfile.code-agent" \
    "$BUILD_DIR"

echo -e "${GREEN}✓ Built code agent${NC}"

# Push to registry if not localhost
if [[ "$REGISTRY" != "localhost:5000" ]]; then
    echo -e "${BLUE}Pushing images to $REGISTRY...${NC}"
    podman push "$REGISTRY/yggdrasil-executor:$VERSION"
    podman push "$REGISTRY/yggdrasil-executor:latest"
    podman push "$REGISTRY/yggdrasil-coordinator:$VERSION"
    podman push "$REGISTRY/yggdrasil-coordinator:latest"
    podman push "$REGISTRY/yggdrasil-code-agent:$VERSION"
    podman push "$REGISTRY/yggdrasil-code-agent:latest"
    echo -e "${GREEN}✓ Pushed to registry${NC}"
fi

echo -e "${GREEN}Build complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Deploy registry: ./scripts/deploy-registry.sh"
echo "2. Deploy executors: ./scripts/deploy-executors.sh"
echo "3. Deploy code agent: ./scripts/deploy-code-agent.sh"
