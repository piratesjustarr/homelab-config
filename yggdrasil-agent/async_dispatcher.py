#!/usr/bin/env python3
"""
Async-first task dispatcher with per-host concurrency limits and priority scheduling.

Key improvements over thread-based dispatcher:
1. Per-host semaphores limit concurrent tasks per GPU (not per agent type)
2. Priority queue respects Beads task priorities
3. Pure asyncio eliminates thread/asyncio mixing
4. Better resource utilization on constrained GPUs
"""

import asyncio
import json
import logging
import time
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass, field
from heapq import heappush, heappop

logger = logging.getLogger(__name__)

# Import observability (will be lazy-loaded)
observability = None


@dataclass
class PrioritizedTask:
    """Task with priority for queue ordering (for heapq)"""
    priority: int  # 0=highest, 3=lowest (from Beads)
    created_at: float  # Tiebreaker: FIFO for same priority
    task: Dict[str, Any]
    
    def __lt__(self, other):
        """Min-heap ordering: lower priority number = higher urgency"""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at
    
    def __eq__(self, other):
        return (self.priority == other.priority and 
                self.created_at == other.created_at)


class HostConcurrencyManager:
    """Manages per-host concurrency limits"""
    
    def __init__(self, host_configs: Dict[str, int]):
        """
        Initialize concurrency limits per host.
        
        Args:
            host_configs: Dict mapping host names to max concurrent tasks
                         {'surtr-reasoning': 2, 'fenrir-chat': 3, 'skadi-code': 2}
        """
        self.semaphores = {
            host: asyncio.Semaphore(limit)
            for host, limit in host_configs.items()
        }
        self.active_tasks = {host: [] for host in host_configs}
    
    async def acquire(self, host: str) -> None:
        """Acquire a slot for this host (blocks if at limit)"""
        if host not in self.semaphores:
            logger.warning(f"Unknown host: {host}, creating unlimited semaphore")
            self.semaphores[host] = asyncio.Semaphore(1)
            self.active_tasks[host] = []
        
        await self.semaphores[host].acquire()
    
    def release(self, host: str) -> None:
        """Release a slot for this host"""
        if host in self.semaphores:
            self.semaphores[host].release()
    
    def register_task(self, host: str, task_id: str) -> None:
        """Register a task as active"""
        if host in self.active_tasks:
            self.active_tasks[host].append(task_id)
    
    def unregister_task(self, host: str, task_id: str) -> None:
        """Unregister a task"""
        if host in self.active_tasks and task_id in self.active_tasks[host]:
            self.active_tasks[host].remove(task_id)
    
    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """Get current status of all hosts"""
        status = {}
        for host, semaphore in self.semaphores.items():
            status[host] = {
                'active': len(self.active_tasks[host]),
                'available_slots': semaphore._value,
                'tasks': self.active_tasks[host][:3],  # Show first 3
            }
        return status


class AsyncBeadsClient:
    """Async-safe Beads client with priority-aware task loading"""
    
    def __init__(self, beads_dir: str = None):
        if beads_dir:
            self.beads_dir = Path(beads_dir)
        else:
            # Try common locations (container, then local)
            for path in [
                Path('/beads'),
                Path('/vault'),
                Path.home() / 'homelab-config/yggdrasil-beads',
                Path.cwd(),
            ]:
                if (path / '.beads/issues.jsonl').exists():
                    self.beads_dir = path
                    break
            else:
                raise FileNotFoundError("Could not find Beads directory")
        
        self.issues_file = self.beads_dir / '.beads/issues.jsonl'
        self.lock_file = self.beads_dir / '.beads/issues.jsonl.lock'
        logger.info(f"AsyncBeadsClient using: {self.beads_dir}")
    
    async def get_ready_tasks_sorted(self) -> List[Dict[str, Any]]:
        """
        Get open tasks sorted by priority (Beads priority field).
        
        Returns tasks in priority order:
        - priority=0 (critical) first
        - priority=3 (low) last
        - FIFO within same priority
        """
        tasks = []
        try:
            # Run blocking I/O in executor
            loop = asyncio.get_event_loop()
            lines = await loop.run_in_executor(None, self._read_all_lines)
            
            for line in lines:
                if not line.strip():
                    continue
                try:
                    task = json.loads(line)
                    if task.get('status') == 'open' and task.get('issue_type') != 'epic':
                        tasks.append(task)
                except json.JSONDecodeError:
                    continue
            
            # Sort by priority (lower number = higher priority)
            # Then by created_at (FIFO for same priority)
            tasks.sort(
                key=lambda t: (t.get('priority', 2), t.get('created_at', ''))
            )
            
            return tasks
        
        except Exception as e:
            logger.warning(f"Error reading Beads: {e}")
            return []
    
    def _read_all_lines(self) -> List[str]:
        """Helper to read file in executor"""
        try:
            with open(self.issues_file) as f:
                return f.readlines()
        except Exception:
            return []
    
    async def update_task(self, task_id: str, status: str, result: str = None) -> bool:
        """Update task status (async-safe)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._update_task_sync,
            task_id,
            status,
            result
        )
    
    def _update_task_sync(self, task_id: str, status: str, result: str = None) -> bool:
        """Synchronous task update (runs in executor)"""
        import fcntl
        
        lock_acquired = False
        lock_fd = None
        
        try:
            # Try to acquire lock with retries
            for attempt in range(10):
                try:
                    lock_fd = open(self.lock_file, 'w')
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except (IOError, OSError):
                    if attempt == 9:
                        logger.warning(f"Could not acquire lock for {task_id}")
                        lock_fd = None
                        break
                    time.sleep(0.1)
            
            # Read existing data
            lines = []
            try:
                with open(self.issues_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            task = json.loads(line)
                            if task['id'] == task_id:
                                task['status'] = status
                                task['updated_at'] = datetime.now(timezone.utc).isoformat()
                                if status == 'closed':
                                    task['closed_at'] = datetime.now(timezone.utc).isoformat()
                                if result:
                                    task['result'] = result[:32000]
                            lines.append(json.dumps(task))
                        except json.JSONDecodeError:
                            lines.append(line)
            except Exception as e:
                logger.error(f"Error reading Beads: {e}")
                return False
            
            # Write atomically
            temp_file = self.issues_file.with_suffix('.jsonl.tmp')
            try:
                with open(temp_file, 'w') as f:
                    for line in lines:
                        f.write(line + '\n')
                temp_file.replace(self.issues_file)
                logger.info(f"Updated task {task_id} to {status}")
                return True
            except Exception as e:
                logger.error(f"Error writing Beads: {e}")
                if temp_file.exists():
                    temp_file.unlink()
                return False
        
        finally:
            if lock_acquired and lock_fd:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    lock_fd.close()
                    if self.lock_file.exists():
                        self.lock_file.unlink()
                except Exception:
                    pass


class AsyncYggdrasilAgent:
    """
    Async-first multi-agent dispatcher with:
    - Per-host concurrency limits (not per-agent-type)
    - Priority-aware task queue
    - Pure asyncio (no thread/asyncio mixing)
    """
    
    def __init__(self, beads_dir: str = None, enable_observability: bool = True):
        from agent import LLMClient, set_task_context, log_task
        from artifact_handler import ArtifactHandler
        
        self.llm = LLMClient()
        self.beads = AsyncBeadsClient(beads_dir)
        self.artifact_handler = ArtifactHandler()
        self.set_task_context = set_task_context
        self.log_task = log_task
        
        # Initialize observability
        if enable_observability:
            from observability import init_observability
            init_observability()
        
        # Host concurrency limits (adjust based on GPU VRAM)
        # - surtr (8GB): 2 concurrent reasoning tasks
        # - fenrir (6GB): 3 concurrent text tasks
        # - skadi (4GB): 2 concurrent code tasks
        self.host_config = {
            'surtr-reasoning': 2,
            'fenrir-chat': 3,
            'skadi-code': 2,
        }
        
        self.concurrency_mgr = HostConcurrencyManager(self.host_config)
        
        # Task type handlers
        self.handlers = {
            'code-generation': self._handle_code_generation,
            'text-processing': self._handle_text_processing,
            'reasoning': self._handle_reasoning,
            'summarize': self._handle_summarize,
            'general': self._handle_general,
        }
        
        # Map task types to hosts
        self.task_to_host = {
            'code-generation': 'skadi-code',
            'code-refactor': 'skadi-code',
            'code-review': 'skadi-code',
            'text-processing': 'fenrir-chat',
            'text-generation': 'fenrir-chat',
            'summarize': 'fenrir-chat',
            'reasoning': 'surtr-reasoning',
            'analyze': 'surtr-reasoning',
            'general': 'surtr-reasoning',
        }
    
    def _detect_task_type(self, task: Dict[str, Any]) -> str:
        """Detect task type from labels or title"""
        labels = task.get('labels', [])
        title = task.get('title', '').lower()
        
        if 'code-generation' in labels or title.startswith('code:'):
            return 'code-generation'
        if 'code-refactor' in labels:
            return 'code-refactor'
        if 'code-review' in labels:
            return 'code-review'
        if 'text-processing' in labels or 'text-generation' in labels:
            return 'text-processing'
        if 'summarize' in labels:
            return 'summarize'
        if 'reasoning' in labels or 'analyze' in title:
            return 'reasoning'
        
        return 'general'
    
    def _get_host_for_task(self, task_type: str) -> str:
        """Get host name for task type"""
        return self.task_to_host.get(task_type, 'surtr-reasoning')
    
    async def _handle_code_generation(self, task: Dict[str, Any]) -> str:
        """Generate code"""
        description = task.get('description', '')
        title = task.get('title', '')
        
        prompt = f"""Generate code for the following task:

Title: {title}
Description: {description}

Provide complete, working code with comments. Include any necessary imports."""
        
        result = self.llm.generate(prompt, task_type='code-generation')
        
        # Auto-save artifact (run in executor since it's async)
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: asyncio.run(
                    self.artifact_handler.handle_agent_output(
                        task, result, artifact_type='code'
                    )
                )
            )
        except Exception as e:
            logger.warning(f"Failed to save artifact: {e}")
        
        return result
    
    async def _handle_text_processing(self, task: Dict[str, Any]) -> str:
        """Process text"""
        description = task.get('description', '')
        
        prompt = description
        return self.llm.generate(prompt, task_type='text-processing')
    
    async def _handle_summarize(self, task: Dict[str, Any]) -> str:
        """Summarize content"""
        description = task.get('description', '')
        prompt = f"Please summarize the following:\n\n{description}"
        return self.llm.generate(prompt, task_type='text-processing')
    
    async def _handle_reasoning(self, task: Dict[str, Any]) -> str:
        """Handle reasoning tasks"""
        description = task.get('description', '')
        title = task.get('title', '')
        
        prompt = f"""Task: {title}

{description}

Please analyze this thoroughly and provide clear reasoning."""
        
        return self.llm.generate(prompt, task_type='reasoning')
    
    async def _handle_general(self, task: Dict[str, Any]) -> str:
        """Handle general tasks"""
        description = task.get('description', '')
        title = task.get('title', '')
        
        prompt = f"""Task: {title}

{description}

Please complete this task and provide a clear response."""
        
        return self.llm.generate(prompt, task_type='general')
    
    async def _process_task_with_limit(
        self,
        task: Dict[str, Any],
        host: str,
        attempt: int = 1,
    ) -> None:
        """
        Process a single task with host concurrency limit and error handling.
        
        Acquires host semaphore, processes task with retry logic, releases semaphore.
        Stores full error tracebacks in Beads for post-mortem analysis.
        """
        from observability import (
            get_structured_logger, get_metrics, get_error_tracker,
            TaskMetrics, TaskStatus, RetryPolicy, with_retry
        )
        
        task_id = task.get('id')
        task_type = self._detect_task_type(task)
        start_time = time.time()
        
        # Initialize observability
        obs_logger = get_structured_logger()
        metrics_collector = get_metrics()
        error_tracker = get_error_tracker()
        
        try:
            # Acquire slot on host
            await self.concurrency_mgr.acquire(host)
            self.concurrency_mgr.register_task(host, task_id)
            
            # Log task start with structured context
            obs_logger.log_task_event(
                'info',
                task_id,
                'task_started',
                task_type=task_type,
                host=host,
                attempt=attempt,
            )
            
            # Mark as in-progress
            await self.beads.update_task(task_id, 'in_progress')
            
            try:
                # Get handler and process with retry
                handler = self.handlers.get(task_type, self._handle_general)
                
                # Retry policy: exponential backoff for transient errors
                retry_policy = RetryPolicy(
                    max_attempts=3,
                    initial_delay_ms=100,
                    max_delay_ms=5000,
                )
                
                # Execute with retry wrapper
                result = await with_retry(
                    handler,
                    task,
                    policy=retry_policy,
                    logger=obs_logger,
                    task_id=task_id,
                )
                
                result_str = str(result) if not isinstance(result, str) else result
                duration_ms = (time.time() - start_time) * 1000
                
                # Record metrics
                metrics_data = TaskMetrics(
                    task_id=task_id,
                    task_type=task_type,
                    host=host,
                    status=TaskStatus.SUCCESS,
                    start_time=start_time,
                    end_time=time.time(),
                    duration_ms=duration_ms,
                    attempt=attempt,
                )
                metrics_collector.record_task_completion(metrics_data)
                obs_logger.log_metrics(metrics_data)
                
                # Mark as completed
                await self.beads.update_task(task_id, 'closed', result_str)
                
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                
                # Track error with full context
                error_context = {
                    'task_type': task_type,
                    'host': host,
                    'attempt': attempt,
                    'description': task.get('description', '')[:200],  # First 200 chars
                }
                error_record = error_tracker.track_error(task_id, e, error_context)
                
                # Determine if we should retry
                should_retry = (
                    attempt < 3 and
                    retry_policy.should_retry(attempt - 1, e)
                )
                
                # Record failure metrics
                status = TaskStatus.RETRY if should_retry else TaskStatus.FAILED
                metrics_data = TaskMetrics(
                    task_id=task_id,
                    task_type=task_type,
                    host=host,
                    status=status,
                    start_time=start_time,
                    end_time=time.time(),
                    duration_ms=duration_ms,
                    attempt=attempt,
                    error_message=str(e),
                    error_traceback=error_record['traceback'],
                )
                metrics_collector.record_task_completion(metrics_data)
                obs_logger.log_metrics(metrics_data)
                
                if should_retry:
                    # Schedule retry with exponential backoff
                    delay_ms = retry_policy.get_delay_ms(attempt - 1)
                    obs_logger.log_task_event(
                        'warning',
                        task_id,
                        'task_retry_scheduled',
                        attempt=attempt + 1,
                        delay_ms=delay_ms,
                        error=str(e),
                    )
                    
                    # Release semaphore before sleeping
                    self.concurrency_mgr.unregister_task(host, task_id)
                    self.concurrency_mgr.release(host)
                    
                    # Sleep and retry
                    await asyncio.sleep(delay_ms / 1000.0)
                    await self._process_task_with_limit(task, host, attempt + 1)
                else:
                    # Final failure: store full error in Beads
                    error_str = error_tracker.format_for_beads(error_record)
                    await self.beads.update_task(task_id, 'blocked', error_str)
                    
                    obs_logger.log_task_event(
                        'error',
                        task_id,
                        'task_failed_final',
                        attempt=attempt,
                        error=str(e),
                        reason='non_retryable' if not should_retry else 'max_retries',
                    )
        
        finally:
            # Release host slot (if not already released by retry)
            if attempt == 1 or not should_retry:
                self.concurrency_mgr.unregister_task(host, task_id)
                self.concurrency_mgr.release(host)
    
    async def run_loop(self, poll_interval: int = 30) -> None:
        """
        Continuously poll for tasks and dispatch with concurrency limits.
        
        - Tasks are fetched in priority order
        - Each task acquires a host semaphore before processing
        - Hosts can process multiple tasks of same type concurrently
        """
        logger.info("Starting async dispatcher...")
        logger.info(f"Host concurrency config: {self.host_config}")
        
        active_tasks = set()
        
        try:
            while True:
                # Get ready tasks (priority-sorted)
                tasks = await self.beads.get_ready_tasks_sorted()
                
                if not tasks:
                    # Log status and wait
                    status = self.concurrency_mgr.get_status()
                    busy_count = sum(s['active'] for s in status.values())
                    
                    if busy_count > 0:
                        logger.info(f"No new tasks, waiting for {busy_count} to complete...")
                        # Check frequently while work is happening
                        await asyncio.sleep(2)
                    else:
                        logger.info(f"No ready tasks, waiting {poll_interval}s...")
                        await asyncio.sleep(poll_interval)
                    continue
                
                # Try to dispatch ready tasks
                for task in tasks:
                    task_id = task.get('id')
                    
                    # Skip if already dispatched
                    if task_id in active_tasks:
                        continue
                    
                    # Get host for this task
                    task_type = self._detect_task_type(task)
                    host = self._get_host_for_task(task_type)
                    
                    # Check if host has available slots
                    # (don't block, just check)
                    sem = self.concurrency_mgr.semaphores.get(host)
                    if sem and sem._value > 0:
                        # Create task and track it
                        task_coro = self._process_task_with_limit(task, host)
                        task_obj = asyncio.create_task(task_coro)
                        active_tasks.add(task_id)
                        
                        # Clean up completed tasks
                        def task_done_callback(task_id_capture):
                            def callback(future):
                                active_tasks.discard(task_id_capture)
                            return callback
                        
                        task_obj.add_done_callback(task_done_callback(task_id))
                        logger.info(f"Dispatched {task_id} to {host}")
                
                # Log status
                status = self.concurrency_mgr.get_status()
                busy_count = sum(s['active'] for s in status.values())
                if busy_count > 0:
                    logger.info(f"Active tasks: {busy_count} ({json.dumps(status, indent=2)})")
                
                # Wait before next poll
                await asyncio.sleep(2)
        
        except KeyboardInterrupt:
            logger.info("Dispatcher stopping...")
            
            # Wait for in-flight tasks
            if active_tasks:
                logger.info(f"Waiting for {len(active_tasks)} tasks to complete...")
                pending = [t for t in asyncio.all_tasks() if not t.done()]
                if pending:
                    await asyncio.wait(pending, timeout=60)
            
            logger.info("Dispatcher stopped")


class MetricsExporter:
    """Export dispatcher metrics via HTTP endpoint"""
    
    def __init__(self, port: int = 8888):
        self.port = port
    
    async def start_server(self) -> None:
        """Start metrics HTTP server"""
        from aiohttp import web
        from observability import get_metrics
        
        async def metrics_handler(request):
            """Prometheus format metrics endpoint"""
            metrics = get_metrics()
            prometheus_text = metrics.export_prometheus()
            return web.Response(text=prometheus_text, content_type='text/plain')
        
        async def metrics_json_handler(request):
            """JSON format metrics endpoint"""
            metrics = get_metrics()
            json_data = metrics.export_json()
            return web.json_response(json_data)
        
        app = web.Application()
        app.router.add_get('/metrics', metrics_handler)
        app.router.add_get('/metrics.json', metrics_json_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', self.port)
        await site.start()
        
        logger.info(f"Metrics server started on http://localhost:{self.port}/metrics")


async def main():
    """Entry point for async dispatcher"""
    import sys
    
    if '--beads' in sys.argv:
        idx = sys.argv.index('--beads')
        beads_dir = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
    else:
        beads_dir = None
    
    agent = AsyncYggdrasilAgent(beads_dir)
    
    # Optionally start metrics server
    if '--metrics' in sys.argv:
        exporter = MetricsExporter()
        asyncio.create_task(exporter.start_server())
    
    await agent.run_loop()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [Dispatcher] %(levelname)s: %(message)s'
    )
    asyncio.run(main())
