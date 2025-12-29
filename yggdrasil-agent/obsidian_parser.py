#!/usr/bin/env python3
"""
Parse Obsidian markdown files for tasks tagged with #agent
"""

import re
from pathlib import Path
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class ObsidianTaskParser:
    """Parse Obsidian markdown for tasks"""
    
    # Regex patterns
    TASK_PATTERN = re.compile(
        r'- \[ \] (.+?)(?:\n|$)',  # Unchecked checkbox
        re.MULTILINE
    )
    
    TAG_PATTERN = re.compile(r'#([a-z\-]+)')  # Tags like #agent, #code
    PRIORITY_PATTERN = re.compile(r'#(p[0-9]|p[0-9]-[a-z]+)')  # Priority tags
    DATE_PATTERN = re.compile(r'📅 (\d{4}-\d{2}-\d{2})')  # Due date
    
    @staticmethod
    def parse_task_line(line: str) -> Dict[str, Any]:
        """Parse a single task checkbox line"""
        # Extract description (before any tags)
        match = re.match(r'- \[ \] (.+?)(?:\s+#|$)', line)
        if not match:
            return None
        
        description = match.group(1).strip()
        
        # Extract tags
        tags = ObsidianTaskParser.TAG_PATTERN.findall(line)
        
        # Extract priority
        priority_match = ObsidianTaskParser.PRIORITY_PATTERN.search(line)
        priority = priority_match.group(1) if priority_match else 'p2'
        
        # Extract due date
        date_match = ObsidianTaskParser.DATE_PATTERN.search(line)
        due_date = date_match.group(1) if date_match else None
        
        return {
            'description': description,
            'tags': tags,
            'priority': priority,
            'due_date': due_date,
            'raw_line': line.strip(),
        }
    
    @staticmethod
    def parse_file(filepath: Path) -> List[Dict[str, Any]]:
        """Parse all #agent tasks from a markdown file"""
        tasks = []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read {filepath}: {e}")
            return []
        
        # Find all task lines
        lines = content.split('\n')
        for line_num, line in enumerate(lines):
            if '- [ ]' not in line:
                continue
            
            task = ObsidianTaskParser.parse_task_line(line)
            if not task:
                continue
            
            # Only include if marked with #agent
            if 'agent' not in task['tags']:
                continue
            
            # Determine task type from tags
            task_type = 'general'
            if 'code' in task['tags']:
                task_type = 'code-generation'
            elif 'text' in task['tags']:
                task_type = 'text-processing'
            elif 'review' in task['tags']:
                task_type = 'code-review'
            
            task['type'] = task_type
            task['file'] = str(filepath)
            task['line'] = line_num + 1
            
            tasks.append(task)
        
        return tasks


def parse_obsidian_tasks(vault_path: Path) -> List[Dict[str, Any]]:
    """
    Scan Obsidian vault for all #agent tasks
    
    Returns list of task dicts with:
    - description: task text
    - tags: list of tags
    - type: inferred from tags (code-generation, text-processing, etc)
    - priority: priority tag
    - due_date: optional due date
    - file: source file path
    - line: line number in file
    """
    vault_path = Path(vault_path)
    all_tasks = []
    
    # Scan all markdown files
    for md_file in vault_path.rglob('*.md'):
        # Skip templates
        if 'Templates' in str(md_file):
            continue
        
        tasks = ObsidianTaskParser.parse_file(md_file)
        all_tasks.extend(tasks)
    
    logger.info(f"Parsed {len(all_tasks)} #agent tasks from {vault_path}")
    return all_tasks


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: obsidian_parser.py <vault_path>")
        sys.exit(1)
    
    vault = Path(sys.argv[1])
    tasks = parse_obsidian_tasks(vault)
    
    for task in tasks:
        print(f"[{task['type'].upper()}] {task['description']}")
        print(f"  Tags: {', '.join(task['tags'])}")
        print(f"  Priority: {task['priority']}")
        if task['due_date']:
            print(f"  Due: {task['due_date']}")
        print()
