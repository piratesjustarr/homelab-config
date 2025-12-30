#!/usr/bin/env python3
"""
Observability examples and quick-start guide.

Demonstrates:
1. Structured logging
2. Metrics collection
3. Error tracking
4. Retry logic
"""

import asyncio
import json
from pathlib import Path


def show_logging_examples():
    """Show structured logging examples"""
    print("\n" + "="*60)
    print("LOGGING EXAMPLES")
    print("="*60)
    
    from observability import StructuredLogger
    
    logger = StructuredLogger('demo', None)
    
    print("\nExample 1: Task start event")
    print("-" * 40)
    logger.log_task_event(
        'info',
        'task-001',
        'task_started',
        task_type='code-generation',
        host='skadi-code',
        attempt=1,
    )
    print("✓ Logged: task_started event")
    
    print("\nExample 2: Retry scheduled")
    print("-" * 40)
    logger.log_task_event(
        'warning',
        'task-001',
        'task_retry_scheduled',
        attempt=2,
        delay_ms=250,
        error='timeout',
    )
    print("✓ Logged: retry with delay")


def show_metrics_examples():
    """Show metrics collection examples"""
    print("\n" + "="*60)
    print("METRICS EXAMPLES")
    print("="*60)
    
    from observability import MetricsCollector, TaskMetrics, TaskStatus
    import time
    
    metrics = MetricsCollector()
    
    print("\nExample 1: Record successful task")
    print("-" * 40)
    task1 = TaskMetrics(
        task_id='task-001',
        task_type='code-generation',
        host='skadi-code',
        status=TaskStatus.SUCCESS,
        start_time=time.time() - 30,
        end_time=time.time(),
        duration_ms=30000,
        tokens_in=150,
        tokens_out=250,
    )
    metrics.record_task_completion(task1)
    print("✓ Recorded: code-generation task (30s, 150→250 tokens)")
    
    print("\nExample 2: Record failed task with retry")
    print("-" * 40)
    task2 = TaskMetrics(
        task_id='task-002',
        task_type='text-processing',
        host='fenrir-chat',
        status=TaskStatus.RETRY,
        start_time=time.time() - 5,
        end_time=time.time(),
        duration_ms=5000,
        attempt=1,
        error_message='connection timeout',
    )
    metrics.record_task_completion(task2)
    print("✓ Recorded: text-processing task (retry after timeout)")
    
    print("\nExample 3: Export metrics (Prometheus)")
    print("-" * 40)
    prometheus = metrics.export_prometheus()
    print(prometheus[:200] + "...")
    
    print("\nExample 4: Export metrics (JSON)")
    print("-" * 40)
    json_metrics = metrics.export_json()
    print(json.dumps(json_metrics, indent=2)[:300] + "...")


def show_retry_examples():
    """Show retry logic examples"""
    print("\n" + "="*60)
    print("RETRY LOGIC EXAMPLES")
    print("="*60)
    
    from observability import RetryPolicy
    
    print("\nExample 1: Default retry policy")
    print("-" * 40)
    policy = RetryPolicy()
    print(f"Max attempts: {policy.max_attempts}")
    print(f"Backoff delays:")
    for i in range(3):
        delay = policy.get_delay_ms(i)
        print(f"  Attempt {i+1}: {delay}ms")
    
    print("\nExample 2: Custom retry policy")
    print("-" * 40)
    policy = RetryPolicy(
        max_attempts=5,
        initial_delay_ms=50,
        max_delay_ms=10000,
        exponential_base=1.5,
    )
    print(f"Custom policy (5 attempts, 1.5x backoff):")
    for i in range(5):
        delay = policy.get_delay_ms(i)
        print(f"  Attempt {i+1}: {delay}ms")
    
    print("\nExample 3: Retryable vs non-retryable errors")
    print("-" * 40)
    
    retryable_errors = [
        TimeoutError("Request timed out"),
        ConnectionError("Connection refused"),
        RuntimeError("GPU memory exceeded"),
    ]
    
    non_retryable_errors = [
        ValueError("Invalid prompt format"),
        json.JSONDecodeError("Invalid JSON", "", 0),
        TypeError("Type mismatch"),
    ]
    
    policy = RetryPolicy()
    
    print("Retryable (will retry up to 3 times):")
    for err in retryable_errors:
        retry = policy.should_retry(0, err)
        print(f"  {type(err).__name__}: {err} → {'RETRY' if retry else 'FAIL'}")
    
    print("\nNon-retryable (fail immediately):")
    for err in non_retryable_errors:
        retry = policy.should_retry(0, err)
        print(f"  {type(err).__name__}: {err} → {'RETRY' if retry else 'FAIL'}")


def show_error_tracking_examples():
    """Show error tracking examples"""
    print("\n" + "="*60)
    print("ERROR TRACKING EXAMPLES")
    print("="*60)
    
    from observability import ErrorTracker
    
    tracker = ErrorTracker()
    
    print("\nExample 1: Track error with context")
    print("-" * 40)
    try:
        1 / 0
    except Exception as e:
        error_record = tracker.track_error(
            'task-001',
            e,
            context={
                'task_type': 'code-generation',
                'host': 'skadi-code',
                'prompt_length': 500,
            }
        )
        print(f"✓ Tracked: {error_record['error_type']}")
        print(f"  Message: {error_record['error_message']}")
        print(f"  Context: {error_record['context']}")
    
    print("\nExample 2: Format error for Beads storage")
    print("-" * 40)
    try:
        raise RuntimeError("GPU out of memory")
    except Exception as e:
        error_record = tracker.track_error('task-002', e)
        beads_format = tracker.format_for_beads(error_record)
        print(beads_format[:300] + "...")


async def show_retry_wrapper_examples():
    """Show async retry wrapper examples"""
    print("\n" + "="*60)
    print("ASYNC RETRY WRAPPER EXAMPLES")
    print("="*60)
    
    from observability import with_retry, RetryPolicy, get_structured_logger
    
    logger = get_structured_logger()
    policy = RetryPolicy(max_attempts=3, initial_delay_ms=50)
    
    print("\nExample 1: Function that succeeds on retry")
    print("-" * 40)
    
    attempt_count = [0]
    
    async def sometimes_fails():
        attempt_count[0] += 1
        if attempt_count[0] < 3:
            raise TimeoutError("Network timeout")
        return "Success!"
    
    result = await with_retry(
        sometimes_fails,
        policy=policy,
        logger=logger,
        task_id='task-003',
    )
    print(f"✓ Result: {result}")
    print(f"  Attempts: {attempt_count[0]}")
    
    print("\nExample 2: Function that fails after max retries")
    print("-" * 40)
    
    async def always_fails():
        raise TimeoutError("Always times out")
    
    try:
        await with_retry(
            always_fails,
            policy=policy,
            logger=logger,
            task_id='task-004',
        )
    except TimeoutError as e:
        print(f"✓ Failed after {policy.max_attempts} attempts")
        print(f"  Error: {e}")


async def run_async_examples():
    """Run async examples"""
    await show_retry_wrapper_examples()


def main():
    """Run all examples"""
    import sys
    
    if len(sys.argv) < 2:
        print("Observability Examples")
        print("=" * 60)
        print()
        print("Usage: python observability_examples.py <command>")
        print()
        print("Commands:")
        print("  logging   - Show structured logging examples")
        print("  metrics   - Show metrics collection examples")
        print("  retry     - Show retry logic examples")
        print("  errors    - Show error tracking examples")
        print("  async     - Show async retry wrapper examples")
        print("  all       - Run all examples")
        return
    
    command = sys.argv[1]
    
    if command == 'logging':
        show_logging_examples()
    elif command == 'metrics':
        show_metrics_examples()
    elif command == 'retry':
        show_retry_examples()
    elif command == 'errors':
        show_error_tracking_examples()
    elif command == 'async':
        asyncio.run(run_async_examples())
    elif command == 'all':
        show_logging_examples()
        show_metrics_examples()
        show_retry_examples()
        show_error_tracking_examples()
        asyncio.run(run_async_examples())
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == '__main__':
    main()
