#!/usr/bin/env python3
"""
Sync Obsidian tasks to Beads
"""

import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class BeadsSync:
    """Sync Obsidian tasks to Beads"""
    
    SYNC_FILE = '.beads/obsidian-sync.json'
    
    @staticmethod
    def _task_hash(task: Dict[str, Any]) -> str:
        """Generate unique hash for a task (file:line:description)"""
        key = f"{task['file']}:{task['line']}:{task['description']}"
        return hashlib.md5(key.encode()).hexdigest()[:8]
    
    @staticmethod
    def load_sync_state(beads_path: Path) -> Dict[str, str]:
        """
        Load mapping of obsidian tasks -> beads ids
        
        Format: {task_hash: bead_id}
        """
        sync_file = beads_path / BeadsSync.SYNC_FILE
        
        if not sync_file.exists():
            return {}
        
        try:
            with open(sync_file) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load sync state: {e}")
            return {}
    
    @staticmethod
    def save_sync_state(beads_path: Path, state: Dict[str, str]) -> None:
        """Save sync mapping to file"""
        sync_file = beads_path / BeadsSync.SYNC_FILE
        
        try:
            with open(sync_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save sync state: {e}")
    
    @staticmethod
    def map_priority(priority_tag: str) -> int:
        """Convert Obsidian priority tag to Beads priority (0=high, 3=low)"""
        mapping = {
            'p0': 0,
            'p1-critical': 0,
            'p1': 1,
            'p2-high': 1,
            'p2': 2,
            'p3-medium': 2,
            'p3': 3,
        }
        return mapping.get(priority_tag, 2)
    
    @staticmethod
    def map_type_to_labels(task_type: str) -> List[str]:
        """Convert task type to Beads labels"""
        labels = ['obsidian-import']  # Always tag as from Obsidian
        
        if task_type == 'code-generation':
            labels.append('code-generation')
        elif task_type == 'text-processing':
            labels.append('text-processing')
        elif task_type == 'code-review':
            labels.append('code-review')
        
        return labels
    
    @staticmethod
    def create_bead(task: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Beads issue from an Obsidian task"""
        now = datetime.now(timezone.utc).isoformat()
        
        return {
            'id': f"obsidian-{BeadsSync._task_hash(task)}",
            'title': task['description'],
            'description': f"{task['description']}\n\nSource: {task['file']}:{task['line']}",
            'status': 'open',
            'priority': BeadsSync.map_priority(task['priority']),
            'issue_type': 'task',
            'created_at': now,
            'labels': BeadsSync.map_type_to_labels(task['type']),
            'dependencies': [],
            'obsidian_source': {
                'file': task['file'],
                'line': task['line'],
                'tags': task['tags'],
            },
            'due_date': task.get('due_date'),
        }


def sync_obsidian_to_beads(tasks: List[Dict[str, Any]], beads_path: Path) -> int:
    """
    Sync Obsidian tasks to Beads
    
    Returns: number of new Beads created
    """
    beads_path = Path(beads_path)
    issues_file = beads_path / '.beads/issues.jsonl'
    
    if not issues_file.exists():
        logger.error(f"Beads issues file not found: {issues_file}")
        return 0
    
    # Load sync state
    sync_state = BeadsSync.load_sync_state(beads_path)
    
    # Load existing beads
    existing_ids = set()
    try:
        with open(issues_file) as f:
            for line in f:
                data = json.loads(line.strip())
                existing_ids.add(data['id'])
    except Exception as e:
        logger.warning(f"Failed to load existing beads: {e}")
    
    # Create new beads for unseen tasks
    new_beads = []
    for task in tasks:
        task_hash = BeadsSync._task_hash(task)
        
        # Check if already synced
        if task_hash in sync_state:
            continue
        
        bead = BeadsSync.create_bead(task)
        
        # Don't create duplicate IDs
        if bead['id'] in existing_ids:
            continue
        
        new_beads.append(bead)
        sync_state[task_hash] = bead['id']
    
    # Append new beads to file
    if new_beads:
        try:
            with open(issues_file, 'a') as f:
                for bead in new_beads:
                    f.write(json.dumps(bead) + '\n')
            
            # Save sync state
            BeadsSync.save_sync_state(beads_path, sync_state)
            
            logger.info(f"Created {len(new_beads)} new Beads from Obsidian")
            return len(new_beads)
        except Exception as e:
            logger.error(f"Failed to create beads: {e}")
            return 0
    
    return 0


def get_sync_state(beads_path: Path = None) -> Dict[str, Any]:
    """Get current sync state"""
    if not beads_path:
        beads_path = Path.home() / 'homelab-config/yggdrasil-beads'
    
    return BeadsSync.load_sync_state(beads_path)


def get_beads_stats(beads_path: Path = None) -> Dict[str, int]:
    """Get Beads statistics"""
    if not beads_path:
        # Try container mount first, then local
        for path in [Path('/beads'), Path.home() / 'homelab-config/yggdrasil-beads']:
            if (path / '.beads/issues.jsonl').exists():
                beads_path = path
                break
        else:
            beads_path = Path.home() / 'homelab-config/yggdrasil-beads'
    
    issues_file = beads_path / '.beads/issues.jsonl'
    
    stats = {'open': 0, 'in_progress': 0, 'closed': 0, 'blocked': 0}
    
    try:
        with open(issues_file) as f:
            for line in f:
                data = json.loads(line.strip())
                status = data.get('status', 'open')
                if status in stats:
                    stats[status] += 1
    except Exception as e:
        logger.warning(f"Failed to get stats: {e}")
    
    return stats


if __name__ == '__main__':
    import sys
    from obsidian_parser import parse_obsidian_tasks
    
    if len(sys.argv) < 3:
        print("Usage: beads_sync.py <vault_path> <beads_path>")
        sys.exit(1)
    
    vault = Path(sys.argv[1])
    beads = Path(sys.argv[2])
    
    tasks = parse_obsidian_tasks(vault)
    created = sync_obsidian_to_beads(tasks, beads)
    print(f"Synced: {created} new Beads created")
