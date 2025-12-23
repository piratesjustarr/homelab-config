#!/usr/bin/env fish
# Deploy private OCI registry on Surtr
# Usage: ./scripts/deploy-registry.sh <surtr-host>

set SURTR_HOST (string join '' $argv[1] '')
test -z "$SURTR_HOST"; and set SURTR_HOST "surtr"
set REGISTRY_PORT (string join '' $argv[2] '')
test -z "$REGISTRY_PORT"; and set REGISTRY_PORT "5000"
set REGISTRY_UI_PORT (string join '' $argv[3] '')
test -z "$REGISTRY_UI_PORT"; and set REGISTRY_UI_PORT "8080"

echo "📦 Deploying Yggdrasil Registry to $SURTR_HOST..."

# Copy docker files to Surtr
echo "📋 Copying docker-compose files..."
scp ../docker/docker-compose.registry.yml "$SURTR_HOST":/tmp/docker-compose.registry.yml
scp ../docker/registry-config.yml "$SURTR_HOST":/tmp/registry-config.yml

# Create temp setup script
set TEMP_SCRIPT /tmp/deploy-registry-setup.fish
echo '#!/usr/bin/env fish' > $TEMP_SCRIPT
echo 'echo "🚀 Starting registry setup..."' >> $TEMP_SCRIPT
echo 'mkdir -p ~/yggdrasil-registry' >> $TEMP_SCRIPT
echo 'cd ~/yggdrasil-registry' >> $TEMP_SCRIPT
echo 'cp /tmp/docker-compose.registry.yml ./docker-compose.yml' >> $TEMP_SCRIPT
echo 'cp /tmp/registry-config.yml ./registry-config.yml' >> $TEMP_SCRIPT
echo 'which docker-compose &>/dev/null; or which podman-compose &>/dev/null; or which /usr/bin/docker-compose &>/dev/null' >> $TEMP_SCRIPT
echo 'set COMPOSE_CMD (which podman-compose; or which docker-compose; or echo /usr/bin/docker-compose)' >> $TEMP_SCRIPT
echo '$COMPOSE_CMD up -d' >> $TEMP_SCRIPT
echo 'echo "⏳ Quick health check (5 attempts)..."' >> $TEMP_SCRIPT
echo 'set timeout 0' >> $TEMP_SCRIPT
echo 'while test $timeout -lt 5' >> $TEMP_SCRIPT
echo '  sleep 1' >> $TEMP_SCRIPT
echo '  curl -f http://localhost:5000/v2/ >/dev/null 2>&1; and break' >> $TEMP_SCRIPT
echo '  set timeout (math $timeout + 1)' >> $TEMP_SCRIPT
echo 'end' >> $TEMP_SCRIPT
echo 'if test $timeout -lt 5' >> $TEMP_SCRIPT
echo '  echo "✅ Registry is responding!"' >> $TEMP_SCRIPT
echo 'else' >> $TEMP_SCRIPT
echo '  echo "⚠️  Registry may still be starting (check with: $COMPOSE_CMD ps)"' >> $TEMP_SCRIPT
echo 'end' >> $TEMP_SCRIPT
echo 'echo ""' >> $TEMP_SCRIPT
echo 'echo "📊 Registry Status:"' >> $TEMP_SCRIPT
echo '$COMPOSE_CMD ps' >> $TEMP_SCRIPT
echo 'echo ""' >> $TEMP_SCRIPT
echo 'echo "🔗 URLs:"' >> $TEMP_SCRIPT
echo 'echo "  Registry: http://(hostname -s):5000"' >> $TEMP_SCRIPT
echo 'echo "  UI: http://(hostname -s):8080"' >> $TEMP_SCRIPT

# Copy and execute on Surtr
scp $TEMP_SCRIPT "$SURTR_HOST":/tmp/deploy-registry-setup.fish
ssh "$SURTR_HOST" fish /tmp/deploy-registry-setup.fish
rm $TEMP_SCRIPT

echo "✅ Registry deployed successfully!"
