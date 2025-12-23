# Yggdrasil Agent Architecture

**Status**: Design Phase  
**Created**: 2025-12-21  

---

## Core Principle

**Beads is the execution graph. Agents execute tasks from the graph.**

Each agent:
1. Polls Beads for work (`bd ready` or `bd export`)
2. Claims a task and marks it `in_progress`
3. Executes the task (runs playbooks, scripts, commands)
4. Reports results back to Beads
5. Waits for next work

---

## Architecture: HTTP Agent Pattern (Recommended)

### Components

**1. Coordinator Agent** (Jormungandr/Surface)
- Single source of truth for task routing
- Reads `bd ready` periodically
- Decides which executor agent should run each task
- Dispatches via HTTP POST
- Collects results and syncs back to Beads
- Monitors executor health

**2. Executor Agents** (One per machine: Fenrir, Surtr, Huginn)
- Lightweight HTTP server (Flask/FastAPI)
- Receives task dispatch from Coordinator
- Executes task (runs Ansible playbooks, scripts, commands)
- Returns result JSON
- Stays available for next task

**3. Beads** (Central State)
- Source of truth for all work
- Tracks dependencies
- Maintains audit trail
- Coordinator reads: `bd ready`, `bd export`
- Coordinator writes: `bd update <id> --status <status>`

### Message Flow

```
Morning:
  Coordinator:  bd ready
  ↓
  → 10 ready tasks
  
Coordinator analyzes:
  Task bgf-2.1 (Surtr: Deploy Ollama)
  → Assign to: surtr-executor
  
  Task bgf-3.1 (Fenrir: Planning Agent)
  → Assign to: fenrir-executor

Dispatch (HTTP POST):
  POST http://surtr.nessie-hippocampus.ts.net:5000/execute
  {
    "task_id": "yggdrasil-beads-2e5.1",
    "type": "deploy-ollama",
    "params": {
      "models": ["llama3.1:70b", "mistral:7b"],
      "gpu": true
    }
  }

Executor (Surtr):
  → Receives task
  → Runs playbook: ansible/playbooks/ollama-setup.yml
  → Captures output
  → Returns HTTP 200:
  {
    "task_id": "yggdrasil-beads-2e5.1",
    "status": "completed",
    "output": "✓ Ollama running on 11434...",
    "duration_seconds": 120
  }

Coordinator:
  → Receives response
  → Updates Beads: bd update yggdrasil-beads-2e5.1 --status closed
  → Logs result to Obsidian (optional)
  → Picks next ready task

Beads recomputes ready:
  → bgf-2.2 now ready (was blocked on 2.1)
  → Coordinator dispatches to next agent
```

---

## Agent Types (Specialized Executors)

### Dev Agent (Fenrir)
- Code review, git operations, testing
- Tasks:
  - `code-review-pr`: Run linter + security checks
  - `git-clone-repo`: Clone repository to workspace
  - `run-tests`: Execute test suite
  - `commit-changes`: Commit to branch

### LLM Agent (Surtr)
- Ollama management, model training, inference
- Tasks:
  - `deploy-ollama`: Install/start Ollama
  - `pull-model`: Download LLM model
  - `run-inference`: Execute query against model
  - `fine-tune-model`: Train on custom dataset

### Ops Agent (Huginn)
- System operations, monitoring, power management
- Tasks:
  - `wake-on-lan`: Power on sleeping machines
  - `check-health`: System health metrics
  - `configure-pihole`: Update DNS rules
  - `monitor-plex`: Check Plex streaming health

### Planning Agent (Surtr/Fenrir - Meta-Agent)
- Reads Obsidian specs, creates Beads issues
- Tasks:
  - `sync-obsidian-to-beads`: Parse project specs, create issues
  - `analyze-dependencies`: Determine blocking relationships
  - `compute-ready-queue`: What can actually start

---

## Routing Logic (How Coordinator Decides)

**Task → Agent Mapping:**

```python
def route_task(task):
    """Assign task to appropriate executor"""
    
    task_type = task['type']
    
    if task_type.startswith('dev-'):
        return 'fenrir-executor'
    elif task_type.startswith('llm-'):
        return 'surtr-executor'
    elif task_type.startswith('ops-'):
        return 'huginn-executor'
    elif task_type.startswith('plan-'):
        return 'fenrir-executor'  # Or surtr, doesn't matter much
    else:
        return 'surtr-executor'  # Default to powerful machine
```

**Agent Load Balancing** (future enhancement):
- Track executor response times
- Prefer faster agents
- Skip agents that are offline

---

## Implementation Phases

### Phase 3.1: Agent Framework
- [ ] Create base Agent class (HTTP server)
- [ ] Create Executor subclasses (Dev, LLM, Ops)
- [ ] Create task dispatch protocol (JSON schema)

### Phase 3.2: Coordinator Agent
- [ ] Read `bd ready` / `bd export`
- [ ] Route tasks to executors
- [ ] Sync results back to Beads
- [ ] Handle executor failures/retries

### Phase 3.3: Executor Deployment
- [ ] Deploy agents on Fenrir, Surtr, Huginn
- [ ] Verify HTTP connectivity over Tailscale
- [ ] Create systemd services (auto-start)

### Phase 3.4: Task Library
- [ ] Define 20+ concrete task types
- [ ] Create Ansible playbooks for each
- [ ] Create Beads issues for Phase 2 tasks

### Phase 3.5: Testing & Hardening
- [ ] Test end-to-end: Beads → Coordinator → Executor → Result → Beads
- [ ] Handle network failures, timeouts
- [ ] Implement retry logic
- [ ] Add logging/observability

---

## Example: End-to-End Task Flow (Ollama Setup)

### Beads Issue
```
yggdrasil-beads-2e5.1: Deploy Ollama on Surtr
Type: task
Tags: llm, infrastructure
```

### Coordinator Process
```python
# Morning: Check ready work
tasks = bd_export()
task = find_task("yggdrasil-beads-2e5.1")

# Route to appropriate agent
agent = route_task(task)  # → "surtr-executor"

# Prepare task payload
payload = {
    "task_id": "yggdrasil-beads-2e5.1",
    "type": "deploy-ollama",
    "params": {
        "docker_compose_path": "~/homelab/docker-compose.yml",
        "models": ["llama3.1:70b", "mistral:7b"],
        "gpu": True
    }
}

# Dispatch to executor
response = requests.post(
    f"http://{agent}.nessie-hippocampus.ts.net:5000/execute",
    json=payload,
    timeout=600  # Long timeout for slow operations
)

# Sync result back to Beads
if response.ok:
    result = response.json()
    bd_update("yggdrasil-beads-2e5.1", "closed", result['output'])
else:
    bd_update("yggdrasil-beads-2e5.1", "blocked", f"Agent error: {response.text}")
```

### Executor Process (Surtr)
```python
# HTTP server listening on surtr:5000

@app.route('/execute', methods=['POST'])
def execute_task():
    task = request.json
    task_id = task['task_id']
    task_type = task['type']
    
    try:
        if task_type == "deploy-ollama":
            # Run Ansible playbook
            result = run_playbook(
                'ansible/playbooks/ollama-setup.yml',
                extra_vars=task['params']
            )
        
        return {
            "task_id": task_id,
            "status": "completed" if result.returncode == 0 else "failed",
            "output": result.stdout + result.stderr,
            "duration_seconds": result.duration
        }
    except Exception as e:
        return {
            "task_id": task_id,
            "status": "error",
            "error": str(e)
        }, 500
```

### Result
- ✅ Ollama deployed on Surtr
- ✅ Models pulled (llama3.1:70b, mistral:7b)
- ✅ Task marked complete in Beads
- ✅ Next ready task (bgf-2.2) identified by Coordinator
- ✅ Full audit trail in Beads git history

---

## Key Design Decisions

1. **HTTP not gRPC**: Simpler debugging, works over Tailscale, no IDL needed
2. **Coordinator is stateless**: Can crash/restart without losing state (all in Beads)
3. **Executors are stateless**: Can crash; Coordinator retries task
4. **Long polling not WebSocket**: Simpler, works with firewalls
5. **Tasks are immutable once dispatched**: No mid-flight changes
6. **Results stored in Beads, not separate DB**: Single source of truth

---

## Failure Modes & Handling

**Executor crashes during task**:
- Coordinator detects timeout (300s default)
- Marks task as blocked with error
- Operator sees in `bd ready` that task failed
- Can retry or escalate

**Coordinator crashes**:
- Executor keeps running, returns 503 (unavailable)
- Operator restarts Coordinator
- It re-reads Beads state and continues
- No work is lost

**Network partition**:
- Executor becomes unreachable
- Coordinator marks tasks as blocked
- When network recovers, Coordinator retries

**Agent out of capacity**:
- Returns HTTP 429 (too many requests)
- Coordinator queues task locally or assigns to backup agent

---

## Security Considerations (Future)

- [ ] API key auth for executors (verify Coordinator identity)
- [ ] TLS encryption over Tailscale (paranoid, probably overkill)
- [ ] Executor sandboxing (limit what agents can do)
- [ ] Audit logging (log every executed command)
- [ ] Rate limiting (prevent agent overload)

For now: Tailscale provides network isolation; agents only accept from Coordinator.

---

*Architecture designed: 2025-12-21*
