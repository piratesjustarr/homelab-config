#!/usr/bin/env python3
"""
Beads ↔ BeeAI Adapter

Thin layer mapping Beads task queue to BeeAI agent execution.
Beads remains source of truth for task tracking; BeeAI handles orchestration.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from beeai_framework.agents.requirement import RequirementAgent
    from beeai_framework.backend import ChatModel
    from beeai_framework.errors import FrameworkError
    HAS_BEEAI = True
except ImportError:
    HAS_BEEAI = False

logger = logging.getLogger(__name__)


class BeadsTask:
    """Represents a task from Beads"""
    
    def __init__(self, data: Dict[str, Any]):
        self.id = data.get('id')
        self.title = data.get('title')
        self.description = data.get('description')
        self.status = data.get('status')
        self.labels = data.get('labels', [])
        self.priority = data.get('priority')
        self.issue_type = data.get('issue_type')
        self.dependencies = data.get('dependencies', [])
        
    def is_ready(self) -> bool:
        """Task is ready if status=open and no blocking dependencies"""
        return self.status == 'open' and not self.dependencies
    
    def infer_agent_type(self) -> Optional[str]:
        """Infer which agent should handle this task"""
        if 'code-generation' in self.labels or 'code-' in self.title.lower():
            return 'code-agent'
        if 'text-processing' in self.labels or 'text-' in self.title.lower():
            return 'text-agent'
        return None


class BeadsAdapter:
    """Adapts Beads task queue to BeeAI agent execution"""
    
    def __init__(self, beads_path: str = '/var/home/matt/homelab-config/yggdrasil-beads'):
        self.beads_path = Path(beads_path)
        self.issues_file = self.beads_path / '.beads' / 'issues.jsonl'
        
        # BeeAI agents (lazy-loaded)
        self.agents: Dict[str, RequirementAgent] = {}
        
        if not HAS_BEEAI:
            logger.warning("BeeAI framework not installed. Install with: pip install beeai-framework")
    
    async def init_agents(self):
        """Initialize BeeAI agents"""
        if not HAS_BEEAI:
            raise RuntimeError("BeeAI framework required")
        
        # Code generation agent
        self.agents['code-agent'] = RequirementAgent(
            name='CodeAgent',
            llm=ChatModel.from_name('ollama:granite-code:8b'),
            role='Code Generation Specialist',
            instructions='Generate clean, well-documented code based on specifications.',
        )
        
        # Text processing agent  
        self.agents['text-agent'] = RequirementAgent(
            name='TextAgent',
            llm=ChatModel.from_name('ollama:llama3.2:3b'),
            role='Text Processing Specialist',
            instructions='Process, analyze, and transform text based on requirements.',
        )
        
        logger.info("Initialized BeeAI agents")
    
    def load_tasks(self) -> List[BeadsTask]:
        """Load open tasks from Beads"""
        if not self.issues_file.exists():
            logger.error(f"Beads file not found: {self.issues_file}")
            return []
        
        tasks = []
        try:
            with open(self.issues_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        task = BeadsTask(data)
                        if task.is_ready():
                            tasks.append(task)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse task: {e}")
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
        
        return tasks
    
    async def execute_task(self, task: BeadsTask) -> Dict[str, Any]:
        """Execute a single task with appropriate agent"""
        agent_type = task.infer_agent_type()
        
        if not agent_type:
            logger.warning(f"Could not infer agent for task {task.id}")
            return {'status': 'error', 'error': 'No suitable agent found'}
        
        agent = self.agents.get(agent_type)
        if not agent:
            logger.warning(f"Agent {agent_type} not initialized")
            return {'status': 'error', 'error': f'Agent {agent_type} not available'}
        
        try:
            logger.info(f"Executing {task.id} with {agent_type}")
            
            # Run agent with task description as prompt
            result = await asyncio.wait_for(
                agent.run(task.description),
                timeout=300  # 5 minute timeout
            )
            
            output = result.last_message.text if hasattr(result, 'last_message') else str(result)
            
            return {
                'status': 'completed',
                'output': output,
                'agent': agent_type,
            }
        
        except asyncio.TimeoutError:
            logger.error(f"Task {task.id} timed out")
            return {'status': 'error', 'error': 'Task timeout'}
        
        except FrameworkError as e:
            logger.error(f"BeeAI error for {task.id}: {e}")
            return {'status': 'error', 'error': str(e)}
        
        except Exception as e:
            logger.error(f"Unexpected error for {task.id}: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def update_task(self, task_id: str, result: Dict[str, Any]):
        """Update task status in Beads"""
        status = 'closed' if result['status'] == 'completed' else 'blocked'
        
        try:
            # Read all tasks
            tasks = []
            with open(self.issues_file, 'r') as f:
                for line in f:
                    if line.strip():
                        task = json.loads(line)
                        
                        # Update target task
                        if task['id'] == task_id:
                            task['status'] = status
                            task['updated_at'] = datetime.now().isoformat() + 'Z'
                            if status == 'closed':
                                task['closed_at'] = datetime.now().isoformat() + 'Z'
                            
                            # Store result in task (truncated if needed)
                            if 'output' in result:
                                output = result['output']
                                if len(output) > 10000:
                                    output = output[:9997] + '...'
                                task['result'] = output
                        
                        tasks.append(task)
            
            # Write back
            with open(self.issues_file, 'w') as f:
                for task in tasks:
                    f.write(json.dumps(task) + '\n')
            
            logger.info(f"Updated {task_id} status to {status}")
        
        except Exception as e:
            logger.error(f"Failed to update task {task_id}: {e}")
    
    async def run_loop(self, poll_interval: int = 30, max_iterations: Optional[int] = None):
        """Main event loop - poll for ready tasks and execute"""
        await self.init_agents()
        
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            
            try:
                # Get ready tasks
                tasks = self.load_tasks()
                
                if not tasks:
                    logger.debug(f"Poll {iteration}: No ready tasks")
                    await asyncio.sleep(poll_interval)
                    continue
                
                # Execute first ready task
                task = tasks[0]
                logger.info(f"Poll {iteration}: Executing {task.id}")
                
                result = await self.execute_task(task)
                self.update_task(task.id, result)
                
                # Short sleep before next task
                await asyncio.sleep(5)
            
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
                await asyncio.sleep(poll_interval)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
    )
    
    adapter = BeadsAdapter()
    await adapter.run_loop(poll_interval=30)


if __name__ == '__main__':
    asyncio.run(main())
