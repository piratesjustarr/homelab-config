"""
Artifact handler for BeeAI output - automatically saves generated code and files.

Handles:
1. TaskArtifactUpdateEvent from BeeAI agents
2. Extracting 'Output path:' from task descriptions
3. Auto-saving to project directories
4. Integration with Beads task tracking
"""

import re
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ArtifactHandler:
    """Handle artifact events and save outputs to disk"""
    
    def __init__(self):
        self.output_path_cache = {}
    
    def extract_output_path(self, task: Dict[str, Any]) -> Optional[Path]:
        """Extract output path from task description"""
        task_id = task.get('id')
        
        # Check cache first
        if task_id in self.output_path_cache:
            return self.output_path_cache[task_id]
        
        description = task.get('description', '')
        
        # Look for "Output path: /path/to/file" pattern
        match = re.search(r'Output path:\s*([^\n]+)', description)
        if match:
            path_str = match.group(1).strip()
            path = Path(path_str).expanduser().resolve()
            self.output_path_cache[task_id] = path
            logger.info(f"[{task_id}] Found output path: {path}")
            return path
        
        return None
    
    async def handle_agent_output(
        self, 
        task: Dict[str, Any], 
        output: str,
        artifact_type: str = 'code'
    ) -> Optional[Path]:
        """
        Handle agent output and save to disk if output path specified.
        
        Supports:
        - Python code (.py)
        - JavaScript (.js)
        - JSON config (.json)
        - Markdown docs (.md)
        - General text
        """
        task_id = task.get('id')
        output_path = self.extract_output_path(task)
        
        if not output_path:
            logger.debug(f"[{task_id}] No output path specified, result stored in Beads only")
            return None
        
        # Ensure parent directories exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Detect file type from output path extension or artifact type
            extension = output_path.suffix.lower()
            
            # Extract code block if it's Python/JS and contains code fences
            if extension in ['.py', '.js'] and '```' in output:
                code_match = re.search(rf'```(?:python|javascript|js)?\n(.*?)\n```', output, re.DOTALL)
                if code_match:
                    content = code_match.group(1)
                    logger.info(f"[{task_id}] Extracted code block from output")
                else:
                    content = output
            else:
                content = output
            
            # Write file
            output_path.write_text(content)
            logger.info(f"[{task_id}] Saved artifact to {output_path} ({len(content)} bytes)")
            return output_path
            
        except Exception as e:
            logger.error(f"[{task_id}] Failed to save artifact: {e}")
            return None
    
    def get_suggested_path(self, task: Dict[str, Any], default_ext: str = '.py') -> Path:
        """Get a suggested output path if none specified"""
        task_id = task.get('id')
        title = task.get('title', 'output')
        
        # Create filename from task ID or title
        filename = task_id.replace('-', '_') + default_ext
        default_dir = Path.home() / 'yggdrasil-outputs'
        default_dir.mkdir(parents=True, exist_ok=True)
        
        return default_dir / filename
