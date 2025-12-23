# Containerized Agent Architecture for Yggdrasil

**Status**: Design Phase  
**Created**: 2025-12-23  
**Context**: Bluefin cloud-native, distributed agent execution, local LLM code generation

---

## Vision: Cloud-Native Agents + Code LLM Bootstrap

### Problem We're Solving

Current state:
- Agents run bare-metal on each machine (manual python execution)
- No artifact registry or versioning
- Adding new machines requires manual agent setup
- All complex tasks delegated to human developer (you)
- Lost opportunity: local code LLM could execute many Beads tasks autonomously

### Solution Architecture

**Three Tiers**:

1. **Surtr Container Registry** (OCI/Docker compatible)
   - Private registry for agent images
   - Versioned executor containers
   - Quick pull-and-run on any machine in tailnet

2. **Containerized Executors**
   - Each machine runs executor(s) in containers
   - Same image, different task handlers → specialized by Beads labels
   - Easy to update: pull new image, restart container
   - Immutable: reproducible agent behavior

3. **Code LLM Agent** (Surtr-hosted, Beads-integrated)
   - Runs Qwen Code (3B) or Granite Code (3B/8B) model
   - Executes simple programming tasks autonomously
   - Route coding tasks to LLM agent instead of human
   - Examples: refactor code, write unit tests, fix lint errors, generate boilerplate

---

## Containerization Strategy

### Why Containers for Agents?

**Bluefin Alignment**:
- Bluefin is immutable host + containerized apps
- Aligns perfectly with cloud-native, GitOps thinking
- Agents become "microservices" in homelab

**Benefits**:
- **Reproducibility**: Same image runs anywhere
- **Versioning**: Tag agents (v0.1.0, v0.2.0)
- **Easy deployment**: `podman pull` + `podman run`
- **Isolation**: Agent dependencies don't pollute host
- **Quick updates**: No installation steps per machine
- **Registry**: Surtr hosts images locally (offline-capable)

### Container Architecture

```
Registry (Surtr):
  ├── localhost:5000/yggdrasil-executor:latest
  ├── localhost:5000/yggdrasil-executor:v0.1.0
  ├── localhost:5000/yggdrasil-coordinator:latest
  ├── localhost:5000/yggdrasil-code-agent:latest
  └── localhost:5000/yggdrasil-code-agent:v0.1.0

Machines:
  Fenrir:
    └── podman run yggdrasil-executor:latest (fenrir-specific config)
  
  Surtr:
    ├── podman run registry:2 (self-hosted registry)
    ├── podman run yggdrasil-code-agent:latest (code LLM)
    ├── podman run yggdrasil-executor:latest (generic fallback)
    └── podman run yggdrasil-coordinator:latest (task dispatcher)
  
  Huginn:
    └── podman run yggdrasil-executor:latest (huginn-specific config)
```

---

## Implementation: Container Layers

### Layer 1: Base Executor Container

**Dockerfile**: `docker/Dockerfile.executor`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    jq \
    ansible \
    && rm -rf /var/lib/apt/lists/*

# Copy agent framework
COPY agents/ agents/
COPY coordinator/ coordinator/
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy executor (will be specialized per machine)
ARG EXECUTOR_TYPE=fenrir
COPY agent-executors/${EXECUTOR_TYPE}-executor.py executor.py

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Run executor
EXPOSE 5000
CMD ["python3", "executor.py"]
```

**Build and Push**:
```bash
podman build -t localhost:5000/yggdrasil-executor:latest \
  --build-arg EXECUTOR_TYPE=fenrir \
  -f docker/Dockerfile.executor .

podman push localhost:5000/yggdrasil-executor:latest
```

### Layer 2: Code LLM Agent Container

**Dockerfile**: `docker/Dockerfile.code-agent`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (Ollama runtime, CUDA if available)
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy code agent (extends base executor)
COPY agents/ agents/
COPY agent-executors/ agent-executors/
COPY requirements.txt .

# Add LLM-specific dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir \
    ollama \
    langchain \
    pydantic

# Copy code agent
COPY agent-executors/code-agent.py executor.py

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# Run code agent on different port to avoid conflicts
EXPOSE 5001
CMD ["python3", "executor.py"]
```

### Layer 3: Coordinator Container

**Dockerfile**: `docker/Dockerfile.coordinator`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY coordinator/ coordinator/
COPY agents/ agents/
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY coordinator/coordinator.py .

# No HEALTHCHECK for coordinator (long-running)

CMD ["python3", "coordinator.py"]
```

### Layer 4: Private Registry on Surtr

**docker-compose.yml**: Self-hosted OCI registry

```yaml
version: '3.8'

services:
  registry:
    image: docker.io/library/registry:2
    container_name: yggdrasil-registry
    ports:
      - "5000:5000"
    volumes:
      - /data/registry:/var/lib/registry
      - /data/registry/config.yml:/etc/docker/registry/config.yml:ro
    environment:
      REGISTRY_STORAGE_FILESYSTEM_ROOTDIRECTORY: /var/lib/registry
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/v2/"]
      interval: 30s
      timeout: 5s
      retries: 3

  # Optional: Registry UI for browsing images
  registry-ui:
    image: joxit/docker-registry-ui:latest
    container_name: yggdrasil-registry-ui
    ports:
      - "8080:80"
    environment:
      REGISTRY_URL: http://localhost:5000
      REGISTRY_TITLE: "Yggdrasil Registry"
    depends_on:
      - registry
    restart: always
```

---

## New Component: Code LLM Agent

### What It Does

- Runs Qwen Code 3B or Granite Code 8B locally on Surtr
- Specialized executor that:
  - Receives coding tasks from Coordinator
  - Uses LLM to analyze + generate code
  - Handles: refactoring, testing, linting, boilerplate generation
  - Returns code + explanation in result

### Handler Examples

**agent-executors/code-agent.py**:

```python
#!/usr/bin/env python3
"""
Code LLM Agent

Executes coding tasks using local code models (Qwen, Granite).
Reduces human developer cognitive load by handling routine code work.

Handlers:
  code-generate    → Write new code from spec
  code-refactor    → Improve existing code
  code-test        → Generate unit tests
  code-document    → Add docstrings
  code-fix-lint    → Auto-fix linting errors
"""

import sys
sys.path.insert(0, '/var/home/matt/homelab-config')

from agents.base_agent import AgentExecutor
import logging
import json

logger = logging.getLogger(__name__)

class CodeLLMAgent(AgentExecutor):
    """LLM-powered code agent for autonomous coding tasks"""
    
    EXECUTOR_NAME = "code-agent"
    EXECUTOR_VERSION = "0.1.0"
    
    def __init__(self):
        super().__init__()
        # Initialize Ollama client
        try:
            import ollama
            self.ollama = ollama
            self.model = "qwen2.5-coder:3b"  # Or granite-code:8b
        except ImportError:
            logger.warning("Ollama not available; using fallback mode")
            self.ollama = None
    
    def register_handlers(self):
        self.task_handlers = {
            'code-generate': self.handle_code_generate,
            'code-refactor': self.handle_code_refactor,
            'code-test': self.handle_code_test,
            'code-document': self.handle_code_document,
            'code-fix-lint': self.handle_code_fix_lint,
        }
    
    def handle_code_generate(self, params):
        """Generate new code from specification"""
        spec = params.get('spec', '')
        language = params.get('language', 'python')
        
        if not spec:
            return {'output': 'Error: spec required', 'success': False}
        
        prompt = f"""Generate {language} code for this specification:

{spec}

Return only the code, no explanation."""
        
        response = self.ollama.generate(
            model=self.model,
            prompt=prompt,
            stream=False
        )
        
        code = response['response']
        
        # Validate syntax
        if language == 'python':
            try:
                compile(code, '<string>', 'exec')
                validity = 'Valid Python syntax'
            except SyntaxError as e:
                validity = f'Syntax error: {e}'
        else:
            validity = 'Syntax not checked'
        
        return {
            'output': code,
            'success': True,
            'language': language,
            'validity': validity
        }
    
    def handle_code_refactor(self, params):
        """Improve code quality, readability"""
        code = params.get('code', '')
        guidance = params.get('guidance', 'improve readability and performance')
        
        if not code:
            return {'output': 'Error: code required', 'success': False}
        
        prompt = f"""Refactor this code to {guidance}:

{code}

Return only the refactored code, no explanation."""
        
        response = self.ollama.generate(
            model=self.model,
            prompt=prompt,
            stream=False
        )
        
        return {
            'output': response['response'],
            'success': True,
            'guidance': guidance
        }
    
    def handle_code_test(self, params):
        """Generate unit tests for code"""
        code = params.get('code', '')
        language = params.get('language', 'python')
        
        if not code:
            return {'output': 'Error: code required', 'success': False}
        
        test_framework = 'pytest' if language == 'python' else 'jest'
        
        prompt = f"""Generate {test_framework} unit tests for this {language} code:

{code}

Return only the test code, no explanation."""
        
        response = self.ollama.generate(
            model=self.model,
            prompt=prompt,
            stream=False
        )
        
        return {
            'output': response['response'],
            'success': True,
            'framework': test_framework
        }
    
    def handle_code_document(self, params):
        """Add docstrings and comments"""
        code = params.get('code', '')
        language = params.get('language', 'python')
        style = params.get('style', 'google')  # google, numpy, sphinx
        
        if not code:
            return {'output': 'Error: code required', 'success': False}
        
        prompt = f"""Add {style}-style docstrings and comments to this {language} code:

{code}

Return only the documented code, no explanation."""
        
        response = self.ollama.generate(
            model=self.model,
            prompt=prompt,
            stream=False
        )
        
        return {
            'output': response['response'],
            'success': True,
            'docstring_style': style
        }
    
    def handle_code_fix_lint(self, params):
        """Auto-fix linting errors"""
        code = params.get('code', '')
        language = params.get('language', 'python')
        linter = params.get('linter', 'flake8')  # flake8, eslint, etc.
        
        # Run linter to get errors
        if language == 'python':
            result = self.run_command(f'echo "{code}" | python3 -m {linter} -', timeout=30)
            errors = result['output']
        else:
            errors = 'Linter not configured for this language'
        
        prompt = f"""Fix {linter} linting errors in this {language} code:

Code:
{code}

Errors:
{errors}

Return only the fixed code, no explanation."""
        
        response = self.ollama.generate(
            model=self.model,
            prompt=prompt,
            stream=False
        )
        
        return {
            'output': response['response'],
            'success': True,
            'linter': linter,
            'fixed_errors': errors
        }

if __name__ == '__main__':
    agent = CodeLLMAgent()
    agent.run(host='0.0.0.0', port=5001, debug=False)
```

---

## Deployment Plan

### Phase A: Container Registry on Surtr (Week 1)

```bash
# 1. Create registry data directory
mkdir -p /data/registry

# 2. Deploy registry container
cd ~/homelab-config
podman-compose -f docker/docker-compose.registry.yml up -d

# 3. Verify registry
curl http://localhost:5000/v2/
# Expected: {} (empty repo list)

# 4. Tag Surtr as registry host in Beads
bd create --title "Surtr: Deploy container registry" --type task \
  --label infrastructure --label registry
```

### Phase B: Build + Push Executor Images (Week 1)

```bash
# 1. Build executor image
podman build -t localhost:5000/yggdrasil-executor:v0.2.0 \
  -f docker/Dockerfile.executor .

# 2. Push to registry
podman push localhost:5000/yggdrasil-executor:v0.2.0

# 3. Tag as latest
podman tag localhost:5000/yggdrasil-executor:v0.2.0 \
  localhost:5000/yggdrasil-executor:latest
podman push localhost:5000/yggdrasil-executor:latest

# 4. Build coordinator image
podman build -t localhost:5000/yggdrasil-coordinator:v0.2.0 \
  -f docker/Dockerfile.coordinator .
podman push localhost:5000/yggdrasil-coordinator:v0.2.0
```

### Phase C: Deploy Containers on Machines (Week 2)

**On Fenrir**:
```bash
podman run -d \
  --name yggdrasil-executor \
  --net host \
  -v ~/.ssh:/root/.ssh:ro \
  localhost:5000/yggdrasil-executor:latest
```

**On Surtr**:
```bash
podman run -d \
  --name yggdrasil-executor \
  --net host \
  --gpus all \
  -v ~/.ssh:/root/.ssh:ro \
  localhost:5000/yggdrasil-executor:latest
```

**On Huginn**:
```bash
podman run -d \
  --name yggdrasil-executor \
  --net host \
  -v ~/.ssh:/root/.ssh:ro \
  localhost:5000/yggdrasil-executor:latest
```

### Phase D: Code LLM Agent on Surtr (Week 2-3)

```bash
# 1. Deploy Ollama container (if not already running)
podman run -d \
  --name ollama \
  --gpus all \
  -p 11434:11434 \
  ollama/ollama:latest

# 2. Pull code model
podman exec ollama ollama pull qwen2.5-coder:3b

# 3. Build code agent image
podman build -t localhost:5000/yggdrasil-code-agent:v0.1.0 \
  -f docker/Dockerfile.code-agent .
podman push localhost:5000/yggdrasil-code-agent:v0.1.0

# 4. Deploy code agent
podman run -d \
  --name yggdrasil-code-agent \
  --net host \
  --gpus all \
  -e OLLAMA_HOST=http://localhost:11434 \
  localhost:5000/yggdrasil-code-agent:v0.1.0

# 5. Create Beads tasks for code LLM
bd create --title "Code Agent: Refactor agents/base_agent.py" --type task \
  --label code-generation --label llm --description "Improve code style"
```

### Phase E: Update Coordinator Routing (Week 3)

Add code agent to Coordinator:

```python
# coordinator/coordinator.py

EXECUTORS = {
    'fenrir-executor': 'fenrir.nessie-hippocampus.ts.net:5000',
    'surtr-executor': 'surtr.nessie-hippocampus.ts.net:5000',
    'huginn-executor': 'huginn.nessie-hippocampus.ts.net:5000',
    'code-agent': 'surtr.nessie-hippocampus.ts.net:5001',  # NEW
}

ROUTING = {
    'dev-': 'fenrir-executor',
    'code-': 'code-agent',  # Route code tasks to LLM
    'git-': 'fenrir-executor',
    'llm-': 'surtr-executor',
    'ollama-': 'surtr-executor',
    'ops-': 'huginn-executor',
    'power-': 'huginn-executor',
    'plan-': 'fenrir-executor',
}
```

---

## Why Code LLM Reduces Human Load

### Tasks It Can Handle Autonomously

**Tier 1 (Easy, No Human Review)**:
- Auto-fix lint errors
- Generate docstrings
- Format code

**Tier 2 (Medium, Light Review)**:
- Refactor code for readability
- Generate unit tests
- Generate simple boilerplate

**Tier 3 (Hard, Full Review)**:
- Implement new features (needs spec review)
- Architecture decisions (needs approval)
- Security fixes (needs audit)

### Examples

**Before** (Human does this):
1. Create task: "Add error handling to coordinator"
2. Read code context
3. Write fix
4. Test fix
5. Commit → update Beads

**After** (Code LLM + Human review):
1. Create task: "Add error handling to coordinator"
2. Code LLM auto-generates fix + tests
3. Human reviews 5 min (diff, tests pass)
4. Human approves → Coordinator commits + marks closed

**Time saved**: ~1 hour → 5 min

### Scaling Implication

- **Phase 1** (Current): You handle all ~30 Phase 1-2 tasks manually
- **Phase 3** (With Code LLM): Code LLM handles refactoring/testing, you handle architecture + reviews
- **Phase 4+** (Multi-agent): Each machine has specialized agents, code LLM coordinates smaller tasks
- **Result**: You shift from "executor" to "director" (create goals, review results, make strategic decisions)

---

## Implementation Files to Create

```
docker/
├── Dockerfile.executor              # Base executor image
├── Dockerfile.coordinator           # Coordinator image
├── Dockerfile.code-agent            # Code LLM agent image
├── docker-compose.registry.yml      # Surtr registry + UI
├── docker-compose.executors.yml     # Run all executors (for testing)
└── .containerignore                 # Exclude from build context

scripts/
├── build-and-push.sh               # Build all images, push to registry
├── deploy-registry.sh              # Setup registry on Surtr
├── deploy-executors.sh             # Deploy containers to each machine
└── pull-code-model.sh              # Download code model to Surtr

kubernetes/ (optional Phase 4)
├── deployment-executor.yml          # K8s manifests (future)
├── deployment-coordinator.yml       # K8s manifests (future)
└── deployment-code-agent.yml        # K8s manifests (future)
```

---

## Risk Mitigation

### Container Runtime Issues

**Risk**: Podman/Docker not available, version conflicts

**Mitigation**:
- Bluefin comes with Podman pre-installed
- Use UBI base images (Red Hat maintained)
- Pin Python version to 3.11 (long-term support)
- Document fallback: bare-metal agent execution still works

### Registry Availability

**Risk**: Registry goes down, agents can't pull images

**Mitigation**:
- Registry redundancy: pull to all machines on deployment
- Keep local image caches: `podman pull --all`
- Fallback to git clone if registry unavailable
- Test registry health in Coordinator

### Model Size / Disk Space

**Risk**: Code LLM models are 2-8GB; Surtr storage full

**Mitigation**:
- Use smaller models (3B > 8B initially)
- Compress models with quantization (GGUF format)
- Monitor `/data` disk usage
- Archive old images to external storage

### GPU Access in Containers

**Risk**: Container can't access host GPU

**Mitigation**:
- Use `--gpus all` flag in podman run
- Verify with `podman run nvidia/cuda nvidia-smi`
- Document GPU passthrough for Bluefin

---

## Success Metrics

**Week 1**: 
- [ ] Registry deployed on Surtr
- [ ] Executor image builds + pushes successfully
- [ ] Coordinator image builds + pushes successfully

**Week 2**:
- [ ] Executor containers running on Fenrir, Surtr, Huginn
- [ ] Health checks passing (curl /health)
- [ ] Coordinator routes to containers instead of bare-metal executors

**Week 3**:
- [ ] Code LLM agent running on Surtr
- [ ] Code generation working (test with manual curl)
- [ ] Coordinator routes code-* tasks to code agent
- [ ] First autonomously-executed Beads task (code refactor)

**Week 4+**:
- [ ] 50% of Phase 1-2 tasks automated (code refactor, testing, linting)
- [ ] Human involvement reduced to review + approval
- [ ] Ready to plan Phase 3 (Planning Agent, multi-agent routing)

---

## Next: Immediate Action Items

1. **Create Dockerfiles** (`docker/Dockerfile.{executor,coordinator,code-agent}`)
2. **Create registry compose** (`docker/docker-compose.registry.yml`)
3. **Add to Beads**: "Deploy container registry on Surtr"
4. **Build + test locally**: `podman build -f docker/Dockerfile.executor .`
5. **Document container deployment**: SSH to Surtr, run containers
6. **Update AGENTS.md**: Add containerization section

Would you like me to start implementing the Dockerfiles and docker-compose configs now?
