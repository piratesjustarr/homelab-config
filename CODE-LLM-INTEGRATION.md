# Code LLM Integration Guide

**Status**: Implementation Phase  
**Created**: 2025-12-23  
**Goal**: Enable autonomous code generation/refactoring via local LLM models

---

## Quick Start

### 1. Verify Ollama/RamaLLama on Surtr

```bash
ssh surtr "which ollama || which ramalama"
# Should return path to either tool

# List available models
ssh surtr "ollama list 2>/dev/null || ramalama list"

# If no models, pull a code model
ssh surtr "ollama pull qwen2.5-coder:3b"  # 3.3GB, fast
# OR
ssh surtr "ollama pull granite-code:8b"   # 4.5GB, better quality
```

### 2. Deploy Code Agent

```bash
# Option A: Direct Python (bare-metal)
ssh surtr "cd ~/homelab-config && python3 agent-executors/code-agent.py &"

# Option B: Container (recommended)
cd ~/homelab-config
./scripts/build-and-push.sh
ssh surtr "podman run -d --name code-agent --net host --gpus all localhost:5000/yggdrasil-code-agent:latest"
```

### 3. Test Code Agent

```bash
# Health check
curl http://surtr.nessie-hippocampus.ts.net:5001/health

# Generate code
curl -X POST http://surtr.nessie-hippocampus.ts.net:5001/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "test-gen",
    "type": "code-generate",
    "params": {
      "spec": "Write a function to reverse a string in Python",
      "language": "python"
    }
  }'
```

### 4. Create Code Tasks in Beads

```bash
cd ~/homelab-config/yggdrasil-beads
export PATH="$HOME/.local/bin:$PATH"

# Code refactoring task
bd create --title "Refactor agents/base_agent.py for clarity" \
  --type task --label code-refactor --label llm \
  --description "Improve method names, add docstrings, extract helper functions"

# Code generation task
bd create --title "Generate unit tests for coordinator.py" \
  --type task --label code-test --label llm \
  --description "pytest-based tests for Coordinator class"

# View ready code tasks
bd ready | grep code
```

### 5. Route to Code Agent

Coordinator already routes based on task prefix:

```python
# In coordinator/coordinator.py
ROUTING = {
    'code-': 'code-agent',  # Routes to port 5001
    ...
}
```

Tasks with `code-` prefix OR `code-agent` label will dispatch to code agent on port 5001.

---

## Task Handler Reference

### code-generate

**Generate new code from specification**

```bash
curl -X POST http://surtr.nessie-hippocampus.ts.net:5001/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "gen-1",
    "type": "code-generate",
    "params": {
      "spec": "Write a Flask route that returns JSON",
      "language": "python"
    }
  }'
```

**Response**:
```json
{
  "task_id": "gen-1",
  "type": "code-generate",
  "status": "completed",
  "output": "from flask import Flask, jsonify\n\napp = Flask(__name__)\n\n@app.route('/api/data', methods=['GET'])\ndef get_data():\n    return jsonify({'status': 'ok', 'data': []})\n",
  "success": true,
  "language": "python",
  "validity": "Valid Python syntax",
  "model": "qwen2.5-coder:3b",
  "duration_seconds": 2.3
}
```

### code-refactor

**Improve code quality, readability, performance**

```bash
curl -X POST http://surtr.nessie-hippocampus.ts.net:5001/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "ref-1",
    "type": "code-refactor",
    "params": {
      "code": "x = [1,2,3]\ny = []\nfor i in x:\n    y.append(i*2)",
      "guidance": "use list comprehension and improve variable names",
      "language": "python"
    }
  }'
```

**Response**:
```json
{
  "output": "numbers = [1, 2, 3]\ndoubled = [num * 2 for num in numbers]",
  "success": true,
  "guidance": "use list comprehension and improve variable names",
  "language": "python",
  "model": "qwen2.5-coder:3b"
}
```

### code-test

**Generate unit tests**

```bash
curl -X POST http://surtr.nessie-hippocampus.ts.net:5001/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "test-1",
    "type": "code-test",
    "params": {
      "code": "def add(a, b):\n    return a + b",
      "language": "python"
    }
  }'
```

**Response**:
```json
{
  "output": "import pytest\n\ndef test_add():\n    assert add(2, 3) == 5\n    assert add(-1, 1) == 0\n    assert add(0, 0) == 0\n\ndef test_add_floats():\n    assert add(1.5, 2.5) == 4.0",
  "success": true,
  "framework": "pytest",
  "language": "python",
  "model": "qwen2.5-coder:3b"
}
```

### code-document

**Add docstrings and comments**

```bash
curl -X POST http://surtr.nessie-hippocampus.ts.net:5001/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "doc-1",
    "type": "code-document",
    "params": {
      "code": "def process_data(items, filter_fn):\n    return [x for x in items if filter_fn(x)]",
      "language": "python",
      "style": "google"
    }
  }'
```

**Response**:
```json
{
  "output": "def process_data(items, filter_fn):\n    \"\"\"Filter items based on a predicate function.\n    \n    Args:\n        items: List of items to filter.\n        filter_fn: Function that returns True for items to keep.\n    \n    Returns:\n        List of filtered items.\n    \"\"\"\n    return [x for x in items if filter_fn(x)]",
  "success": true,
  "docstring_style": "google",
  "language": "python",
  "model": "qwen2.5-coder:3b"
}
```

### code-fix-lint

**Auto-fix linting errors**

```bash
curl -X POST http://surtr.nessie-hippocampus.ts.net:5001/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "lint-1",
    "type": "code-fix-lint",
    "params": {
      "code": "x=1;y=2;z=x+y",
      "language": "python",
      "linter": "flake8"
    }
  }'
```

**Response**:
```json
{
  "output": "x = 1\ny = 2\nz = x + y",
  "success": true,
  "linter": "flake8",
  "errors_found": "E225 missing whitespace around operator",
  "language": "python",
  "model": "qwen2.5-coder:3b"
}
```

---

## Which Model to Use?

### Qwen2.5-Coder (Recommended for Phase 1)

```bash
ollama pull qwen2.5-coder:3b    # 3.3GB, ~8K tokens, fast
ollama pull qwen2.5-coder:7b    # 4.7GB, ~32K tokens, better
```

**Pros**:
- Smaller, faster inference
- Good at code generation, refactoring, testing
- Lower GPU memory (fits in RTX 2070)
- Pre-trained on programming languages

**Cons**:
- Less sophisticated architectures
- Struggles with complex multi-file refactoring

### Granite Code (Alternative)

```bash
ollama pull granite-code:8b     # 4.5GB, better quality
```

**Pros**:
- Better quality code generation
- More accurate type hints
- Better at understanding context

**Cons**:
- Slightly slower
- Requires more GPU memory

### Recommendation

Start with **qwen2.5-coder:3b**:
- Fast enough for interactive use
- Good enough for code refactoring, testing, documentation
- Fits in RTX 2070 memory constraints
- Upgrade to 7B or Granite if needed

---

## Integration with Beads Workflow

### Example: Automated Code Refactoring Loop

```bash
# 1. Create refactoring task in Beads
cd ~/homelab-config/yggdrasil-beads
export PATH="$HOME/.local/bin:$PATH"

bd create --title "Refactor coordinator.py" \
  --type task --label code-refactor --label llm

# 2. Get ready tasks
bd ready
# Output shows: yggdrasil-beads-xyz.1: Refactor coordinator.py

# 3. Coordinator automatically:
#    - Polls bd ready
#    - Sees code-refactor task → routes to code-agent
#    - Dispatches to code-agent on port 5001
#    - Code agent generates refactored code
#    - Coordinator gets result
#    - Syncs back: bd update yggdrasil-beads-xyz.1 --status closed

# 4. Human reviews diff:
git diff
# Review generated code, approve or iterate

# 5. If approved, auto-commit:
git add coordinator.py
git commit -m "Refactor: improve variable names and error handling"
```

### Connecting Code LLM to Fenrir's Git Handler

Could create a combined task: "Refactor + commit"

```python
# fenrir-executor.py - NEW handler

def handle_code_refactor_and_commit(self, params):
    """
    Refactor code AND commit the result
    
    1. Read file from repo
    2. Send to code agent for refactoring
    3. Write refactored code back
    4. Commit with message
    """
    repo_path = params.get('repo_path')
    file_path = params.get('file_path')
    guidance = params.get('guidance', 'improve readability')
    commit_msg = params.get('commit_msg')
    
    # Read original code
    result = self.run_command(f'cat {repo_path}/{file_path}')
    original_code = result['output']
    
    # Request refactoring from code agent (via HTTP)
    import requests
    response = requests.post(
        'http://surtr.nessie-hippocampus.ts.net:5001/execute',
        json={
            'task_id': params.get('task_id'),
            'type': 'code-refactor',
            'params': {
                'code': original_code,
                'guidance': guidance,
                'language': 'python'
            }
        },
        timeout=120
    )
    
    refactored = response.json()['output']
    
    # Write back
    with open(f'{repo_path}/{file_path}', 'w') as f:
        f.write(refactored)
    
    # Commit
    commit_result = self.handle_git_commit({
        'repo_path': repo_path,
        'message': commit_msg or f'Refactor {file_path}: {guidance}'
    })
    
    return {
        'output': f'Refactored and committed\n{commit_result["output"]}',
        'success': True
    }
```

---

## Performance Characteristics

### Model Latency (Typical)

| Task | Qwen 3B | Qwen 7B | Granite 8B |
|------|---------|---------|-----------|
| Simple generate (50 lines) | 2-4s | 3-5s | 4-6s |
| Refactor (100 lines) | 3-6s | 4-7s | 5-10s |
| Generate tests (80 lines) | 3-5s | 4-6s | 5-9s |
| Fix lint (50 lines) | 1-2s | 2-3s | 2-4s |
| Add docstrings (100 lines) | 2-4s | 3-5s | 4-8s |

**GPU Memory Usage** (measured on RTX 2070 with 8GB):
- Qwen 3B: ~3.2GB
- Qwen 7B: ~5.8GB (tight, may OOM)
- Granite 8B: ~6.2GB (tight, may OOM)

**Recommendation**: Start with Qwen 3B for Surtr's RTX 2070.

---

## Debugging Code LLM Issues

### Code Agent Not Responding

```bash
# Check if running
ps aux | grep code-agent

# Check logs
tail -f /var/log/yggdrasil-agent.log

# Test manually
curl http://localhost:5001/health

# If containerized
podman logs -f yggdrasil-code-agent
```

### Ollama Connection Issues

```bash
# Verify Ollama is running
ps aux | grep ollama

# Test Ollama API
curl http://localhost:11434/api/tags | jq .

# Model not available
ollama list
ollama pull qwen2.5-coder:3b

# Ollama memory issues (OOM)
# Check with: nvidia-smi
# Reduce batch size or use smaller model
```

### Code Generation Quality Issues

**Problem**: Generated code has syntax errors

**Solution**:
- Add validation step in Beads (review before commit)
- Include example code in prompt
- Use smaller model (Qwen 3B is more conservative)
- Increase temperature for more variation

**Problem**: Generated code doesn't compile

**Solution**:
- Validate syntax in code agent before returning
- Require test validation before commit
- Add "return only valid code" to prompt

---

## Next Steps

### Phase 2a: Code LLM Bootstrap (This Week)

- [ ] Deploy code agent on Surtr
- [ ] Test all 5 handlers manually with curl
- [ ] Create 3-5 code tasks in Beads
- [ ] Run Coordinator, let it execute code tasks autonomously
- [ ] Review generated code quality
- [ ] Document patterns that work well vs. poorly

### Phase 2b: Human Review Loop (Next Week)

- [ ] Create "code refactor + human review" workflow
- [ ] Fenrir reads generated code from Coordinator
- [ ] Sends diff to human for approval
- [ ] Auto-commits if approved
- [ ] Tracks approval ratio (learning feedback)

### Phase 3: Code LLM as Coordinator

- [ ] LLM agent decides task routing
- [ ] "Code agent, what tasks should run next?"
- [ ] Enables planning + decomposition
- [ ] Creates sub-tasks autonomously

---

## Success Criteria

**Week 1**: Code LLM is running and can generate code
- [ ] Agent starts successfully
- [ ] Health check passes
- [ ] All 5 handlers respond to manual requests
- [ ] Generated code is syntactically valid

**Week 2**: Integrated with Beads and Coordinator
- [ ] Code tasks created in Beads
- [ ] Coordinator routes to code agent
- [ ] Tasks complete autonomously
- [ ] Human can review generated code

**Week 3**: Automated code workflows
- [ ] 50% of code tasks run without human execution
- [ ] Quality is acceptable (minimal fixes needed)
- [ ] Feedback loop working (approval tracking)
- [ ] Ready to expand to other task types

---

## References

- Model documentation: https://ollama.ai/library/qwen2.5-coder
- Beads documentation: `./AGENTS.md`, `./AGENT-ARCHITECTURE.md`
- Containerization: `./CONTAINERIZATION-STRATEGY.md`
