#!/usr/bin/env python3
"""
Base Agent Executor

Lightweight HTTP server that receives tasks from Coordinator and executes them.
Each machine (Fenrir, Surtr, Huginn) runs a specialized executor inheriting from this.
"""

from flask import Flask, request, jsonify
from abc import ABC, abstractmethod
import subprocess
import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, Tuple
import os
import signal
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/var/log/yggdrasil-agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AgentExecutor(ABC):
    """
    Base class for task executors.
    
    Each machine (Fenrir, Surtr, Huginn) creates a subclass implementing
    specific handlers for their role.
    
    Usage:
        class FenrirExecutor(AgentExecutor):
            EXECUTOR_NAME = "fenrir-executor"
            
            def handle_code_review(self, params):
                # Run linter, security checks, etc.
                pass
        
        agent = FenrirExecutor()
        agent.run(host='0.0.0.0', port=5000)
    """
    
    EXECUTOR_NAME: str = "generic-executor"
    EXECUTOR_VERSION: str = "0.1.0"
    
    def __init__(self):
        self.app = Flask(self.EXECUTOR_NAME)
        self.setup_routes()
        self.task_handlers = {}
        self.register_handlers()
        
        # Graceful shutdown
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
    
    def setup_routes(self):
        """Register HTTP routes"""
        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify({
                'status': 'healthy',
                'executor': self.EXECUTOR_NAME,
                'version': self.EXECUTOR_VERSION,
                'timestamp': datetime.now().isoformat()
            })
        
        @self.app.route('/execute', methods=['POST'])
        def execute():
            return self.handle_execute_request()
        
        @self.app.route('/status', methods=['GET'])
        def status():
            return jsonify({
                'executor': self.EXECUTOR_NAME,
                'version': self.EXECUTOR_VERSION,
                'handlers': list(self.task_handlers.keys()),
                'timestamp': datetime.now().isoformat()
            })
    
    def register_handlers(self):
        """
        Override in subclass to register task handlers.
        
        Example:
            def register_handlers(self):
                self.task_handlers['code-review'] = self.handle_code_review
                self.task_handlers['git-clone'] = self.handle_git_clone
        """
        pass
    
    def handle_execute_request(self) -> Tuple[Dict[str, Any], int]:
        """HTTP handler for /execute endpoint"""
        
        task = None
        try:
            logger.info(f"Request headers: {dict(request.headers)}")
            logger.info(f"Request content-type: {request.content_type}")
            logger.info(f"Request data (raw): {request.data}")
            task = request.get_json(force=True)
            
            if not task:
                return jsonify({'error': 'No task provided'}), 400
            
            task_id = task.get('task_id')
            task_type = task.get('type')
            params = task.get('params', {})
            
            logger.info(f"Received task {task_id}: {task_type}")
            
            # Check if handler exists
            if task_type not in self.task_handlers:
                error_msg = f"Unknown task type: {task_type}"
                logger.error(error_msg)
                return jsonify({
                    'task_id': task_id,
                    'status': 'error',
                    'error': error_msg
                }), 400
            
            # Execute task
            start_time = time.time()
            handler = self.task_handlers[task_type]
            result = handler(params)
            duration = time.time() - start_time
            
            logger.info(f"Task {task_id} completed in {duration:.2f}s")
            
            return jsonify({
                'task_id': task_id,
                'type': task_type,
                'status': 'completed',
                'output': result.get('output', ''),
                'duration_seconds': duration,
                'timestamp': datetime.now().isoformat()
            }), 200
        
        except Exception as e:
            logger.exception(f"Task execution failed: {e}")
            task_id = task.get('task_id', 'unknown') if task else 'unknown'
            return jsonify({
                'task_id': task_id,
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }), 500
    
    def run_command(self, cmd: str, timeout: int = 300) -> Dict[str, Any]:
        """
        Run a shell command and return output.
        
        Args:
            cmd: Command to run
            timeout: Max seconds to wait (default 5 minutes)
        
        Returns:
            {
                'returncode': int,
                'stdout': str,
                'stderr': str,
                'output': str (combined),
                'duration': float
            }
        """
        logger.info(f"Running: {cmd}")
        
        start = time.time()
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            duration = time.time() - start
            
            combined = result.stdout + result.stderr
            
            return {
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'output': combined,
                'duration': duration,
                'success': result.returncode == 0
            }
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out after {timeout}s: {cmd}")
            return {
                'returncode': -1,
                'stdout': '',
                'stderr': f'Command timed out after {timeout}s',
                'output': f'Command timed out after {timeout}s',
                'duration': timeout,
                'success': False
            }
    
    def run_playbook(self, playbook_path: str, extra_vars: Dict[str, Any] = None,
                     timeout: int = 600) -> Dict[str, Any]:
        """
        Run an Ansible playbook.
        
        Args:
            playbook_path: Path to .yml file
            extra_vars: Extra variables for playbook
            timeout: Max seconds (default 10 minutes)
        
        Returns:
            Result dict with output
        """
        cmd = f"cd ~/homelab-config && ansible-playbook {playbook_path}"
        
        if extra_vars:
            vars_json = json.dumps(extra_vars)
            cmd += f" -e '{vars_json}'"
        
        return self.run_command(cmd, timeout=timeout)
    
    def shutdown(self, signum, frame):
        """Graceful shutdown handler"""
        logger.info(f"Received signal {signum}, shutting down...")
        sys.exit(0)
    
    def run(self, host: str = '0.0.0.0', port: int = 5000, debug: bool = False):
        """
        Start the HTTP server.
        
        Args:
            host: Bind address (default: all interfaces)
            port: Bind port (default: 5000)
            debug: Enable Flask debug mode
        """
        logger.info(f"Starting {self.EXECUTOR_NAME} on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug)


# Example: Standalone dev executor (for testing)
class DevExecutor(AgentExecutor):
    EXECUTOR_NAME = "dev-executor"
    
    def register_handlers(self):
        self.task_handlers['echo'] = self.handle_echo
    
    def handle_echo(self, params):
        message = params.get('message', 'Hello from DevExecutor')
        logger.info(f"Echo: {message}")
        return {'output': message}


if __name__ == '__main__':
    # For testing
    agent = DevExecutor()
    agent.run(port=5000)
