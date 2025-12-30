# Async Dispatcher: Implementation Summary

**Date**: 2025-12-30  
**Status**: ✅ Ready for deployment

## What Was Improved

The original ThreadPoolExecutor-based dispatcher had a critical limitation: it allowed only **one active task per agent type** (code/text/reasoning), even though the three GPU hosts could easily handle multiple concurrent tasks.

### Before
```
ThreadPoolExecutor(max_workers=3):
  Thread 1: code agent (either busy or idle)
  Thread 2: text agent (either busy or idle)  
  Thread 3: reasoning agent (either busy or idle)

Result: Maximum 3 concurrent tasks (and usually fewer due to workload imbalance)
```

### After
```
AsyncYggdrasilAgent with HostConcurrencyManager:
  surtr-reasoning: Semaphore(2)   → 2 concurrent reasoning tasks
  fenrir-chat:     Semaphore(3)   → 3 concurrent text tasks
  skadi-code:      Semaphore(2)   → 2 concurrent code tasks

Result: Up to 7 concurrent tasks + better GPU utilization
```

## Key Improvements

| Aspect | Before | After |
|--------|--------|-------|
| Max concurrent | 3 | **7+** |
| Concurrency model | Per-agent lock | **Per-host semaphore** |
| Priority support | None (FIFO) | **Beads priorities** |
| Architecture | Thread + asyncio | **Pure asyncio** |
| CPU overhead | High (threads) | **Low (coroutines)** |
| Task ordering | First-come-first-served | **Priority-aware** |

## Files Created

### Core Implementation
- **`async_dispatcher.py`** (400 lines)
  - `HostConcurrencyManager`: Per-host semaphore management
  - `AsyncBeadsClient`: Priority-sorted task loading
  - `AsyncYggdrasilAgent`: Main dispatcher loop

### Documentation
- **`ASYNC_DISPATCHER.md`** (300 lines)
  - Configuration guide
  - Performance tuning
  - Troubleshooting

- **`CONCURRENCY_COMPARISON.md`** (400 lines)
  - Architecture comparison
  - Performance benchmarks
  - Migration path

### Examples & Testing
- **`examples.py`** (200 lines)
  - Create test workloads
  - Monitor queue depth
  - Benchmark both dispatchers

## Files Modified

- **`cli.py`**: Added `--async` flag to `loop` command

## Architecture

```
AsyncYggdrasilAgent.run_loop()
  │
  ├─ Poll Beads every 2 seconds
  │  └─ get_ready_tasks_sorted() returns tasks ordered by:
  │     1. Priority (0=critical, 3=low)
  │     2. Created timestamp (FIFO within same priority)
  │
  ├─ For each ready task:
  │  ├─ Detect task type (code/text/reasoning)
  │  ├─ Route to host (skadi/fenrir/surtr)
  │  ├─ Check host semaphore has available slots
  │  └─ Create asyncio task: _process_task_with_limit()
  │
  └─ _process_task_with_limit(task, host):
     ├─ await concurrency_mgr.acquire(host)  ◄── Blocks here, not event loop
     ├─ register_task(host, task_id)
     ├─ await beads.update_task(..., 'in_progress')
     ├─ await handler(task)  ◄── Run LLM (non-blocking)
     ├─ await beads.update_task(..., 'closed')
     └─ concurrency_mgr.release(host)
```

## Performance Expectations

### Synthetic Benchmark (30 mixed tasks: 10 code + 10 text + 10 reasoning)

**Thread-based** (legacy):
- Code agent: 10 tasks × 30s avg = 300s
- Text agent: 10 tasks × 20s avg = 200s
- Reasoning agent: 10 tasks × 40s avg = 400s
- **Sequential bottleneck**: ~400s total

**Async** (new):
- Skadi (code): 10 tasks / 2 concurrent = 5 batches × 30s = 150s
- Fenrir (text): 10 tasks / 3 concurrent = 4 batches × 20s = 80s
- Surtr (reasoning): 10 tasks / 2 concurrent = 5 batches × 40s = 200s
- **Parallel max**: ~200s total

**Expected speedup**: 2x (400s → 200s)

### Actual Results (will vary with LLM response times):
- Test with: `python examples.py create 30 && python ygg.py loop --async`

## Configuration

Default semaphore counts in `async_dispatcher.py`:
```python
self.host_config = {
    'surtr-reasoning': 2,    # 8GB GPU, heavy reasoning
    'fenrir-chat': 3,        # 6GB GPU, lighter text
    'skadi-code': 2,         # 4GB GPU, moderate code gen
}
```

Adjust based on GPU VRAM during testing:
- Monitor with: `watch nvidia-smi` on each host
- Increase count if GPU util <70%
- Decrease count if memory >95%

## Usage

### Start Async Dispatcher (Recommended)
```bash
cd ~/homelab-config/yggdrasil-agent
source .venv/bin/activate
python ygg.py loop --async
```

### Start Legacy Dispatcher (for comparison)
```bash
python ygg.py loop  # No --async flag
```

### Monitor Queue
```bash
# Terminal 2
python examples.py monitor
```

### Create Test Workload
```bash
python examples.py create 20
```

## Testing Results

### Initialization Test
```
✓ AsyncYggdrasilAgent initialized
  Host config: {'surtr-reasoning': 2, 'fenrir-chat': 3, 'skadi-code': 2}
  Task handlers: ['code-generation', 'text-processing', 'reasoning', 'summarize', 'general']
  Semaphores: ['surtr-reasoning', 'fenrir-chat', 'skadi-code']
```

### CLI Integration Test
```
Usage: ygg.py loop [OPTIONS]
  Continuously process tasks (dispatches to all available agents)

Options:
  --interval INTEGER  Poll interval (seconds)
  --async             Use async dispatcher (better concurrency)
  --help              Show this message and exit.
```

## Backwards Compatibility

✅ **Fully compatible with existing Beads format**
- Both dispatchers use same `.beads/issues.jsonl`
- Can switch between them without data loss
- In-flight tasks are marked `blocked` on error (can be rerun)

## Next Steps

1. **Test with real workload** (10-20 mixed tasks)
2. **Monitor GPU utilization** during test run
3. **Tune semaphore counts** if needed
4. **Consider default change** (make --async the default in production)
5. **Archive documentation** (ASYNC_DISPATCHER.md, CONCURRENCY_COMPARISON.md)

## Deployment Checklist

- [x] Implementation complete
- [x] CLI integration complete
- [x] Documentation complete
- [x] Examples for testing
- [x] Backwards compatible with legacy code
- [ ] Real-world testing (when you have time)
- [ ] Performance benchmarking (vs legacy)
- [ ] GPU memory tuning for your workloads
- [ ] Consider making --async default

## Support Resources

- **Quick Start**: ASYNC_DISPATCHER.md
- **Architecture**: CONCURRENCY_COMPARISON.md  
- **Examples**: `python examples.py help`
- **Troubleshooting**: ASYNC_DISPATCHER.md → Troubleshooting section

## Known Limitations

1. **No built-in request cancellation** - tasks continue even if cancelled
   - Workaround: Mark as 'blocked' manually, then rerun
2. **Priority is soft** - only affects ordering, not preemption
   - Critical task won't interrupt running low-priority task
   - Will start next if host has available slots
3. **Artifact handler runs in executor** - slightly slower than native async
   - Trade-off: Simplicity vs perfect async purity

## Future Improvements (optional)

- Task cancellation support (mark as 'cancelled' instead of 'blocked')
- Per-task timeout with auto-failure
- Metrics collection (average task time, queue depth over time)
- Web UI for monitoring
- Dynamic semaphore adjustment based on GPU memory

