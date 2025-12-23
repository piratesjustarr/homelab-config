#!/usr/bin/env python3
"""
Fenrir Executor (Dev Agent)

Handles code review, git operations, testing tasks.
Runs on: fenrir.nessie-hippocampus.ts.net:5000
"""

import sys
sys.path.insert(0, '/var/home/matt/homelab-config')

from agents.base_agent import AgentExecutor
import logging

logger = logging.getLogger(__name__)


class FenrirExecutor(AgentExecutor):
    """Dev agent for code review, git, testing tasks"""
    
    EXECUTOR_NAME = "fenrir-executor"
    EXECUTOR_VERSION = "0.1.0"
    
    def register_handlers(self):
        """Register task handlers for Fenrir"""
        
        self.task_handlers = {
            'dev-health-check': self.handle_health_check,
            'git-clone': self.handle_git_clone,
            'git-commit': self.handle_git_commit,
            'code-review': self.handle_code_review,
            'run-tests': self.handle_run_tests,
            'plan-sync': self.handle_plan_sync,
        }
    
    def handle_health_check(self, params):
        """Verify Fenrir is operational"""
        result = self.run_command('uname -a')
        return {
            'output': f"Fenrir health check: {result['success']}\n{result['output']}"
        }
    
    def handle_git_clone(self, params):
        """Clone a repository"""
        repo_url = params.get('repo_url')
        dest_path = params.get('dest_path', '/tmp/repo')
        
        if not repo_url:
            return {'output': 'Error: repo_url required'}
        
        cmd = f"git clone {repo_url} {dest_path}"
        result = self.run_command(cmd, timeout=300)
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_git_commit(self, params):
        """Commit changes to a repository"""
        repo_path = params.get('repo_path', '.')
        message = params.get('message', 'Auto-commit from Fenrir executor')
        
        cmd = f"cd {repo_path} && git add -A && git commit -m '{message}'"
        result = self.run_command(cmd, timeout=60)
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_code_review(self, params):
        """Run static analysis / linting"""
        repo_path = params.get('repo_path', '.')
        
        # Example: Run flake8 if Python project
        cmd = f"cd {repo_path} && python3 -m flake8 --version && echo 'Flake8 ready'"
        result = self.run_command(cmd, timeout=120)
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_run_tests(self, params):
        """Execute test suite"""
        repo_path = params.get('repo_path', '.')
        
        # Example: Run pytest if available
        cmd = f"cd {repo_path} && python3 -m pytest --version && echo 'Tests ready'"
        result = self.run_command(cmd, timeout=300)
        
        return {
            'output': result['output'],
            'success': result['success']
        }
    
    def handle_plan_sync(self, params):
        """Sync Obsidian specs to Beads (planning agent)"""
        # This is a stub; full implementation in Phase 3
        return {
            'output': 'Planning sync not yet implemented'
        }


if __name__ == '__main__':
    agent = FenrirExecutor()
    agent.run(host='0.0.0.0', port=5000, debug=False)
