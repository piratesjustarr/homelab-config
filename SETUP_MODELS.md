# Yggdrasil LLM Setup Instructions

## Overview

Three machines with different GPU capabilities host a suite of optimized models:

| Host | GPU | Models | Purpose |
|------|-----|--------|---------|
| **Surtr** | RTX 2070 8GB | granite-code:8b, gpt-oss:20b | Code + Reasoning |
| **Fenrir** | RTX 4050 6GB + 64GB RAM | granite3.1-moe:3b, qwen2.5:7b | Fast + Chat |
| **Skadi** | GTX 1650 Ti 4GB | granite3.1-moe:1b | Ultra-fast |

## Prerequisites

On each host:
- `ramalama` installed: `brew install container-tools/skopeo/ramalama`
- `podman` running
- Tailscale configured

## Setup

### Option 1: Automatic (from each host)

SSH to each host and run:

**On Surtr:**
```bash
cd ~/homelab-config/scripts
./setup-all-llms.sh
```

**On Fenrir:**
```bash
cd ~/homelab-config/scripts
./setup-all-llms.sh
```

**On Skadi:**
```bash
cd ~/homelab-config/scripts
./setup-all-llms.sh
```

### Option 2: Manual (host-specific scripts)

Each host has a dedicated setup script:

```bash
# On Surtr
./setup-surtr-llms.sh

# On Fenrir
./setup-fenrir-llms.sh

# On Skadi
./setup-skadi-llms.sh
```

## Verification

After running setup scripts on all hosts:

```bash
# Check health from main machine
ygg status

# Expected output:
# ✓ surtr-code: online (granite-code:8b)
# ✓ surtr-reasoning: online (gpt-oss:20b)
# ✓ fenrir-fast: online (granite3.1-moe:3b)
# ✓ fenrir-chat: online (qwen2.5:7b)
# ✓ skadi-fast: online (granite3.1-moe:1b)
# ✓ cloud-anthropic: available (claude-sonnet)
```

## Monitoring

Check model status:

```bash
# View container logs
podman logs surtr-code
podman logs fenrir-fast
podman logs skadi-fast

# List running models
podman ps | grep -E "surtr|fenrir|skadi"

# Manually test an endpoint
curl http://surtr.nessie-hippocampus.ts.net:8080/v1/models | jq .
```

## Troubleshooting

**Model not responding:**
- Check logs: `podman logs <container_name>`
- Models take time to load (especially large ones like gpt-oss:20b)
- Verify port is open and accessible via Tailscale

**GPU out of memory:**
- Check `podman stats`
- Reduce `--ngl` layers for partial CPU offload
- The setup scripts use conservative settings, but large models may still need adjustment

**Models crashing:**
- Check available disk space
- Ensure adequate RAM (especially on Fenrir for qwen2.5:7b)
- Try pulling model manually: `ramalama pull ollama://model-name`

## Model Details

### Surtr (RTX 2070 8GB)

- **granite-code:8b** (port 8080)
  - Code generation, review, fixing
  - ~6GB VRAM
  
- **gpt-oss:20b** (port 8081)
  - Complex reasoning, planning
  - ~8GB VRAM (may need slight CPU offload on older 8GB cards)

### Fenrir (RTX 4050 6GB + 64GB RAM)

- **granite3.1-moe:3b** (port 8080)
  - Fast general purpose, MoE architecture
  - ~2GB VRAM
  
- **qwen2.5:7b** (port 8081)
  - Chat, text processing, summarization
  - ~4GB VRAM + 2GB CPU offload (24 GPU layers via `--ngl 24`)

### Skadi (GTX 1650 Ti 4GB)

- **granite3.1-moe:1b** (port 8080)
  - Ultra-fast simple tasks
  - ~1GB VRAM

## Integration

Once models are running, they're automatically discovered by:

```python
from llm_router import LLMRouter

router = LLMRouter()
router.load_config()           # Reads llm_hosts.yaml
router.health_check()          # Pings all hosts
host = router.get_host_for_task('code-generation')  # Returns best host
```

The Yggdrasil agent uses this routing to select appropriate models for each task.
