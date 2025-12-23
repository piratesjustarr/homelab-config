# Yggdrasil Agent Execution System

**Status**: Implementation Phase  
**Version**: 0.1.0  

---

## Overview

This is the **distributed execution layer** for Yggdrasil homelab automation.

**Architecture**:
- **Beads**: Central task graph (source of truth)
- **Coordinator**: Reads Beads, routes tasks, syncs results
- **Executors**: Specialized agents on each machine (Fenrir, Surtr, Huginn)

**Key principle**: Beads tracks WHAT needs doing; agents handle HOW it gets done.

---

## Components

### 1. Base Agent Framework (`agents/base_agent.py`)

Generic HTTP server that any executor can inherit from:

```python
class FenrirExecutor(AgentExecutor):
    EXECUTOR_NAME = "fenrir-executor"
    
    def register_handlers(self):
        self.task_handlers['git-clone'] = self.handle_git_clone
    
    def handle_git_clone(self, params):
        # Your implementation
        pass
```

**Features**:
- HTTP routes: `/health`, `/execute`, `/status`
- Automatic logging to `/var/log/yggdrasil-agent.log`
- Timeout handling, graceful shutdown
- Helper methods: `run_command()`, `run_playbook()`

### 2. Coordinator (`coordinator/coordinator.py`)

Central dispatcher that:
1. Polls Beads for ready work (`bd ready`)
2. Routes each task to appropriate executor
3. Dispatches via HTTP POST
4. Syncs results back to Beads (`bd update`)

**Routing logic**:
```
Task type "llm-*" → surtr-executor
Task type "code-*" → fenrir-executor
Task type "ops-*" → huginn-executor
```

### 3. Executor Agents

#### Fenrir Executor (`agent-executors/fenrir-executor.py`)
- Dev/code tasks: git, code review, testing
- Handlers:
  - `dev-health-check`
  - `git-clone`, `git-commit`
  - `code-review`
  - `run-tests`

#### Surtr Executor (`agent-executors/surtr-executor.py`)
- LLM tasks: Ollama deployment, model mgmt, inference
- Handlers:
  - `llm-health-check`
  - `ollama-deploy`, `ollama-pull-model`, `ollama-list-models`
  - `llm-inference`
  - `gpu-verify`

#### Huginn Executor (`agent-executors/huginn-executor.py`)
- Ops tasks: monitoring, power management, DNS
- Handlers:
  - `ops-health-check`
  - `power-wake`, `power-status`
  - `monitor-pihole`, `monitor-plex`
  - `network-check`

---

## Deployment

### Prerequisites

On **all machines** (Fenrir, Surtr, Huginn):
```bash
# Install Python and dependencies
sudo dnf install python3 python3-pip

# Install agent code
git clone [your-repo] ~/homelab-config
cd ~/homelab-config
pip3 install -r requirements.txt
```

### Start Executor Agents

**On Fenrir**:
```bash
python3 ~/homelab-config/agent-executors/fenrir-executor.py
# Listens on fenrir:5000
```

**On Surtr**:
```bash
python3 ~/homelab-config/agent-executors/surtr-executor.py
# Listens on surtr:5000
```

**On Huginn**:
```bash
python3 ~/homelab-config/agent-executors/huginn-executor.py
# Listens on huginn:5000
```

### Start Coordinator

**On Jormungandr or Surtr**:
```bash
python3 ~/homelab-config/coordinator/coordinator.py
# Polls bd ready every 30 seconds
# Dispatches tasks to executors
# Syncs results back to Beads
```

### Systemd Integration (Optional)

Create `/etc/systemd/system/yggdrasil-fenrir-executor.service`:
```ini
[Unit]
Description=Yggdrasil Fenrir Executor
After=network.target

[Service]
Type=simple
User=brandon
ExecStart=/usr/bin/python3 /var/home/matt/homelab-config/agent-executors/fenrir-executor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable --now yggdrasil-fenrir-executor.service
```

---

## Message Flow Example

### Scenario: Deploy Ollama on Surtr

**1. Beads Issue**
```
yggdrasil-beads-2e5.1: Deploy Ollama
Type: task
Tags: llm, infrastructure
Status: open
```

**2. Coordinator Poll**
```python
Coordinator reads: bd ready
→ Finds yggdrasil-beads-2e5.1
→ Routes to: surtr-executor (task type: "ollama-deploy")
```

**3. Dispatch to Executor**
```bash
POST http://surtr.nessie-hippocampus.ts.net:5000/execute
{
  "task_id": "yggdrasil-beads-2e5.1",
  "type": "ollama-deploy",
  "params": {}
}
```

**4. Executor Handles**
```python
SurtrExecutor.handle_ollama_deploy()
→ Runs: docker-compose up -d ollama
→ Waits for startup
→ Returns HTTP 200:
{
  "task_id": "yggdrasil-beads-2e5.1",
  "status": "completed",
  "output": "... docker logs ...",
  "duration_seconds": 45
}
```

**5. Sync to Beads**
```bash
Coordinator receives result
→ Runs: bd update yggdrasil-beads-2e5.1 --status closed
→ Logs output to /var/log/yggdrasil-coordinator.log
```

**6. Next Task**
```python
Coordinator polls again
→ bd ready now shows next task (maybe yggdrasil-beads-2e5.2)
→ Dispatch to appropriate executor
```

---

## Adding New Task Handlers

### Step 1: Define Beads Issue

```bash
cd ~/homelab-config/yggdrasil-beads
bd create "New Feature: Do X" \
  --type task \
  --parent yggdrasil-beads-2e5 \
  --labels llm,infrastructure
```

Note the task ID (e.g., `yggdrasil-beads-2e5.5`).

### Step 2: Add Handler to Executor

Edit `agent-executors/surtr-executor.py` (or appropriate executor):

```python
def register_handlers(self):
    self.task_handlers['new-task-type'] = self.handle_new_task
    # ... other handlers ...

def handle_new_task(self, params):
    """Handle new-task-type"""
    param1 = params.get('param1', 'default')
    
    result = self.run_command(f"do something with {param1}")
    
    return {
        'output': result['output'],
        'success': result['success']
    }
```

### Step 3: Update Beads Issue

```bash
# Update task with handler info
bd update yggdrasil-beads-2e5.5 \
  --description "Handler: new-task-type on surtr-executor"
```

### Step 4: Test

```bash
# Manual test
curl -X POST http://surtr:5000/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "test-bgf-5",
    "type": "new-task-type",
    "params": {"param1": "value"}
  }'
```

---

## Logging & Debugging

### Executor Logs
```bash
# On Fenrir
tail -f /var/log/yggdrasil-agent.log | grep fenrir-executor

# On Surtr
tail -f /var/log/yggdrasil-agent.log | grep surtr-executor
```

### Coordinator Logs
```bash
tail -f /var/log/yggdrasil-coordinator.log
```

### Live Executor Status
```bash
# Check executor health
curl http://fenrir.nessie-hippocampus.ts.net:5000/health | jq .

# List handlers
curl http://surtr.nessie-hippocampus.ts.net:5000/status | jq .
```

---

## Failure Modes & Recovery

### Executor Crash
- Coordinator detects timeout (10 min default)
- Task marked as `blocked` in Beads
- Restart executor: `systemctl restart yggdrasil-surtr-executor.service`
- Coordinator retries on next poll

### Coordinator Crash
- Executors keep running, return HTTP 503
- Restart coordinator: `systemctl restart yggdrasil-coordinator.service`
- Reads Beads state and continues from where it left off

### Network Partition
- Coordinator can't reach executor
- Task marked as `blocked`
- When network recovers, retry automatically

---

## Performance Tuning

### Task Timeout
Default: 600 seconds (10 minutes)

Adjust in `coordinator.py`:
```python
self.task_timeout = 600  # Change this
```

### Poll Interval
Default: 30 seconds between checks

Adjust in `coordinator.py`:
```python
coordinator.run_loop(poll_interval=30)  # Change this
```

### Parallel Execution
Current: Sequential (one task at a time)

Future enhancement: Dispatcher pool to run multiple tasks concurrently.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│         Beads (Central State)                    │
│  • Phase 2: Ollama tasks (bgf-2.1, 2.2, ...)   │
│  • Phase 3: Agent tasks (bgf-3.1, 3.2, ...)    │
│  Status: open/in_progress/blocked/closed        │
└─────────────────────────────────────────────────┘
              ↑         ↓
              │         │
        bd export   bd update
              │         │
       ┌──────┴─────────┴──────┐
       │                       │
┌──────▼──────────────────┐    │
│  Coordinator (Jorgmun)   │    │
│  • Poll bd ready         │    │
│  • Route tasks           │────┘
│  • Dispatch HTTP         │
└──────┬──────────────────┘
       │
    HTTP POST
    ┌──────┼──────┐
    │      │      │
┌───▼──┐ ┌──▼──┐ ┌──▼───┐
│Fenrir│ │Surtr│ │Huginn│
│Dev   │ │LLM  │ │Ops   │
│Agent │ │Agent│ │Agent │
└──────┘ └─────┘ └──────┘
```

---

## Next Steps

- [ ] Deploy executors to all machines
- [ ] Test coordinator with simple tasks
- [ ] Add Ansible playbook handlers
- [ ] Implement Phase 2 task library
- [ ] Build Planning agent (Obsidian → Beads)
- [ ] Scale to parallel execution

---

*Agent architecture v0.1.0 • Designed for Yggdrasil homelab*
