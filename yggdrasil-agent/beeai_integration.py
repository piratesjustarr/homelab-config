#!/usr/bin/env python3
"""
BeeAI agent integration for Yggdrasil.

Provides structured agent capabilities with BeeAI framework:
- CodeGenerationAgent: For code generation and refactoring
- TextProcessingAgent: For text extraction, summarization, rewriting
- ReasoningAgent: For complex analysis and planning

Falls back to simple LLM if BeeAI unavailable or Python version insufficient.
"""

import logging
import sys
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all agents"""
    
    def __init__(self, llm, cloud_llm=None):
        self.llm = llm
        self.cloud_llm = cloud_llm
    
    @abstractmethod
    async def process(self, prompt: str) -> str:
        """Process a prompt and return result"""
        pass


class CodeGenerationAgent(BaseAgent):
    """Generate or refactor code using BeeAI or fallback"""
    
    async def process(self, prompt: str) -> str:
        """Generate code"""
        try:
            # Try BeeAI if available
            from beeai_framework.agents import Agent
            
            # BeeAI code generation with tools
            result = await self._beeai_process(prompt)
            return result
        except (ImportError, AttributeError):
            # Fallback to simple LLM
            return self._simple_process(prompt)
    
    async def _beeai_process(self, prompt: str) -> str:
        """BeeAI-based code generation"""
        try:
            # This would use BeeAI's code generation capabilities
            # For now, return a placeholder
            logger.info("BeeAI code generation not fully integrated")
            return self._simple_process(prompt)
        except Exception as e:
            logger.warning(f"BeeAI code generation failed: {e}")
            return self._simple_process(prompt)
    
    def _simple_process(self, prompt: str) -> str:
        """Fallback to simple LLM"""
        # This will be called by the LLMClient
        return prompt


class TextProcessingAgent(BaseAgent):
    """Process text (summarize, extract, rewrite) using BeeAI or fallback"""
    
    async def process(self, prompt: str) -> str:
        """Process text"""
        try:
            from beeai_framework.agents import Agent
            result = await self._beeai_process(prompt)
            return result
        except (ImportError, AttributeError):
            return self._simple_process(prompt)
    
    async def _beeai_process(self, prompt: str) -> str:
        """BeeAI-based text processing"""
        try:
            logger.info("BeeAI text processing not fully integrated")
            return self._simple_process(prompt)
        except Exception as e:
            logger.warning(f"BeeAI text processing failed: {e}")
            return self._simple_process(prompt)
    
    def _simple_process(self, prompt: str) -> str:
        """Fallback to simple LLM"""
        return prompt


class ReasoningAgent(BaseAgent):
    """Perform reasoning and analysis using BeeAI or fallback"""
    
    async def process(self, prompt: str) -> str:
        """Process reasoning task"""
        try:
            from beeai_framework.agents import Agent
            result = await self._beeai_process(prompt)
            return result
        except (ImportError, AttributeError):
            return self._simple_process(prompt)
    
    async def _beeai_process(self, prompt: str) -> str:
        """BeeAI-based reasoning"""
        try:
            logger.info("BeeAI reasoning not fully integrated")
            return self._simple_process(prompt)
        except Exception as e:
            logger.warning(f"BeeAI reasoning failed: {e}")
            return self._simple_process(prompt)
    
    def _simple_process(self, prompt: str) -> str:
        """Fallback to simple LLM"""
        return prompt


class BeeAIManager:
    """Manage BeeAI agent initialization and configuration"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize BeeAI manager.
        
        Args:
            config: BeeAI configuration dict with 'enabled', 'python_version', etc.
        """
        self.config = config or {}
        self.enabled = self.config.get('enabled', False)
        self.fallback_to_simple = self.config.get('fallback_to_simple_llm', True)
        self.required_python = self.config.get('python_version', '3.12')
        
        self.agents = {}
        self._check_prerequisites()
    
    def _check_prerequisites(self) -> None:
        """Check if BeeAI can be used"""
        if not self.enabled:
            logger.info("BeeAI integration disabled in config")
            return
        
        # Check Python version
        current_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        if current_version < self.required_python:
            msg = f"BeeAI requires Python {self.required_python}+, found {current_version}"
            if self.fallback_to_simple:
                logger.warning(f"{msg} (will fallback to simple LLM)")
                self.enabled = False
            else:
                raise RuntimeError(msg)
        
        # Check if beeai-framework is installed
        try:
            import beeai_framework
            logger.info("BeeAI framework available")
        except ImportError:
            msg = "beeai-framework not installed"
            if self.fallback_to_simple:
                logger.warning(f"{msg} (will fallback to simple LLM)")
                self.enabled = False
            else:
                raise RuntimeError(msg)
    
    def initialize_agents(
        self,
        llm_router,
        cloud_llm=None,
    ) -> Dict[str, BaseAgent]:
        """
        Initialize BeeAI agents for different task types.
        
        Args:
            llm_router: LLMRouter instance for host selection
            cloud_llm: Cloud LLM for fallback
        
        Returns:
            Dictionary mapping agent names to agent instances
        """
        if not self.enabled:
            logger.info("BeeAI disabled, using simple LLM fallback")
            return {}
        
        try:
            # Create agents with LLM instances
            # In a real BeeAI integration, this would configure the agents
            # with appropriate models and tools
            
            self.agents['code'] = CodeGenerationAgent(
                llm=None,  # Would be BeeAI LLM instance
                cloud_llm=cloud_llm,
            )
            self.agents['text'] = TextProcessingAgent(
                llm=None,
                cloud_llm=cloud_llm,
            )
            self.agents['reasoning'] = ReasoningAgent(
                llm=None,
                cloud_llm=cloud_llm,
            )
            
            logger.info(f"BeeAI agents initialized: {list(self.agents.keys())}")
            return self.agents
        
        except Exception as e:
            logger.error(f"Failed to initialize BeeAI agents: {e}")
            if self.fallback_to_simple:
                logger.warning("Falling back to simple LLM")
                self.enabled = False
                return {}
            else:
                raise
    
    def get_agent(self, agent_type: str) -> Optional[BaseAgent]:
        """Get specific agent"""
        return self.agents.get(agent_type)
    
    def is_available(self) -> bool:
        """Check if BeeAI is available"""
        return self.enabled and bool(self.agents)


def initialize_beeai(
    config: Dict[str, Any] = None,
    llm_router=None,
    cloud_llm=None,
) -> BeeAIManager:
    """
    Initialize BeeAI with configuration.
    
    Args:
        config: BeeAI configuration dict
        llm_router: LLMRouter instance
        cloud_llm: Cloud LLM fallback
    
    Returns:
        BeeAIManager instance
    """
    manager = BeeAIManager(config)
    if llm_router:
        manager.initialize_agents(llm_router, cloud_llm)
    return manager
