#!/usr/bin/env fish
# Build all Yggdrasil agent images and push to registry

set REGISTRY (string join '' $REGISTRY '')
test -z "$REGISTRY"; and set REGISTRY "localhost:5000"
set VERSION (string join '' $VERSION '')
test -z "$VERSION"; and set VERSION "v0.2.0"
set BUILD_DIR (cd (dirname (status filename))/.. && pwd)

echo "Building Yggdrasil agent images..."
echo "Registry: $REGISTRY"
echo "Version: $VERSION"

# Colors for output
set GREEN '\033[0;32m'
set BLUE '\033[0;34m'
set NC '\033[0m'

# Build executor images
for executor in fenrir surtr huginn
    echo -e "$BLUE"Building $executor executor..."$NC"
    podman build \
        -t "$REGISTRY/yggdrasil-executor:$VERSION" \
        -t "$REGISTRY/yggdrasil-executor-$executor:$VERSION" \
        --build-arg EXECUTOR_TYPE=$executor \
        -f "$BUILD_DIR/docker/Dockerfile.executor" \
        "$BUILD_DIR"
    
    echo -e "$GREEN"✓ Built $executor executor"$NC"
end

# Tag as latest
echo -e "$BLUE"Tagging as latest..."$NC"
podman tag "$REGISTRY/yggdrasil-executor:$VERSION" "$REGISTRY/yggdrasil-executor:latest"

# Build coordinator
echo -e "$BLUE"Building coordinator..."$NC"
podman build \
    -t "$REGISTRY/yggdrasil-coordinator:$VERSION" \
    -t "$REGISTRY/yggdrasil-coordinator:latest" \
    -f "$BUILD_DIR/docker/Dockerfile.coordinator" \
    "$BUILD_DIR"

echo -e "$GREEN"✓ Built coordinator"$NC"

# Build code agent
echo -e "$BLUE"Building code agent..."$NC"
podman build \
    -t "$REGISTRY/yggdrasil-code-agent:$VERSION" \
    -t "$REGISTRY/yggdrasil-code-agent:latest" \
    -f "$BUILD_DIR/docker/Dockerfile.code-agent" \
    "$BUILD_DIR"

echo -e "$GREEN"✓ Built code agent"$NC"

# Build text agent
echo -e "$BLUE"Building text agent..."$NC"
podman build \
    -t "$REGISTRY/yggdrasil-text-agent:$VERSION" \
    -t "$REGISTRY/yggdrasil-text-agent:latest" \
    -f "$BUILD_DIR/docker/Dockerfile.text-agent" \
    "$BUILD_DIR"

echo -e "$GREEN"✓ Built text agent"$NC"

# Push to registry if not localhost
if test "$REGISTRY" != "localhost:5000"
    echo -e "$BLUE"Pushing images to $REGISTRY..."$NC"
    set PUSH_OPTS "--tls-verify=false"
    podman push $PUSH_OPTS "$REGISTRY/yggdrasil-executor:$VERSION"
    podman push $PUSH_OPTS "$REGISTRY/yggdrasil-executor:latest"
    podman push $PUSH_OPTS "$REGISTRY/yggdrasil-coordinator:$VERSION"
    podman push $PUSH_OPTS "$REGISTRY/yggdrasil-coordinator:latest"
    podman push $PUSH_OPTS "$REGISTRY/yggdrasil-code-agent:$VERSION"
    podman push $PUSH_OPTS "$REGISTRY/yggdrasil-code-agent:latest"
    podman push $PUSH_OPTS "$REGISTRY/yggdrasil-text-agent:$VERSION"
    podman push $PUSH_OPTS "$REGISTRY/yggdrasil-text-agent:latest"
    echo -e "$GREEN"✓ Pushed to registry"$NC"
end

echo -e "$GREEN"Build complete!"$NC"
echo ""
echo "Next steps:"
echo "1. Deploy registry: ./scripts/deploy-registry.sh"
echo "2. Deploy executors: ./scripts/deploy-executors.sh"
echo "3. Deploy code agent: ./scripts/deploy-code-agent.sh"
echo "4. Deploy text agent: ./scripts/deploy-text-agent.sh"
