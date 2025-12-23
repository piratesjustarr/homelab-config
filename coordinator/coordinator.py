#!/usr/bin/env python3
"""
Coordinator Agent

Central dispatch point that:
1. Reads Beads for ready work
2. Routes tasks to appropriate executors
3. Syncs results back to Beads
"""

import subprocess
import json
import requests
import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [Coordinator] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/var/log/yggdrasil-coordinator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class Coordinator:
    """Central task dispatcher using Beads as source of truth"""
    
    # Executor locations (hostname.tailnet)
    EXECUTORS = {
        'fenrir-executor': 'fenrir.nessie-hippocampus.ts.net:5000',
        'surtr-executor': 'surtr.nessie-hippocampus.ts.net:5000',
        'huginn-executor': 'huginn.nessie-hippocampus.ts.net:5000',
    }
    
    # Task type → executor routing
    ROUTING = {
        'dev-': 'fenrir-executor',
        'code-': 'fenrir-executor',
        'git-': 'fenrir-executor',
        'llm-': 'surtr-executor',
        'ollama-': 'surtr-executor',
        'ops-': 'huginn-executor',
        'power-': 'huginn-executor',
        'plan-': 'fenrir-executor',  # Or surtr
    }
    
    def __init__(self, beads_repo: str = '~/homelab-config/yggdrasil-beads'):
        self.beads_repo = beads_repo
        self.default_executor = 'surtr-executor'
        self.retry_limit = 3
        self.task_timeout = 600  # 10 minutes default
    
    def get_ready_tasks(self) -> List[Dict[str, Any]]:
        """
        Query Beads for ready work.
        
        Returns:
            List of tasks ready to execute (from 'bd ready')
        """
        try:
            # Run bd export to get full task list
            result = subprocess.run(
                f'cd {self.beads_repo} && bd export',
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error(f"bd export failed: {result.stderr}")
                return []
            
            # Parse JSONL output
            tasks = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        task = json.loads(line)
                        # Filter for open/ready tasks only
                        if task.get('status') == 'open' and not task.get('blocked'):
                            tasks.append(task)
                    except json.JSONDecodeError:
                        pass
            
            logger.info(f"Found {len(tasks)} ready tasks")
            return tasks
        
        except Exception as e:
            logger.error(f"Failed to get ready tasks: {e}")
            return []
    
    def route_task(self, task: Dict[str, Any]) -> str:
        """
        Determine which executor should handle this task.
        
        Args:
            task: Task dict with 'type' and optional 'labels'
        
        Returns:
            Executor name (e.g., 'fenrir-executor')
        """
        task_type = task.get('type', '')
        labels = task.get('labels', [])
        
        # Check if task specifies preferred executor in labels
        for label in labels:
            if label.endswith('-executor'):
                if label in self.EXECUTORS:
                    return label
        
        # Route by task type prefix
        for prefix, executor in self.ROUTING.items():
            if task_type.startswith(prefix):
                return executor
        
        # Default to most powerful machine
        return self.default_executor
    
    def dispatch_task(self, task: Dict[str, Any], executor: str) -> Dict[str, Any]:
        """
        Send task to executor via HTTP.
        
        Args:
            task: Task to execute
            executor: Executor name
        
        Returns:
            Result dict from executor
        """
        if executor not in self.EXECUTORS:
            logger.error(f"Unknown executor: {executor}")
            return {'status': 'error', 'error': 'Unknown executor'}
        
        url = f"http://{self.EXECUTORS[executor]}/execute"
        
        # Prepare payload
        payload = {
            'task_id': task.get('id'),
            'type': task.get('type'),
            'params': task.get('params', {}),
        }
        
        try:
            logger.info(f"Dispatching {task.get('id')} to {executor}")
            
            response = requests.post(
                url,
                json=payload,
                timeout=self.task_timeout
            )
            
            if response.ok:
                result = response.json()
                logger.info(f"Task {task.get('id')} completed: {result.get('status')}")
                return result
            else:
                logger.error(f"Executor returned {response.status_code}: {response.text}")
                return {
                    'status': 'error',
                    'error': f"HTTP {response.status_code}",
                    'task_id': task.get('id')
                }
        
        except requests.Timeout:
            logger.error(f"Task {task.get('id')} timed out ({self.task_timeout}s)")
            return {
                'status': 'error',
                'error': f'Timeout after {self.task_timeout}s',
                'task_id': task.get('id')
            }
        
        except Exception as e:
            logger.error(f"Failed to dispatch task: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'task_id': task.get('id')
            }
    
    def sync_result_to_beads(self, task_id: str, result: Dict[str, Any]):
        """
        Update Beads with task result.
        
        Args:
            task_id: Beads task ID
            result: Result dict from executor
        """
        status = result.get('status')
        
        if status == 'completed':
            beads_status = 'closed'
        elif status == 'error':
            beads_status = 'blocked'
        else:
            beads_status = 'open'
        
        # Capture output for debugging
        output = result.get('output', '')
        output_summary = output[:500] if output else ''
        
        try:
            # Update Beads
            update_cmd = (
                f'cd {self.beads_repo} && '
                f'bd update {task_id} --status {beads_status}'
            )
            
            result = subprocess.run(
                update_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                logger.info(f"Updated {task_id} → {beads_status}")
            else:
                logger.error(f"Failed to update {task_id}: {result.stderr}")
        
        except Exception as e:
            logger.error(f"Failed to sync result: {e}")
    
    def check_executor_health(self, executor: str) -> bool:
        """
        Check if executor is alive and responsive.
        
        Args:
            executor: Executor name
        
        Returns:
            True if healthy, False otherwise
        """
        if executor not in self.EXECUTORS:
            return False
        
        url = f"http://{self.EXECUTORS[executor]}/health"
        
        try:
            response = requests.get(url, timeout=5)
            return response.ok
        except Exception:
            return False
    
    def run_loop(self, poll_interval: int = 30, max_iterations: Optional[int] = None):
        """
        Main coordinator loop.
        
        Args:
            poll_interval: Seconds between checks (default: 30)
            max_iterations: Max loops (None = infinite)
        """
        iteration = 0
        
        while max_iterations is None or iteration < max_iterations:
            try:
                iteration += 1
                logger.info(f"=== Poll {iteration} @ {datetime.now().isoformat()} ===")
                
                # Get ready tasks
                tasks = self.get_ready_tasks()
                
                if not tasks:
                    logger.info("No ready tasks, sleeping...")
                    time.sleep(poll_interval)
                    continue
                
                # Process first ready task
                task = tasks[0]
                task_id = task.get('id')
                
                # Route to executor
                executor = self.route_task(task)
                logger.info(f"Task {task_id} → {executor}")
                
                # Check executor health
                if not self.check_executor_health(executor):
                    logger.warning(f"Executor {executor} is not healthy, skipping")
                    time.sleep(poll_interval)
                    continue
                
                # Dispatch task
                result = self.dispatch_task(task, executor)
                
                # Sync result back to Beads
                self.sync_result_to_beads(task_id, result)
                
                # Short sleep before next task
                time.sleep(5)
            
            except KeyboardInterrupt:
                logger.info("Coordinator interrupted, shutting down")
                break
            
            except Exception as e:
                logger.exception(f"Coordinator loop error: {e}")
                time.sleep(poll_interval)


def main():
    """Run the coordinator"""
    coordinator = Coordinator()
    
    # Start in infinite loop mode
    # In production, wrap this in a systemd service
    logger.info("Starting Yggdrasil Coordinator")
    coordinator.run_loop(poll_interval=30)


if __name__ == '__main__':
    main()
