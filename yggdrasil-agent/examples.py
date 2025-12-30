#!/usr/bin/env python3
"""
Quick examples for using the async dispatcher.

Run these to test concurrency improvements.
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone


def create_test_tasks(count: int = 10):
    """
    Create test tasks in Beads with mixed types and priorities.
    
    Example:
        create_test_tasks(5)  # Create 5 test tasks
        python ygg.py loop --async
        # Watch them dispatch concurrently
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    
    from beads_sync import BeadsSync
    
    beads_path = Path.home() / 'homelab-config/yggdrasil-beads'
    issues_file = beads_path / '.beads/issues.jsonl'
    
    if not issues_file.exists():
        print(f"Error: Beads not found at {beads_path}")
        return 0
    
    # Define test tasks
    test_tasks = [
        {
            'id': f'test-code-p0-{i}',
            'title': f'Test: Generate code snippet #{i}',
            'description': f'Generate a Python function that returns the number {i}',
            'status': 'open',
            'priority': 0,  # Critical
            'issue_type': 'task',
            'labels': ['code-generation'],
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        for i in range(count // 3)
    ]
    
    test_tasks += [
        {
            'id': f'test-text-p1-{i}',
            'title': f'Test: Summarize content #{i}',
            'description': f'Summarize the following: Lorem ipsum dolor sit amet, consectetur adipiscing elit. #{i}',
            'status': 'open',
            'priority': 1,  # High
            'issue_type': 'task',
            'labels': ['text-processing'],
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        for i in range(count // 3)
    ]
    
    test_tasks += [
        {
            'id': f'test-reason-p2-{i}',
            'title': f'Test: Analyze problem #{i}',
            'description': f'Explain why async is better than threads for task dispatching. Example #{i}',
            'status': 'open',
            'priority': 2,  # Medium
            'issue_type': 'task',
            'labels': ['reasoning'],
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        for i in range(count // 3)
    ]
    
    # Append to Beads
    try:
        with open(issues_file, 'a') as f:
            for task in test_tasks:
                f.write(json.dumps(task) + '\n')
        
        print(f"✓ Created {len(test_tasks)} test tasks")
        print(f"  {len([t for t in test_tasks if t['priority'] == 0])} critical (p0)")
        print(f"  {len([t for t in test_tasks if t['priority'] == 1])} high (p1)")
        print(f"  {len([t for t in test_tasks if t['priority'] == 2])} medium (p2)")
        return len(test_tasks)
    except Exception as e:
        print(f"Error: {e}")
        return 0


def monitor_queue():
    """
    Monitor queue depth and active tasks while dispatcher runs.
    
    Example:
        # Terminal 1:
        python ygg.py loop --async
        
        # Terminal 2:
        python examples.py monitor
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    
    from beads_sync import get_beads_stats
    
    try:
        print("Queue Monitor (Ctrl+C to stop)")
        print("=" * 50)
        
        iteration = 0
        while True:
            import time
            time.sleep(5)
            
            stats = get_beads_stats()
            
            print(f"\n[{iteration}] {datetime.now().strftime('%H:%M:%S')}")
            print(f"  Open:        {stats['open']:2d}")
            print(f"  In Progress: {stats['in_progress']:2d}")
            print(f"  Completed:   {stats['closed']:2d}")
            print(f"  Blocked:     {stats['blocked']:2d}")
            
            total = stats['open'] + stats['in_progress']
            print(f"  Queue depth: {total}")
            
            iteration += 1
    
    except KeyboardInterrupt:
        print("\n✓ Monitor stopped")


def compare_dispatchers():
    """
    Benchmark both dispatchers on same workload.
    
    Example:
        create_test_tasks(30)
        python examples.py compare
    """
    import sys
    import time
    sys.path.insert(0, str(Path(__file__).parent))
    
    from beads_sync import get_beads_stats
    
    print("Dispatcher Comparison")
    print("=" * 60)
    print("This creates a benchmark comparing:")
    print("  1. Legacy thread dispatcher (1 task per agent type)")
    print("  2. Async dispatcher (per-host concurrency)")
    print()
    print("Setup: Create test tasks first")
    print("  python examples.py create 30")
    print()
    print("Run test 1:")
    print("  python ygg.py loop  # Without --async")
    print("  (Record time to clear queue)")
    print()
    print("Reset Beads and create tasks again")
    print()
    print("Run test 2:")
    print("  python ygg.py loop --async  # With --async")
    print("  (Record time to clear queue)")
    print()
    print("Typical results:")
    print("  - Thread: 120-180s for 30 mixed tasks")
    print("  - Async:  60-90s for 30 mixed tasks")
    print("  - Speedup: 2x typical")
    

def example_custom_config():
    """
    Example: Custom host concurrency configuration.
    
    Save as custom_dispatcher.py:
    
        from async_dispatcher import AsyncYggdrasilAgent
        import asyncio
        
        class MyAsyncAgent(AsyncYggdrasilAgent):
            def __init__(self, beads_dir=None):
                super().__init__(beads_dir)
                # Override for high-memory workload
                self.host_config = {
                    'surtr-reasoning': 1,   # Only 1 at a time (heavy)
                    'fenrir-chat': 4,       # More text tasks
                    'skadi-code': 1,        # Memory-constrained
                }
        
        async def main():
            agent = MyAsyncAgent()
            await agent.run_loop(poll_interval=10)
        
        if __name__ == '__main__':
            asyncio.run(main())
    
    Then run:
        python custom_dispatcher.py
    """
    print(__doc__)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python examples.py <command>")
        print()
        print("Commands:")
        print("  create <count>    Create N test tasks (default 10)")
        print("  monitor           Monitor queue depth (run alongside dispatcher)")
        print("  compare           Show comparison benchmark instructions")
        print("  config            Show custom configuration example")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'create':
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        create_test_tasks(count)
    elif command == 'monitor':
        monitor_queue()
    elif command == 'compare':
        compare_dispatchers()
    elif command == 'config':
        example_custom_config()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
