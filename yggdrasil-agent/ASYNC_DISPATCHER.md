# Async Dispatcher: Per-Host Concurrency & Priority Scheduling

**Status**: Ready for production use (replaces thread-based dispatcher)

## Overview

The async dispatcher replaces the legacy thread-based approach with:

1. **Per-host semaphores** - Each GPU host can run N concurrent tasks independently
2. **Priority-aware queue** - Tasks processed by Beads priority (0=critical, 3=low)
3. **Pure asyncio** - No thread/asyncio mixing, better CPU efficiency
4. **Better utilization** - Multiple text tasks on fenrir while code task runs on skadi

## Key Improvements

| Aspect | Thread-Based | Async |
|--------|--------------|-------|
| Max concurrent tasks | 3 (one per agent) | **8** (2+3+2 per host) |
| Task ordering | FIFO | **Priority-based** |
| GPU idle time | High | **Low** |
| CPU overhead | Thread context switches | **Minimal** |
| Scalability | Limited by agent types | **Per-host configurable** |

## Architecture

```
┌─────────────────────────────────────────┐
│    AsyncYggdrasilAgent.run_loop()      │
│  • Polls Beads (priority-sorted)        │
│  • Dispatches tasks with semaphores     │
│  • Tracks active tasks per host         │
└──────────────┬──────────────────────────┘
               │
       ┌───────┴─────────┬─────────────┐
       │                 │             │
  ┌────▼────┐      ┌────▼────┐   ┌───▼────┐
  │surtr-   │      │fenrir-  │   │skadi-  │
  │reasoning│      │chat     │   │code    │
  │Sem: 2   │      │Sem: 3   │   │Sem: 2  │
  └────┬────┘      └────┬────┘   └───┬────┘
       │                │            │
   reasoning    text/summarize    code tasks
   complexity    extraction/gen    generation
```

## Configuration

### 1. Host Concurrency Limits

Edit `async_dispatcher.py` line ~260:

```python
self.host_config = {
    'surtr-reasoning': 2,    # Up to 2 reasoning tasks
    'fenrir-chat': 3,        # Up to 3 text tasks
    'skadi-code': 2,         # Up to 2 code tasks
}
```

**Guidelines**:
- **surtr** (8GB): 2 concurrent (reasoning is heavy)
- **fenrir** (6GB): 3 concurrent (qwen is lighter)
- **skadi** (4GB): 2 concurrent (code generation is moderate)

### 2. Task-to-Host Mapping

Edit `async_dispatcher.py` line ~275:

```python
self.task_to_host = {
    'code-generation': 'skadi-code',
    'text-processing': 'fenrir-chat',
    'reasoning': 'surtr-reasoning',
    'general': 'surtr-reasoning',  # Falls back to reasoning
}
```

## Usage

### Start async dispatcher (recommended)
```bash
cd ~/homelab-config/yggdrasil-agent
source .venv/bin/activate
python ygg.py loop --async
```

### Start legacy dispatcher (for comparison)
```bash
python ygg.py loop  # Without --async flag
```

## Monitoring

The dispatcher logs concurrency status:

```
[Dispatcher] INFO: Active tasks: 6 ({
  'surtr-reasoning': {'active': 2, 'available_slots': 0, 'tasks': [...]},
  'fenrir-chat': {'active': 3, 'available_slots': 0, 'tasks': [...]},
  'skadi-code': {'active': 1, 'available_slots': 1, 'tasks': [...]}
})
```

- **active**: Currently running
- **available_slots**: Free slots (0 = host busy)
- **tasks**: Task IDs running on this host

## Performance Tuning

### Monitor GPU usage:
```bash
# On each host
watch -n 1 'nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader'
```

### Adjust limits based on:
1. **GPU memory saturation**: If >90%, reduce semaphore count
2. **Queue latency**: If tasks wait >1min, increase semaphore count
3. **GPU idle time**: If <50% utilization, increase semaphore count

### Example tuning scenario:

**Observation**: fenrir at 65% utilization, qwen memory ~4GB of 6GB available

**Action**: Increase from 3 to 4 concurrent:
```python
'fenrir-chat': 4,  # More tasks fit in 6GB
```

**Verification**: Re-run, check GPU util reaches 85%+ and memory <5.5GB

## Beads Priority Integration

Tasks are dispatched in priority order:

```bash
# Create critical task
bd new "Urgent code fix" -d "..." -l code-generation -p 0

# Create low-priority task  
bd new "Nice-to-have feature" -d "..." -l code-generation -p 3
```

The dispatcher processes priority=0 first, even if lower-priority tasks arrived earlier.

**Within same priority**, FIFO order is preserved.

## Comparing Dispatchers

### Thread-based (legacy)
- ✓ Simple, familiar model
- ✗ One task per agent type (max 3 concurrent)
- ✗ Higher CPU overhead
- ✗ No priority awareness

### Async (new)
- ✓ 8 concurrent tasks typical
- ✓ Priority-aware scheduling
- ✓ Lower CPU overhead
- ✓ Per-host configurable
- ✓ Better GPU utilization
- ⚠ More complex debugging (if needed)

## Troubleshooting

### Task never starts (stuck in queue)
```bash
# Check host status
python ygg.py status

# If host unhealthy, restart it
ssh surtr ollama serve  # or relevant host
```

### Tasks fail quickly (maybe priority issue)
```bash
# Check which host task was sent to
tail -f logs/ygg.log | grep "task-id"

# Verify task-to-host mapping is correct
```

### Memory usage grows over time
- Async doesn't leak by design
- Check artifact_handler for file handle leaks
- Monitor: `ps aux | grep ygg.py`

## Implementation Details

### Semaphore Semantics
- Per-host Semaphore(N) blocks on `acquire()` if count=0
- Automatically tracks "available_slots"
- No fairness guarantees (FIFO queuing at OS level)

### Priority Queue
- Uses Python heapq (not thread-safe on its own)
- Accessed only in main loop (no race conditions)
- Tasks sorted by (priority, created_at) tuple

### Task Cancellation
- On Ctrl+C, waits up to 60s for in-flight tasks
- Incomplete tasks marked as 'blocked' with error
- No task loss (state saved to Beads atomically)

## Next Steps

1. **Deploy**: Use `--async` flag in production
2. **Monitor**: Watch GPU utilization with tuning above
3. **Tune**: Adjust host_config based on actual workload
4. **Integrate**: Remove legacy dispatcher once fully stable

## Architecture Diagram (Detailed)

```
Main Event Loop (asyncio.run())
│
├─ get_ready_tasks_sorted() ─ Beads (priority-sorted)
│  Returns: [task1(p=0), task2(p=0), task3(p=1), ...]
│
├─ For each task:
│  ├─ Detect task_type (labels/title)
│  ├─ Map to host (task_to_host dict)
│  ├─ Check host semaphore has slots
│  ├─ Create task: _process_task_with_limit(task, host)
│  │  │
│  │  ├─ await concurrency_mgr.acquire(host)  ◄─ BLOCKS if at limit
│  │  ├─ register_task(host, task_id)
│  │  ├─ await beads.update_task(..., 'in_progress')
│  │  ├─ await handler(task)
│  │  ├─ await beads.update_task(..., 'closed')
│  │  └─ concurrency_mgr.release(host)
│  │
│  └─ Track active task IDs
│
└─ Loop: sleep(2), repeat
```

All task processing happens concurrently thanks to `asyncio.create_task()`.

