# Yggdrasil Private OCI Registry Setup

**Task**: [Beads yggdrasil-beads-2e5.3]  
**Status**: ✅ Closed  
**Purpose**: Host container images for agents (executor, coordinator, code-agent) on Surtr

---

## Architecture

- **Registry Service**: Docker Registry v2 on Surtr port 5000
- **Storage**: Podman volume `registry-data` (persistent)
- **Network**: Local network, Tailscale accessible
- **Management**: `podman-compose` handles container orchestration

---

## Deployment Steps

### Option 1: Automated (Recommended)

From `~/homelab-config`:

```fish
./scripts/deploy-registry.sh surtr
```

This will:
1. Copy docker-compose.yml to Surtr
2. Create `~/yggdrasil-registry` directory
3. Start registry container with podman-compose
4. Health-check registry endpoint
5. Display service URLs

### Option 2: Manual Deployment

SSH into Surtr:

```fish
ssh surtr

# Create working directory
mkdir -p ~/yggdrasil-registry
cd ~/yggdrasil-registry
```

From local machine:

```fish
scp ~/homelab-config/docker/docker-compose.registry.yml surtr:~/yggdrasil-registry/docker-compose.yml
```

Back on Surtr:

```fish
cd ~/yggdrasil-registry
podman-compose up -d
podman-compose ps
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
