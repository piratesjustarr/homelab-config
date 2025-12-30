#!/usr/bin/env python3
"""
Auto-apply mechanism for generated code changes.

This module provides functionality to automatically detect, validate, and commit
generated code changes to a git repository with proper testing and validation.
"""

import os
import sys
import subprocess
import json
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import logging
from dataclasses import dataclass
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class TaskInfo:
    """Information about a Beads task."""
    task_id: str
    title: str
    description: str = ""
    status: str = "pending"

class CodeChangeHandler(FileSystemEventHandler):
    """File system event handler for detecting code changes."""
    
    def __init__(self, auto_applier: 'AutoApplier'):
        self.auto_applier = auto_applier
        self._last_processed = {}
        
    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return
            
        file_path = Path(event.src_path)
        if self._should_process_file(file_path):
            # Debounce rapid file changes
            current_time = time.time()
            last_time = self._last_processed.get(str(file_path), 0)
            
            if current_time - last_time > 2:  # 2 second debounce
                self._last_processed[str(file_path)] = current_time
                logger.info(f"Detected change in {file_path}")
                self.auto_applier.process_file_change(file_path)
    
    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return
            
        file_path = Path(event.src_path)
        if self._should_process_file(file_path):
            logger.info(f"Detected new file {file_path}")
            self.auto_applier.process_file_change(file_path, is_new_file=True)
    
    def _should_process_file(self, file_path: Path) -> bool:
        """Check if file should be processed."""
        # Only process Python files for now
        if not file_path.suffix == '.py':
            return False
            
        # Skip temporary files, __pycache__, etc.
        if any(part.startswith('.') or part == '__pycache__' for part in file_path.parts):
            return False
            
        # Skip files in virtual environments
        if 'venv' in str(file_path) or '.env' in str(file_path):
            return False
            
        return True

class AutoApplier:
    """Main class for auto-applying generated code changes."""
    
    def __init__(self, project_root: str, beads_config_path: Optional[str] = None):
        self.project_root = Path(project_root).resolve()
        self.beads_config_path = beads_config_path
        self._git_repo_root = self._find_git_root()
        
        if not self._git_repo_root:
            raise ValueError(f"No git repository found in {self.project_root}")
            
        logger.info(f"Initialized AutoApplier for {self.project_root}")
        logger.info(f"Git repository root: {self._git_repo_root}")
    
    def _find_git_root(self) -> Optional[Path]:
        """Find the root of the git repository."""
        current = self.project_root
        while current != current.parent:
            if (current / '.git').exists():
                return current
            current = current.parent
        return None
    
    def _run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
        """Run a command and return (returncode, stdout, stderr)."""
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or self.project_root,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {' '.join(cmd)}")
            return 1, "", "Command timed out"
        except Exception as e:
            logger.error(f"Error running command {' '.join(cmd)}: {e}")
            return 1, "", str(e)
    
    def _is_git_tracked(self, file_path: Path) -> bool:
        """Check if file is tracked by git."""
        rel_path = file_path.relative_to(self._git_repo_root)
        returncode, _, _ = self._run_command(
            ['git', 'ls-files', '--error-unmatch', str(rel_path)],
            cwd=self._git_repo_root
        )
        return returncode == 0
    
    def _has_uncommitted_changes(self, file_path: Path) -> bool:
        """Check if file has uncommitted changes."""
        rel_path = file_path.relative_to(self._git_repo_root)
        returncode, stdout, _ = self._run_command(
            ['git', 'status', '--porcelain', str(rel_path)],
            cwd=self._git_repo_root
        )
        return returncode == 0 and stdout.strip() != ""
    
    def _run_python_tests(self, file_path: Path) -> bool:
        """Run Python tests for the given file."""
        logger.info(f"Running tests for {file_path}")
        
        # Try pytest first
        if self._has_pytest():
            return self._run_pytest(file_path)
        
        # Fall back to basic syntax check
        return self._check_python_syntax(file_path)
    
    def _has_pytest(self) -> bool:
        """Check if pytest is available."""
        returncode, _, _ = self._run_command(['python', '-m', 'pytest', '--version'])
        return returncode == 0
    
    def _run_pytest(self, file_path: Path) -> bool:
        """Run pytest for the file or related tests."""
        # Look for corresponding test file
        test_patterns = [
            file_path.parent / f"test_{file_path.name}",
            file_path.parent / "tests" / f"test_{file_path.name}",
            self.project_root / "tests" / f"test_{file_path.name}",
        ]
        
        test_files = [t for t in test_patterns if t.exists()]
        
        if test_files:
            # Run specific test files
            cmd = ['python', '-m', 'pytest'] + [str(t) for t in test_files]
        else:
            # Run all tests in the project
            cmd = ['python', '-m', 'pytest', str(self.project_root)]
        
        returncode, stdout, stderr = self._run_command(cmd)
        
        if returncode == 0:
            logger.info("Tests passed")
            return True
        else:
            logger.warning(f"Tests failed: {stderr}")
            return False
    
    def _check_python_syntax(self, file_path: Path) -> bool:
        """Check Python syntax of the file."""
        logger.info(f"Checking syntax for {file_path}")
        
        returncode, stdout, stderr = self._run_command([
            'python', '-m', 'py_compile', str(file_path)
        ])
        
        if returncode == 0:
            logger.info("Syntax check passed")
            return True
        else:
            logger.warning(f"Syntax check failed: {stderr}")
            return False
    
    def _run_linting(self, file_path: Path) -> bool:
        """Run linting checks on the file."""
        # Try flake8 if available
        returncode, _, _ = self._run_command(['python', '-m', 'flake8', '--version'])
        if returncode == 0:
            returncode, stdout, stderr = self._run_command([
                'python', '-m', 'flake8', '--max-line-length=88', str(file_path)
            ])
            if returncode != 0:
                logger.warning(f"Linting warnings: {stdout}{stderr}")
                # Don't fail on linting warnings, just log them
        
        return True
    
    def _extract_task_info(self, file_path: Path) -> Optional[TaskInfo]:
        """Extract task information from file comments or beads config."""
        # Try to read task info from file comments
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Look for task info in comments
            lines = content.split('\n')
            task_id = None
            title = None
            
            for line in lines[:20]:  # Check first 20 lines
                line = line.strip()
                if line.startswith('#') or line.startswith('"""') or line.startswith("'''"):
                    if 'task_id:' in line.lower():
                        task_id = line.split('task_id:', 1)[1].strip().strip('"\'')
                    elif 'title:' in line.lower():
                        title = line.split('title:', 1)[1].strip().strip('"\'')
            
            if task_id and title:
                return TaskInfo(task_id=task_id, title=title)
                
        except Exception as e:
            logger.debug(f"Could not extract task info from {file_path}: {e}")
        
        # Fall back to generic info
        return TaskInfo(
            task_id=hashlib.md5(str(file_path).encode()).hexdigest()[:8],
            title=f"Code changes in {file_path.name}"
        )
    
    def _create_commit(self, file_path: Path, task_info: TaskInfo, is_new_file: bool = False) -> bool:
        """Create a git commit for the changes."""
        try:
            # Add the file to git
            rel_path = file_path.relative_to(self._git_repo_root)
            returncode, _, stderr = self._run_command([
                'git', 'add', str(rel_path)
            ], cwd=self._git_repo_root)
            
            if returncode != 0:
                logger.error(f"Failed to add file to git: {stderr}")
                return False
            
            # Create commit message
            if is_new_file:
                commit_msg = f"Add new file: {task_info.task_id} - {task_info.title}"
            else:
                commit_msg = f"Apply generated code improvement: {task_info.task_id} - {task_info.title}"
            
            # Commit the changes
            returncode, _, stderr = self._run_command([
                'git', 'commit', '-m', commit_msg
            ], cwd=self._git_repo_root)
            
            if returncode != 0:
                logger.error(f"Failed to create commit: {stderr}")
                return False
            
            logger.info(f"Created commit: {commit_msg}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating commit: {e}")
            return False
    
    def _update_beads_task_status(self, task_info: TaskInfo, status: str) -> None:
        """Update the task status in Beads configuration."""
        if not self.beads_config_path:
            logger.debug("No Beads config path provided, skipping status update")
            return
            
        try:
            config_path = Path(self.beads_config_path)
            if not config_path.exists():
                logger.debug(f"Beads config file not found: {config_path}")
                return
            
            # This is a placeholder - actual implementation would depend on
            # the Beads configuration format
            logger.info(f"Would update task {task_info.task_id} status to {status}")
            
        except Exception as e:
            logger.warning(f"Failed to update Beads task status: {e}")
    
    def process_file_change(self, file_path: Path, is_new_file: bool = False) -> None:
        """Process a detected file change."""
        try:
            logger.info(f"Processing {'new' if is_new_file else 'modified'} file: {file_path}")
            
            # Skip if file doesn't exist (might have been deleted)
            if not file_path.exists():
                logger.debug(f"File no longer exists: {file_path}")
                return
            
            # For existing files, check if there are actually uncommitted changes
            if not is_new_file and self._is_git_tracked(file_path):
                if not self._has_uncommitted_changes(file_path):
                    logger.debug(f"No uncommitted changes in {file_path}")
                    return
            
            # Extract task information
            task_info = self._extract_task_info(file_path)
            if not task_info:
                logger.warning(f"Could not extract task info from {file_path}")
                return
            
            # Run validation
            validation_passed = True
            
            # Check Python syntax and run tests
            if file_path.suffix == '.py':
                if not self._check_python_syntax(file_path):
                    validation_passed = False
                elif not self._run_python_tests(file_path):
                    validation_passed = False
                else:
                    self._run_linting(file_path)  # Non-blocking
            
            if not validation_passed:
                logger.warning(f"Validation failed for {file_path}, skipping commit")
                self._update_beads_task_status(task_info, "validation_failed")
                return
            
            # Create git commit
            if self._create_commit(file_path, task_info, is_new_file):
                logger.info(f"Successfully applied changes for {file_path}")
                self._update_beads_task_status(task_info, "deployed")
            else:
                logger.error(f"Failed to commit changes for {file_path}")
                self._update_beads_task_status(task_info, "commit_failed")
                
        except Exception as e:
            logger.error(f"Error processing file change {file_path}: {e}")
    
    def start_watching(self, recursive: bool = True) -> None:
        """Start watching for file changes."""
        event_handler = CodeChangeHandler(self)
        observer = Observer()
        observer.schedule(event_handler, str(self.project_root), recursive=recursive)
        
        logger.info(f"Starting file watcher on {self.project_root}")
        observer.start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping file watcher...")
            observer.stop()
        observer.join()
    
    def process_single_file(self, file_path: Union[str, Path]) -> None:
        """Process a single file immediately."""
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"File does not exist: {file_path}")
            return
        
        is_new_file = not self._is_git_tracked(file_path)
        self.process_file_change(file_path, is_new_file)


def main():
    """Main entry point for the auto-apply script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Auto-apply generated code changes")
    parser.add_argument(
        "project_root",
        help="Root directory of the project to monitor"
    )
    parser.add_argument(
        "--beads-config",
        help="Path to Beads