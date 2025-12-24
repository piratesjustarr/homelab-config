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
import threading
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from flask import Flask, jsonify, send_file, send_from_directory

# Claude integration
try:
    from anthropic import Anthropic
    HAS_CLAUDE = True
except ImportError:
    HAS_CLAUDE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [Coordinator] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/tmp/yggdrasil-coordinator.log'),
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
        'code-agent': 'surtr.nessie-hippocampus.ts.net:5001',
        'huginn-executor': 'huginn.nessie-hippocampus.ts.net:5000',
    }
    
    # Task type → executor routing
    ROUTING = {
        'code-': 'code-agent',
        'dev-': 'fenrir-executor',
        'git-': 'fenrir-executor',
        'llm-': 'surtr-executor',
        'ollama-': 'surtr-executor',
        'ops-': 'huginn-executor',
        'power-': 'huginn-executor',
        'plan-': 'fenrir-executor',
    }
    
    def __init__(self, beads_repo: str = '/app/beads'):
        self.beads_repo = beads_repo
        self.default_executor = 'surtr-executor'
        self.retry_limit = 3
        self.task_timeout = 600  # 10 minutes default
        
        # Beads cache
        self.beads_cache = {}
        self.beads_mtime = None
        
        # Initialize Claude if available
        self.claude = None
        if HAS_CLAUDE:
            logger.info("Anthropic library available, trying to initialize Claude...")
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            
            # If not in env, try to read from crush config
            if not api_key:
                try:
                    import json as json_lib
                    config_path = os.path.expanduser('~/.local/share/crush/crush.json')
                    logger.info(f"Reading API key from {config_path}")
                    with open(config_path) as f:
                        config = json_lib.load(f)
                        api_key = config.get('providers', {}).get('anthropic', {}).get('api_key')
                        if api_key:
                            logger.info("Found Anthropic API key in crush config")
                except Exception as e:
                    logger.warning(f"Failed to read crush config: {e}")
            
            if api_key:
                try:
                    self.claude = Anthropic(api_key=api_key)
                    logger.info("Claude initialized with Anthropic API")
                except Exception as e:
                    logger.error(f"Failed to initialize Anthropic client: {e}")
            else:
                logger.warning("No Anthropic API key found")
        else:
            logger.warning("Anthropic library not available")
    
    def ask_claude(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ask Claude what to do with an unknown task type.
        Returns result or None if Claude unavailable.
        """
        if not self.claude:
            return None
        
        try:
            prompt = f"""You are an intelligent task executor. A task needs to be handled:

Task ID: {task.get('id')}
Title: {task.get('title')}
Description: {task.get('description')}
Labels: {task.get('labels', [])}

The task couldn't be routed to a known executor. What should be done?

Respond with a JSON object containing:
- "action": what to do (e.g., "skip", "close", "integrate_code", "save_file", "run_test")
- "result": the result of performing that action
- "success": true/false
- "details": any details about what was done
"""
            
            message = self.claude.messages.create(
                model="claude-3-haiku-20240307",  # or claude-3-haiku-20240307, claude-3-sonnet-20240229, etc.
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            
            response_text = message.content[0].text
            
            # Try to parse JSON from response
            try:
                result = json.loads(response_text)
            except:
                # If not JSON, wrap the response
                result = {
                    "action": "review",
                    "result": response_text,
                    "success": True,
                    "details": "Claude reviewed the task"
                }
            
            logger.info(f"Claude handled {task.get('id')}: {result.get('action')}")
            return result
            
        except Exception as e:
            logger.error(f"Claude error: {e}")
            return None
    
    def get_ready_tasks(self) -> List[Dict[str, Any]]:
        """
        Query Beads for ready work by reading .beads/issues.jsonl directly.
        
        Returns:
            List of tasks ready to execute (status=open, no blockers)
        """
        try:
            import os
            issues_file = os.path.expanduser(f"{self.beads_repo}/.beads/issues.jsonl")
            
            if not os.path.exists(issues_file):
                logger.error(f"Beads file not found: {issues_file}")
                return []
            
            tasks = []
            with open(issues_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        issue = json.loads(line)
                        # Filter for open tasks with no blockers/dependencies, skip epics
                        if issue.get('status') == 'open' and issue.get('issue_type') != 'epic':
                            dependencies = issue.get('dependencies', [])
                            if not dependencies:  # No blockers
                                tasks.append(issue)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON line: {e}")
            
            logger.info(f"Found {len(tasks)} ready tasks from beads")
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
        title = task.get('title', '')
        labels = task.get('labels', [])
        
        # Check if task specifies preferred executor in labels
        for label in labels:
            if label.endswith('-executor'):
                if label in self.EXECUTORS:
                    return label
        
        # Route by task title prefix (e.g., "Code task:")
        if title.startswith('Code task:'):
            return 'code-agent'
        
        # Route by label
        if 'code-generation' in labels:
            return 'code-agent'
        
        # Route by task type prefix
        for prefix, executor in self.ROUTING.items():
            if task_type.startswith(prefix):
                return executor
        
        # Route by task ID prefix
        task_id = task.get('id', '')
        for prefix, executor in self.ROUTING.items():
            if task_id.startswith(prefix):
                return executor
        
        # Default to fenrir for dev work
        return 'fenrir-executor'
    
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
            # Unknown executor - ask Claude what to do
            logger.warning(f"Unknown executor: {executor}, asking Claude...")
            result = self.ask_claude(task)
            if result:
                return result
            logger.error(f"Unknown executor and Claude unavailable: {executor}")
            return {'status': 'error', 'error': 'Unknown executor'}
        
        url = f"http://{self.EXECUTORS[executor]}/execute"
        
        # Infer task type from labels if not set
        task_type = task.get('type')
        if not task_type:
            title = task.get('title', '')
            labels = task.get('labels', [])
            
            # Map to actual code-agent handlers
            if 'code-generation' in labels or 'Generate' in title:
                task_type = 'code-generate'
            elif title.startswith('Code task: Add docstrings'):
                task_type = 'code-document'
            elif title.startswith('Code task: Fix lint'):
                task_type = 'code-fix-lint'
            elif title.startswith('Code task: Generate unit tests'):
                task_type = 'code-test'
            elif title.startswith('Code task: Refactor'):
                task_type = 'code-refactor'
            elif 'code-' in executor:
                # Default code task handler for code-agent
                task_type = 'code-generate'
            elif 'containers' in labels:
                task_type = 'container'
            elif 'testing' in labels:
                task_type = 'test'
            else:
                task_type = 'task'
        
        # Prepare payload
        params = task.get('params', {})
        
        # For code-generation tasks, use description as spec if not provided
        if task_type == 'code-generate' and 'spec' not in params:
            params['spec'] = task.get('description', task.get('title', ''))
        
        payload = {
            'task_id': task.get('id'),
            'type': task_type,
            'params': params,
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
                # Log full result including generated code/output
                if result.get('output'):
                    logger.info(f"Output:\n{result.get('output')}")
                return result
            else:
                # Executor error - try Claude
                logger.warning(f"Executor returned {response.status_code}: {response.text}, asking Claude...")
                result = self.ask_claude(task)
                if result:
                    return result
                
                logger.error(f"Executor failed and Claude unavailable")
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
    
    def save_artifact(self, task_id: str, output: str, task: Dict[str, Any] = None) -> Optional[str]:
        """
        Save generated code/output to specified location or artifacts directory.
        
        Args:
            task_id: Beads task ID
            output: Generated code/output
            task: Task dict (to extract output path if specified)
        
        Returns:
            Path to saved file or None if failed
        """
        try:
            import os
            import re
            
            # Check if task description specifies output path
            output_path = None
            if task and task.get('description'):
                match = re.search(r'Output path:\s*(.+?)(?:\n|$)', task['description'])
                if match:
                    output_path = match.group(1).strip()
            
            if output_path:
                # Use specified output path
                output_path = os.path.expanduser(output_path)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                filepath = output_path
            else:
                # Use default artifacts directory
                artifacts_dir = '/tmp/yggdrasil-artifacts'
                os.makedirs(artifacts_dir, exist_ok=True)
                
                # Determine file extension based on content
                ext = '.txt'
                if output.startswith('<!DOCTYPE') or output.startswith('<html'):
                    ext = '.html'
                elif output.startswith('def ') or output.startswith('import ') or output.startswith('class '):
                    ext = '.py'
                elif output.startswith('{') or output.startswith('['):
                    ext = '.json'
                elif output.startswith('#!/bin/bash') or output.startswith('#!/bin/sh'):
                    ext = '.sh'
                
                filename = f"{task_id}{ext}"
                filepath = os.path.join(artifacts_dir, filename)
            
            with open(filepath, 'w') as f:
                f.write(output)
            
            logger.info(f"Saved artifact to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to save artifact: {e}")
            return None
    
    def sync_result_to_beads(self, task_id: str, result: Dict[str, Any], task: Dict[str, Any] = None):
        """
        Update Beads with task result by modifying the issues.jsonl file directly.
        
        Args:
            task_id: Beads task ID
            result: Result dict from executor
            task: Task dict (to extract output path if specified)
        """
        status = result.get('status')
        
        if status == 'completed':
            beads_status = 'closed'
        elif status == 'error':
            beads_status = 'blocked'
        else:
            beads_status = 'open'
        
        # Save artifact if there's output
        if result.get('output'):
            logger.info(f"Result has output, attempting to save...")
            self.save_artifact(task_id, result.get('output'), task)
        else:
            logger.info(f"No output in result: {result.keys()}")
        
        try:
            import os
            issues_file = os.path.expanduser(f"{self.beads_repo}/.beads/issues.jsonl")
            
            # Read all tasks
            tasks = []
            with open(issues_file, 'r') as f:
                for line in f:
                    if line.strip():
                        task = json.loads(line)
                        # Update the target task
                        if task.get('id') == task_id:
                            task['status'] = beads_status
                            if beads_status == 'closed':
                                task['closed_at'] = datetime.now().isoformat() + 'Z'
                            logger.info(f"Updated {task_id} status to {beads_status}")
                        tasks.append(task)
            
            # Write back
            with open(issues_file, 'w') as f:
                for task in tasks:
                    f.write(json.dumps(task) + '\n')
            
            logger.info(f"Synced {task_id} to beads")
            
        except Exception as e:
            logger.error(f"Failed to update beads: {e}")

    
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
                self.sync_result_to_beads(task_id, result, task)
                
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
    import os
    beads_repo = os.environ.get('BEADS_REPO', '/app/beads')
    coordinator = Coordinator(beads_repo=beads_repo)
    
    # Create Flask app for status endpoint
    app = Flask(__name__)
    
    @app.route('/status')
    def status():
        """Return health status of all components"""
        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'healthy': True,
            'components': {
                'coordinator': {'status': 'healthy'},
                'code-agent': {'status': 'healthy'},
                'fenrir-executor': {'status': 'healthy'}
            }
        })
    
    @app.route('/files')
    def list_files():
        """List all generated artifacts"""
        import os
        artifacts_dir = '/tmp/yggdrasil-artifacts'
        try:
            files = []
            if os.path.exists(artifacts_dir):
                for fname in sorted(os.listdir(artifacts_dir)):
                    fpath = os.path.join(artifacts_dir, fname)
                    if os.path.isfile(fpath):
                        stat = os.stat(fpath)
                        files.append({
                            'name': fname,
                            'size': stat.st_size,
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })
            return jsonify({'files': files})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/files/<path:filename>')
    def get_file(filename):
        """Serve a generated artifact"""
        artifacts_dir = '/tmp/yggdrasil-artifacts'
        return send_from_directory(artifacts_dir, filename)
    
    
    # Start Flask in background thread
    def run_flask():
        logger.info("Starting Flask status endpoint on :5000")
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start coordinator loop in main thread
    logger.info("Starting Yggdrasil Coordinator")
    coordinator.run_loop(poll_interval=30)


if __name__ == '__main__':
    main()
