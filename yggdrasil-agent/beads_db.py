#!/usr/bin/env python3
"""
Robust Beads client with SQLite transactions and distributed locking.

Improvements over JSONL file approach:
1. SQLite transactions - Atomic updates, no partial writes
2. Distributed locking - WAL mode for multi-instance safety
3. Query efficiency - SQL queries instead of linear file scan
4. No stale locks - Transaction-based, no lock files
5. Audit trail - Optional full history of all changes
"""

import sqlite3
import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class BeadsDatabase:
    """SQLite-based Beads task database with transactions"""
    
    SCHEMA_VERSION = 1
    
    def __init__(self, beads_dir: Optional[Path] = None, timeout: float = 30.0):
        """
        Initialize Beads database.
        
        Args:
            beads_dir: Path to Beads directory (defaults to standard locations)
            timeout: SQLite lock timeout in seconds
        """
        if beads_dir:
            self.beads_dir = Path(beads_dir)
        else:
            # Standard Beads locations
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
        
        self.db_path = self.beads_dir / '.beads/beads.sqlite'
        self.timeout = timeout
        
        # Create database directory if needed
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_db()
        
        logger.info(f"Initialized Beads database at {self.db_path}")
    
    def _init_db(self) -> None:
        """Initialize database schema"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Create tasks table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    priority INTEGER DEFAULT 2,
                    issue_type TEXT DEFAULT 'task',
                    labels TEXT,  -- JSON array as string
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    result TEXT,
                    attempt_count INTEGER DEFAULT 0,
                    last_error TEXT
                )
            ''')
            
            # Create index for common queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status 
                ON tasks(status)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_priority
                ON tasks(priority, created_at)
            ''')
            
            # Create audit log table (optional, tracks all changes)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    old_status TEXT,
                    new_status TEXT,
                    error_message TEXT
                )
            ''')
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """
        Get database connection with WAL mode for concurrency.
        
        WAL (Write-Ahead Logging) allows concurrent readers while writes
        happen without blocking, eliminating stale lock issues.
        """
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout)
        
        # Enable WAL mode for better concurrency
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.row_factory = sqlite3.Row
        
        try:
            yield conn
        finally:
            conn.close()
    
    def get_ready_tasks(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get open tasks sorted by priority.
        
        Args:
            limit: Maximum number of tasks to return
        
        Returns:
            List of task dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT * FROM tasks
                WHERE status = 'open'
                ORDER BY priority ASC, created_at ASC
            '''
            
            if limit:
                query += f' LIMIT {limit}'
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def update_task(
        self,
        task_id: str,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
        attempt: int = 0,
    ) -> bool:
        """
        Atomically update task status and result.
        
        Uses transactions to ensure consistency - either all updates
        succeed or none do (no partial writes).
        
        Args:
            task_id: Task ID
            status: New status (open, in_progress, closed, blocked)
            result: Result/output text (up to 32KB)
            error: Error message if failed
            attempt: Attempt count
        
        Returns:
            True if successful, False if task not found
        """
        now = datetime.now(timezone.utc).isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # Start transaction
                cursor.execute('BEGIN IMMEDIATE')
                
                # Check task exists
                cursor.execute('SELECT status FROM tasks WHERE id = ?', (task_id,))
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    logger.warning(f"Task {task_id} not found")
                    return False
                
                old_status = row[0]
                
                # Update task
                update_fields = [
                    'status = ?',
                    'updated_at = ?',
                ]
                update_values = [status, now]
                
                if result is not None:
                    update_fields.append('result = ?')
                    update_values.append(result[:32000])  # 32KB limit
                
                if error is not None:
                    update_fields.append('last_error = ?')
                    update_values.append(error[:1000])  # 1KB limit for error
                
                if status == 'closed':
                    update_fields.append('closed_at = ?')
                    update_values.append(now)
                
                if attempt > 0:
                    update_fields.append('attempt_count = ?')
                    update_values.append(attempt)
                
                update_values.append(task_id)
                
                query = f"UPDATE tasks SET {', '.join(update_fields)} WHERE id = ?"
                cursor.execute(query, update_values)
                
                # Log audit entry
                cursor.execute('''
                    INSERT INTO audit_log 
                    (task_id, timestamp, operation, old_status, new_status, error_message)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (task_id, now, 'status_update', old_status, status, error))
                
                # Commit transaction
                conn.commit()
                
                logger.info(f"Updated task {task_id}: {old_status} → {status}")
                return True
            
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(f"Failed to update task {task_id}: {e}")
                return False
    
    def create_task(self, task_data: Dict[str, Any]) -> bool:
        """
        Create a new task (atomic).
        
        Args:
            task_data: Task dictionary
        
        Returns:
            True if successful
        """
        now = datetime.now(timezone.utc).isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO tasks
                    (id, title, description, status, priority, issue_type, labels, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task_data.get('id'),
                    task_data.get('title'),
                    task_data.get('description'),
                    task_data.get('status', 'open'),
                    task_data.get('priority', 2),
                    task_data.get('issue_type', 'task'),
                    json.dumps(task_data.get('labels', [])),
                    task_data.get('created_at', now),
                    now,
                ))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"Task {task_data.get('id')} already exists")
                return False
            except sqlite3.Error as e:
                logger.error(f"Failed to create task: {e}")
                return False
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get single task by ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
    
    def get_stats(self) -> Dict[str, int]:
        """Get task statistics"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT status, COUNT(*) as count
                FROM tasks
                GROUP BY status
            ''')
            
            stats = {'open': 0, 'in_progress': 0, 'closed': 0, 'blocked': 0}
            for row in cursor.fetchall():
                status = row[0]
                if status in stats:
                    stats[status] = row[1]
            
            return stats
    
    def export_to_jsonl(self, output_path: Optional[Path] = None) -> Path:
        """
        Export all tasks to JSONL for Beads compatibility.
        
        Args:
            output_path: Where to write JSONL (defaults to .beads/issues.jsonl)
        
        Returns:
            Path to exported file
        """
        if output_path is None:
            output_path = self.beads_dir / '.beads/issues.jsonl'
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM tasks')
            
            # Write atomically with temp file
            temp_path = output_path.with_suffix('.jsonl.tmp')
            try:
                with open(temp_path, 'w') as f:
                    for row in cursor.fetchall():
                        task = self._row_to_dict(row)
                        f.write(json.dumps(task) + '\n')
                
                # Atomic rename
                temp_path.replace(output_path)
                logger.info(f"Exported {cursor.rowcount} tasks to {output_path}")
                return output_path
            except Exception as e:
                if temp_path.exists():
                    temp_path.unlink()
                logger.error(f"Failed to export tasks: {e}")
                raise
    
    def import_from_jsonl(self, input_path: Path) -> int:
        """
        Import tasks from JSONL file.
        
        Args:
            input_path: Path to JSONL file
        
        Returns:
            Number of tasks imported
        """
        imported = 0
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute('BEGIN IMMEDIATE')
                
                with open(input_path) as f:
                    for line in f:
                        if not line.strip():
                            continue
                        
                        try:
                            task = json.loads(line)
                            self.create_task(task)
                            imported += 1
                        except json.JSONDecodeError:
                            logger.warning(f"Skipped invalid JSON line")
                            continue
                
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to import tasks: {e}")
        
        return imported
    
    def get_audit_log(self, task_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get audit log entries.
        
        Args:
            task_id: Filter by task ID (if None, get all)
            limit: Maximum entries to return
        
        Returns:
            List of audit log entries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if task_id:
                cursor.execute('''
                    SELECT * FROM audit_log
                    WHERE task_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (task_id, limit))
            else:
                cursor.execute('''
                    SELECT * FROM audit_log
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (limit,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert SQLite row to dictionary"""
        d = dict(row)
        
        # Parse JSON fields
        if d.get('labels'):
            try:
                d['labels'] = json.loads(d['labels'])
            except json.JSONDecodeError:
                d['labels'] = []
        
        return d
    
    def close(self) -> None:
        """Close database connections"""
        pass  # Connections are context-managed


def migrate_jsonl_to_sqlite(beads_dir: Optional[Path] = None) -> int:
    """
    Migrate existing JSONL Beads to SQLite database.
    
    Args:
        beads_dir: Path to Beads directory
    
    Returns:
        Number of tasks migrated
    """
    beads = BeadsDatabase(beads_dir)
    
    jsonl_path = beads.beads_dir / '.beads/issues.jsonl'
    if jsonl_path.exists():
        imported = beads.import_from_jsonl(jsonl_path)
        logger.info(f"Migrated {imported} tasks from JSONL to SQLite")
        
        # Backup original JSONL
        backup_path = jsonl_path.with_suffix('.jsonl.backup')
        jsonl_path.rename(backup_path)
        logger.info(f"Backed up original JSONL to {backup_path}")
        
        return imported
    
    return 0
