#!/usr/bin/env fish
# Deploy executor agent on target machine
# Usage: ./scripts/deploy-executor.sh <host> <executor-type> [registry]

set HOST (string join '' $argv[1] '')
set EXECUTOR_TYPE (string join '' $argv[2] '')
set REGISTRY (string join '' $argv[3] '')
test -z "$REGISTRY"; and set REGISTRY "surtr:5000"

if test -z "$HOST" -o -z "$EXECUTOR_TYPE"
  echo "Usage: ./scripts/deploy-executor.sh <host> <executor-type> [registry]"
  echo "Example: ./scripts/deploy-executor.sh fenrir fenrir surtr:5000"
  exit 1
end

echo "📦 Deploying $EXECUTOR_TYPE executor to $HOST..."
echo "Registry: $REGISTRY"

# Create temp setup script
set TEMP_SCRIPT /tmp/deploy-executor-setup.fish
echo '#!/usr/bin/env fish' > $TEMP_SCRIPT
echo "echo '🚀 Starting executor setup on $EXECUTOR_TYPE...'" >> $TEMP_SCRIPT
echo 'mkdir -p ~/yggdrasil-executor' >> $TEMP_SCRIPT
echo 'cd ~/yggdrasil-executor' >> $TEMP_SCRIPT
echo "set IMAGE '$REGISTRY/yggdrasil-executor-$EXECUTOR_TYPE:latest'" >> $TEMP_SCRIPT
echo 'echo "Pulling image: \$IMAGE"' >> $TEMP_SCRIPT
echo 'podman pull --tls-verify=false $IMAGE 2>&1 | head -5' >> $TEMP_SCRIPT
echo 'podman rm -f executor 2>/dev/null' >> $TEMP_SCRIPT
echo 'echo "Starting container..."' >> $TEMP_SCRIPT
echo "podman run -d --name executor -p 5000:5000 --network=host --tls-verify=false \$IMAGE" >> $TEMP_SCRIPT
echo 'sleep 2' >> $TEMP_SCRIPT
echo 'echo "✅ Executor deployed"' >> $TEMP_SCRIPT
echo 'echo ""' >> $TEMP_SCRIPT
echo 'echo "📊 Status:"' >> $TEMP_SCRIPT
echo 'podman ps | grep executor' >> $TEMP_SCRIPT
echo 'echo ""' >> $TEMP_SCRIPT
echo 'echo "🔗 Health check:"' >> $TEMP_SCRIPT
echo 'curl -s http://localhost:5000/health | jq .' >> $TEMP_SCRIPT

# Copy and execute on target
scp $TEMP_SCRIPT "$HOST":/tmp/deploy-executor-setup.fish
ssh "$HOST" fish /tmp/deploy-executor-setup.fish
rm $TEMP_SCRIPT

echo "✅ Executor deployment complete!"
