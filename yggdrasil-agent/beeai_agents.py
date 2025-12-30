"""BeeAI agents for structured task processing with tools and reasoning."""

import logging
import asyncio
from typing import Optional
from pathlib import Path

from beeai_framework.backend import ChatModel
from beeai_framework.agents.requirement import RequirementAgent

logger = logging.getLogger(__name__)


class CodeGenerationAgent:
    """Agent for code generation tasks using BeeAI RequirementAgent."""
    
    def __init__(self, local_llm: ChatModel, fallback_llm: Optional[ChatModel] = None):
        self.local_llm = local_llm
        self.fallback_llm = fallback_llm
        
    async def process(self, task_description: str, context: dict = None) -> str:
        """Process a code generation task."""
        context = context or {}
        
        requirements = [
            "Generate clean, well-structured code",
            "Include necessary imports and documentation",
            "Follow best practices for the language",
            "Explain the implementation"
        ]
        
        agent = RequirementAgent(
            llm=self.local_llm,
            requirements=requirements
        )
        
        try:
            result = await agent.run(task_description)
            return result.output
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            if self.fallback_llm:
                logger.info("Retrying with fallback LLM")
                agent.llm = self.fallback_llm
                result = await agent.run(task_description)
                return result.output
            raise


class TextProcessingAgent:
    """Agent for text processing tasks using BeeAI RequirementAgent."""
    
    def __init__(self, local_llm: ChatModel, fallback_llm: Optional[ChatModel] = None):
        self.local_llm = local_llm
        self.fallback_llm = fallback_llm
        
    async def process(self, task_description: str, context: dict = None) -> str:
        """Process a text processing task."""
        context = context or {}
        
        requirements = [
            "Analyze the input thoroughly",
            "Provide clear and structured output",
            "Be comprehensive in your analysis",
            "Explain your reasoning"
        ]
        
        agent = RequirementAgent(
            llm=self.local_llm,
            requirements=requirements
        )
        
        try:
            result = await agent.run(task_description)
            return result.output
        except Exception as e:
            logger.error(f"Text processing failed: {e}")
            if self.fallback_llm:
                logger.info("Retrying with fallback LLM")
                agent.llm = self.fallback_llm
                result = await agent.run(task_description)
                return result.output
            raise


class ReasoningAgent:
    """Agent for complex reasoning and planning tasks using BeeAI RequirementAgent."""
    
    def __init__(self, local_llm: ChatModel, fallback_llm: Optional[ChatModel] = None):
        self.local_llm = local_llm
        self.fallback_llm = fallback_llm
        
    async def process(self, task_description: str, context: dict = None) -> str:
        """Process a reasoning task."""
        context = context or {}
        
        requirements = [
            "Break down complex problems systematically",
            "Think through each step carefully",
            "Provide clear reasoning and explanations",
            "Offer actionable recommendations",
            "Consider edge cases and implications"
        ]
        
        agent = RequirementAgent(
            llm=self.local_llm,
            requirements=requirements
        )
        
        try:
            result = await agent.run(task_description)
            return result.output
        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            if self.fallback_llm:
                logger.info("Retrying with fallback LLM")
                agent.llm = self.fallback_llm
                result = await agent.run(task_description)
                return result.output
            raise
