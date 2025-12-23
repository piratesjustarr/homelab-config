# AGENTS.md: Yggdrasil Agent System Guide

This document is your reference for working in the homelab-config repository. It covers the agent system architecture, how to add tasks, extend executors, and debug operations.

---

## Quick Start for Agents

### Essential Commands

```bash
# View ready work in Beads
cd ~/homelab-config/yggdrasil-beads
export PATH="$HOME/.local/bin:$PATH"
bd ready                    # Show next work (10 items, no blockers)
bd list                     # Show all tasks with status
bd export                   # Export full task graph as JSONL

# Update task status after completing work
bd update yggdrasil-beads-bgf.1 --status closed

# Start coordinator (routes tasks to executors)
cd ~/homelab-config
python3 coordinator/coordinator.py

# Start an executor (receives tasks, executes them)
python3 agent-executors/fenrir-executor.py    # Dev tasks
python3 agent-executors/surtr-executor.py     # LLM tasks
python3 agent-executors/huginn-executor.py    # Ops tasks
```

### Directory Structure

```
homelab-config/
├── agents/                          # Base framework
│   └── base_agent.py               # AgentExecutor class (Flask HTTP server)
├── agent-executors/                 # Specialized executors (one per machine)
│   ├── fenrir-executor.py          # Dev agent: code review, git, tests
│   ├── surtr-executor.py           # LLM agent: Ollama, inference
│   └── huginn-executor.py          # Ops agent: monitoring, power, DNS
├── coordinator/                     # Central dispatcher
│   └── coordinator.py              # Routes tasks, syncs results
├── yggdrasil-beads/                # Task graph (Beads database)
│   ├── .beads/                     # SQLite DB, JSONL export, config
│   └── .git/                       # Git history
├── requirements.txt                # Python dependencies (Flask, requests)
├── AGENT-ARCHITECTURE.md           # Design rationale
├── AGENT-IMPLEMENTATION.md         # Deployment guide
└── AGENTS.md                       # This file
```

---

## How the System Works

### The Three-Layer Model

**Layer 1: Beads (Task Graph)**
- Single source of truth for all work
- Tracks task status: open, in_progress, closed, blocked
- Maintains dependencies (tasks blocked until others complete)
- Git-backed audit trail

**Layer 2: Coordinator Agent**
- Runs on Jormungandr or Surtr (always-on machine)
- Polls Beads every 30 seconds for ready work
- Routes each task to appropriate executor
- Syncs results back to Beads
- Monitors executor health

**Layer 3: Executor Agents**
- Run on each machine: Fenrir, Surtr, Huginn
- HTTP server listening on port 5000
- Receive task dispatch from Coordinator
- Execute task (run command, playbook, or custom handler)
- Return JSON result with output, status, duration
- Stateless (can crash; Coordinator retries)

### Execution Flow (Example)

```
1. Coordinator polls:
   $ bd ready
   → [yggdrasil-beads-2e5.1: Deploy Ollama]

2. Coordinator routes:
   Task type: "ollama-deploy"
   → Send to: surtr-executor

3. Coordinator dispatches (HTTP POST):
   POST http://surtr.nessie-hippocampus.ts.net:5000/execute
   {
     "task_id": "yggdrasil-beads-2e5.1",
     "type": "ollama-deploy",
     "params": {"models": ["llama3.1:8b"]}
   }

4. Surtr executor handles:
   class SurtrExecutor(AgentExecutor):
       def handle_ollama_deploy(self, params):
           cmd = 'docker-compose up -d ollama'
           result = self.run_command(cmd, timeout=300)
           return {'output': result['output'], 'success': result['success']}

5. Coordinator receives result (HTTP 200):
   {
     "task_id": "yggdrasil-beads-2e5.1",
     "type": "ollama-deploy",
     "status": "completed",
     "output": "Creating ollama ... done",
     "duration_seconds": 45.2
   }

6. Coordinator syncs back:
   $ bd update yggdrasil-beads-2e5.1 --status closed

7. Next task ready:
   Coordinator polls again → new task from Beads
```

---

## Code Organization & Patterns

### Base Agent Framework (agents/base_agent.py)

All executors inherit from `AgentExecutor`. The framework provides:

**HTTP Routes** (built-in):
- `GET /health` — Health check (status, version, timestamp)
- `POST /execute` — Receive and execute task
- `GET /status` — List registered task handlers

**Helper Methods**:
```python
# Run shell command
result = self.run_command(
    'docker ps',
    timeout=30  # seconds
)
# Returns: {
#   'returncode': int,
#   'stdout': str,
#   'stderr': str,
#   'output': str,  # combined stdout+stderr
#   'duration': float,
#   'success': bool
# }

# Run Ansible playbook
result = self.run_playbook(
    'playbooks/ollama-setup.yml',
    extra_vars={'model': 'llama3.1:8b'},
    timeout=600
)
```

**Lifecycle**:
```python
class MyExecutor(AgentExecutor):
    EXECUTOR_NAME = "my-executor"
    EXECUTOR_VERSION = "0.1.0"
    
    def register_handlers(self):
        """Called during __init__; map task types to methods"""
        self.task_handlers = {
            'task-type': self.handle_task_type,
        }
    
    def handle_task_type(self, params):
        """Task handler; receives params dict, returns {'output': str}"""
        result = self.run_command('do-something')
        return {'output': result['output']}

if __name__ == '__main__':
    agent = MyExecutor()
    agent.run(host='0.0.0.0', port=5000, debug=False)
```

### Task Handler Naming

Task types use kebab-case. Handlers use snake_case method names:
- Task type: `code-review` → Handler: `handle_code_review()`
- Task type: `ollama-deploy` → Handler: `handle_ollama_deploy()`

### Executor Specialization

**Fenrir Executor** (Dev Agent)
- Path: `agent-executors/fenrir-executor.py`
- Task prefix: `dev-`, `code-`, `git-`, `plan-`
- Handlers: health-check, git-clone, git-commit, code-review, run-tests, plan-sync
- Use for: code operations, testing, version control

**Surtr Executor** (LLM Agent)
- Path: `agent-executors/surtr-executor.py`
- Task prefix: `llm-`, `ollama-`, `gpu-`
- Handlers: health-check, ollama-deploy, ollama-pull-model, ollama-list-models, llm-inference, gpu-verify
- Use for: LLM operations, Ollama management, GPU compute

**Huginn Executor** (Ops Agent)
- Path: `agent-executors/huginn-executor.py`
- Task prefix: `ops-`, `power-`, `monitor-`, `network-`
- Handlers: health-check, power-wake, power-status, monitor-pihole, monitor-plex, network-check
- Use for: system operations, monitoring, power management, network diagnostics

### Coordinator Routing Logic (coordinator/coordinator.py)

The Coordinator uses prefix matching to route tasks:

```python
ROUTING = {
    'dev-': 'fenrir-executor',
    'code-': 'fenrir-executor',
    'git-': 'fenrir-executor',
    'llm-': 'surtr-executor',
    'ollama-': 'surtr-executor',
    'ops-': 'huginn-executor',
    'power-': 'huginn-executor',
    'plan-': 'fenrir-executor',
}
```

If a task type doesn't match any prefix, it defaults to `surtr-executor` (most powerful machine).

To override routing, add a Beads label matching the executor name (e.g., `fenrir-executor` label forces routing to Fenrir).

---

## Adding New Task Handlers

### Step 1: Identify Which Executor

Decide based on task responsibility:
- Code/testing → Fenrir
- LLM/GPU → Surtr
- Ops/monitoring → Huginn

### Step 2: Implement Handler

Edit the appropriate executor file. Example for Surtr:

```python
# agent-executors/surtr-executor.py

def register_handlers(self):
    self.task_handlers = {
        # ... existing handlers ...
        'ollama-chat': self.handle_ollama_chat,  # NEW
    }

def handle_ollama_chat(self, params):
    """Chat with a local LLM model"""
    model = params.get('model', 'llama3.1:8b')
    messages = params.get('messages', [])  # List of {"role": "user", "content": "..."}
    
    # Build multi-turn prompt
    prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
    
    # Run inference
    cmd = f'ollama run {model} "{prompt}"'
    result = self.run_command(cmd, timeout=120)
    
    return {
        'output': result['output'],
        'success': result['success']
    }
```

### Step 3: Create Beads Task

```bash
cd ~/homelab-config/yggdrasil-beads
export PATH="$HOME/.local/bin:$PATH"
bd create --title "Chat with Llama 3.1" --type task --label llm --description "Interactive chat session"
```

This creates a new task. The Coordinator will route it to Surtr based on the `llm` label (or `ollama-chat` prefix).

### Step 4: Test Handler

```bash
# Start executor
python3 agent-executors/surtr-executor.py

# In another terminal, test the handler
curl -X POST http://surtr.nessie-hippocampus.ts.net:5000/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "test-1",
    "type": "ollama-chat",
    "params": {
      "model": "llama3.1:8b",
      "messages": [{"role": "user", "content": "Hello"}]
    }
  }'
```

---

## Important Gotchas & Patterns

### 1. Logging Goes to Files, Not Stdout in Production

All agents log to `/var/log/`:
- Coordinator: `/var/log/yggdrasil-coordinator.log`
- All executors: `/var/log/yggdrasil-agent.log`

During development, logs also print to stdout. In systemd services, redirect stdout/stderr to avoid duplicate logging.

### 2. Tailscale DNS Names

All executors are referenced by Tailscale MagicDNS names:
- Fenrir: `fenrir.nessie-hippocampus.ts.net`
- Surtr: `surtr.nessie-hippocampus.ts.net`
- Huginn: `huginn.nessie-hippocampus.ts.net`

These names are hardcoded in `coordinator/coordinator.py`. If you change machine names or Tailnet name, update the `EXECUTORS` dict.

### 3. Handlers Must Return {'output': str}

All task handlers must return a dict with at least `'output'` key (string). Additional keys are optional:

```python
return {
    'output': 'Success message',
    'success': True,  # Optional
    'data': {...}     # Optional
}
```

If a handler doesn't return the right shape, the Coordinator will fail when trying to sync results.

### 4. Task Timeouts Are Defaults

Default timeouts:
- `run_command()`: 5 minutes (300s)
- `run_playbook()`: 10 minutes (600s)
- Coordinator dispatch: 10 minutes (600s)

Long-running tasks (model downloads) may timeout. Override in handler:

```python
def handle_ollama_pull_model(self, params):
    model = params.get('model', 'llama3.1:8b')
    cmd = f'ollama pull {model}'
    result = self.run_command(cmd, timeout=1800)  # 30 minutes
    return {'output': result['output']}
```

### 5. Beads Task IDs

All Beads tasks have IDs like `yggdrasil-beads-bgf.1`. When creating handlers, always accept `task_id` in the dispatch payload (it's passed by Coordinator but may not be used by all handlers).

### 6. Executor Naming Convention

Executors are named `{machine}-executor` to avoid confusion:
- `fenrir-executor`
- `surtr-executor`
- `huginn-executor`

This matches the Tailscale machine names for consistency.

### 7. Graceful Shutdown

Executors handle SIGTERM and SIGINT. They shut down cleanly, allowing the current task to complete (up to 5 minutes). When restarting executors, the Coordinator will retry pending tasks.

### 8. Beads Submodule

`yggdrasil-beads/` is a Git submodule within `homelab-config/`. When committing changes to Beads (task status updates), you need to:

```bash
cd yggdrasil-beads
git add -A && git commit -m "Update task status"
cd ..
git add yggdrasil-beads
git commit -m "Update Beads submodule"
git push
```

The Coordinator handles this automatically, but if you update Beads manually, remember to commit the submodule reference.

---

## Testing & Debugging

### Health Checks

Check if executors are running:

```bash
curl http://fenrir.nessie-hippocampus.ts.net:5000/health
curl http://surtr.nessie-hippocampus.ts.net:5000/health
curl http://huginn.nessie-hippocampus.ts.net:5000/health

# Expected response:
# {
#   "status": "healthy",
#   "executor": "fenrir-executor",
#   "version": "0.1.0",
#   "timestamp": "2025-12-23T..."
# }
```

### Coordinator Health

Check Coordinator logs:

```bash
tail -f /var/log/yggdrasil-coordinator.log
```

Look for:
- `Poll N @ ...` — Coordinator running
- `Found X ready tasks` — Tasks available
- `Dispatching ... to ...` — Task being sent
- `Updated ... → closed` — Task completed

### Executor Logs

Check executor logs:

```bash
tail -f /var/log/yggdrasil-agent.log
```

Look for:
- `Received task ...` — Handler invoked
- `Running: ...` — Command executed
- `Task ... completed in ...` — Handler returned

### Manual Task Testing

Dispatch a task directly to an executor (bypass Coordinator):

```bash
# Test Fenrir health check
curl -X POST http://fenrir.nessie-hippocampus.ts.net:5000/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "manual-test-1",
    "type": "dev-health-check",
    "params": {}
  }'

# Expected output:
# {
#   "task_id": "manual-test-1",
#   "type": "dev-health-check",
#   "status": "completed",
#   "output": "Fenrir health check: True\nLinux fenrir...",
#   "duration_seconds": 0.3
# }
```

### Coordinator Dry-Run

Run Coordinator in limited mode to test routing and health checks:

```bash
cd ~/homelab-config
python3 -c "
from coordinator.coordinator import Coordinator
c = Coordinator()
tasks = c.get_ready_tasks()
for t in tasks[:3]:
    executor = c.route_task(t)
    healthy = c.check_executor_health(executor)
    print(f'{t[\"id\"]} → {executor} ({\"healthy\" if healthy else \"UNHEALTHY\"})')
"
```

---

## Deployment Notes

### Running Executors as Services

For production, run executors as systemd services:

```bash
# /etc/systemd/system/yggdrasil-fenrir-executor.service
[Unit]
Description=Yggdrasil Fenrir Executor
After=network.target tailscaled.service

[Service]
Type=simple
User=matt
WorkingDirectory=/var/home/matt/homelab-config
ExecStart=/usr/bin/python3 agent-executors/fenrir-executor.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable yggdrasil-fenrir-executor.service
sudo systemctl start yggdrasil-fenrir-executor.service
sudo systemctl status yggdrasil-fenrir-executor.service
```

### Running Coordinator as Service

Similar setup for Coordinator on Jormungandr or Surtr:

```bash
# /etc/systemd/system/yggdrasil-coordinator.service
[Unit]
Description=Yggdrasil Coordinator
After=network.target tailscaled.service
Requires=yggdrasil-fenrir-executor.service yggdrasil-surtr-executor.service yggdrasil-huginn-executor.service

[Service]
Type=simple
User=matt
WorkingDirectory=/var/home/matt/homelab-config
ExecStart=/usr/bin/python3 coordinator/coordinator.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Environment Setup

Ensure Python dependencies are installed on all machines:

```bash
pip3 install -r ~/homelab-config/requirements.txt
```

Dependencies:
- `Flask>=2.0.0` — Web framework for executors
- `requests>=2.25.0` — HTTP client for Coordinator

---

## Next Steps

### Phase 2: Ollama + Model Management
- Create `ollama-deploy` task (deploy Ollama on Surtr)
- Create `ollama-pull-model` tasks (download LLMs)
- Test end-to-end: Coordinator → Surtr → Ollama deployed

### Phase 3: Planning Agent
- Sync Obsidian specs to Beads (bidirectional)
- Implement `plan-sync` handler on Fenrir
- Allow humans to create tasks in Obsidian, auto-import to Beads

### Phase 4: Multi-Agent LLM Routing
- Use LLM (Surtr) to classify incoming tasks
- Coordinator dispatches to appropriate executor based on classification
- Enable dynamic task routing

### Phase 5: Director-Level Workflows
- High-level goal → decomposed into sub-tasks
- Coordinator orchestrates complex multi-machine workflows
- Example: "Deploy Ollama + pull 3 models + verify GPU" = 1 goal, 3 tasks

---

## Common Issues & Solutions

### Executor Not Responding

**Symptom**: Coordinator gets connection timeout

**Solution**:
1. Check executor is running: `systemctl status yggdrasil-fenrir-executor`
2. Check port: `ss -tlnp | grep 5000`
3. Check Tailscale: `tailscale status | grep fenrir`
4. Check firewall: `sudo ufw allow 5000`
5. Test directly: `curl http://fenrir.nessie-hippocampus.ts.net:5000/health`

### Task Hangs

**Symptom**: Coordinator dispatches task, no response for 10+ minutes

**Solution**:
1. SSH to executor machine, check process: `ps aux | grep executor`
2. Check logs: `tail /var/log/yggdrasil-agent.log`
3. If command is stuck, increase timeout in handler or make command non-blocking
4. Restart executor: `systemctl restart yggdrasil-fenrir-executor`

### Beads Not Updating

**Symptom**: Coordinator reports task completed but Beads status unchanged

**Solution**:
1. Check Coordinator logs for sync errors: `tail /var/log/yggdrasil-coordinator.log | grep "sync"`
2. Verify Beads repo is accessible: `cd ~/homelab-config/yggdrasil-beads && bd list`
3. Ensure Beads git is committed: `cd yggdrasil-beads && git status`
4. Try manual update: `bd update <task-id> --status closed`

### Python Import Errors

**Symptom**: `ModuleNotFoundError: No module named 'agents'`

**Solution**:
- Ensure executor files have: `sys.path.insert(0, '/var/home/matt/homelab-config')` at top
- This allows imports like `from agents.base_agent import AgentExecutor`
- Verify absolute path matches your setup; adjust if needed

---

## Containerization (v0.2.0+)

### Running Agents in Containers

All agents can run in containers for better reproducibility and deployment:

```bash
# Build all images
cd ~/homelab-config
./scripts/build-and-push.sh

# Deploy registry on Surtr
# (stores executor images, code agent, coordinator)
cd docker
podman-compose -f docker-compose.registry.yml up -d

# Deploy executor on Fenrir (pull from registry)
podman run -d \
  --name yggdrasil-executor \
  --net host \
  -v ~/.ssh:/root/.ssh:ro \
  -v /var/log:/var/log \
  localhost:5000/yggdrasil-executor:latest

# Deploy code agent on Surtr (requires Ollama running)
podman run -d \
  --name yggdrasil-code-agent \
  --net host \
  --gpus all \
  -e OLLAMA_HOST=http://localhost:11434 \
  localhost:5000/yggdrasil-code-agent:latest
```

### Dockerfile Structure

- **Dockerfile.executor**: Python 3.11 + Flask + agent framework (multi-executor variant)
- **Dockerfile.coordinator**: Coordinator agent (central dispatcher)
- **Dockerfile.code-agent**: Code LLM agent with Ollama support (runs on port 5001)

Each Dockerfile:
- Uses `python:3.11-slim` base image (Red Hat UBI compatible with Bluefin)
- Installs only necessary system dependencies (minimal image size)
- Includes health checks for monitoring
- Logs to `/var/log` (container mounts for persistence)

### Registry on Surtr

Registry runs on port 5000 (via docker-compose):
- Stores versioned executor images
- Optional web UI on port 8080 for browsing images
- Configuration in `docker/registry-config.yml`
- Data persists in `registry-data` volume

### Container Deployment Checklist

- [ ] Build images with `./scripts/build-and-push.sh`
- [ ] Deploy registry: `podman-compose -f docker/docker-compose.registry.yml up -d`
- [ ] Verify registry: `curl http://localhost:5000/v2/`
- [ ] Deploy executors on Fenrir, Huginn (pull from registry)
- [ ] Deploy code agent on Surtr with GPU support
- [ ] Verify all health checks passing: `podman ps`
- [ ] Update Coordinator to use containerized executors
- [ ] Test with manual curl to container endpoints

---

## Version History

- **v0.2.0** (2025-12-23): Containerization + Code LLM Agent
  - All agents now runnable as containers
  - Private registry on Surtr
  - Code generation agent (Qwen/Granite based)
  - Aligns with Bluefin cloud-native principles

- **v0.1.0** (2025-12-21): Initial HTTP agent framework with 3 executors + Coordinator
  - Stateless design, sequential execution, git-backed task graph
  - 18 total task handlers across Fenrir, Surtr, Huginn
  - Bare-metal agent execution

- **Next**: Parallel execution, dynamic routing, planning agent integration
