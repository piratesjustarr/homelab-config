# Yggdrasil Private OCI Registry Setup

**Task**: [Beads yggdrasil-beads-2e5.3]  
**Status**: In Progress  
**Purpose**: Host container images for agents (executor, coordinator, code-agent) on Surtr

---

## Architecture

- **Registry Service**: Docker Registry v2 on Surtr port 5000
- **UI**: Joxit Registry UI on port 8080 (for browsing images)
- **Storage**: Docker volume `registry-data` (persistent)
- **Network**: Local network, Tailscale accessible

---

## Deployment Steps

### Option 1: Automated (Recommended)

From `~/homelab-config`:

```bash
./scripts/deploy-registry.sh surtr 5000 8080
```

This will:
1. Copy docker-compose files to Surtr
2. Create `/home/$USER/yggdrasil-registry` directory
3. Start registry + UI containers
4. Health-check registry endpoint
5. Display service URLs

### Option 2: Manual Deployment

SSH into Surtr:

```bash
ssh surtr

# Create working directory
mkdir -p ~/yggdrasil-registry
cd ~/yggdrasil-registry

# Copy config files (from local first)
# Assume docker-compose.registry.yml and registry-config.yml are in place
```

From local machine:

```bash
scp ~/homelab-config/docker/docker-compose.registry.yml surtr:~/yggdrasil-registry/docker-compose.yml
scp ~/homelab-config/docker/registry-config.yml surtr:~/yggdrasil-registry/registry-config.yml
```

Back on Surtr:

```bash
cd ~/yggdrasil-registry
docker-compose up -d
docker-compose ps
```

---

## Verification

### Check Registry Health

```bash
# From Surtr or any machine with network access
curl http://surtr:5000/v2/

# Expected response: empty JSON object {}
```

### List Images

```bash
curl http://surtr:5000/v2/_catalog
```

### Access UI

Open browser: `http://surtr:8080`

---

## Pushing Images

### Build & Tag

```bash
cd ~/homelab-config

# Build executor image
docker build -f docker/Dockerfile.executor -t surtr:5000/yggdrasil/executor:latest .

# Build coordinator image
docker build -f docker/Dockerfile.coordinator -t surtr:5000/yggdrasil/coordinator:latest .

# Build code-agent image
docker build -f docker/Dockerfile.code-agent -t surtr:5000/yggdrasil/code-agent:latest .
```

### Push to Registry

```bash
docker push surtr:5000/yggdrasil/executor:latest
docker push surtr:5000/yggdrasil/coordinator:latest
docker push surtr:5000/yggdrasil/code-agent:latest
```

---

## Pulling Images on Other Machines

### Fenrir / Huginn (if not on Surtr's network)

Configure Docker daemon (`/etc/docker/daemon.json`):

```json
{
  "insecure-registries": ["surtr:5000"]
}
```

Then:

```bash
docker pull surtr:5000/yggdrasil/executor:latest
docker pull surtr:5000/yggdrasil/coordinator:latest
docker pull surtr:5000/yggdrasil/code-agent:latest
```

---

## Troubleshooting

### Registry not accessible

Check if registry container is running:

```bash
ssh surtr "docker ps | grep yggdrasil-registry"
```

Check logs:

```bash
ssh surtr "docker logs yggdrasil-registry"
```

### Permission denied on volume

Ensure registry volume has proper permissions:

```bash
ssh surtr "docker exec yggdrasil-registry ls -la /var/lib/registry"
```

### Pull fails (untrusted registry)

Use `--insecure-registries` in Docker daemon config (see above).

---

## Related Tasks

- [yggdrasil-beads-2e5.2]: Build all container images
- [yggdrasil-beads-2e5.4]: Deploy executor on Fenrir
- [yggdrasil-beads-2e5.5]: Deploy executor on Huginn
- [yggdrasil-beads-2e5.6]: Deploy code-agent on Surtr

---

*Created: 2025-12-23*
