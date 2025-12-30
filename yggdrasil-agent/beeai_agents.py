"""BeeAI agents for structured task processing using direct ChatModel calls."""

import logging
from typing import Optional

from beeai_framework.backend import ChatModel, UserMessage, SystemMessage

logger = logging.getLogger(__name__)


def extract_text(result) -> str:
    """Extract text content from BeeAI ChatModelOutput."""
    if not result.output or len(result.output) == 0:
        return "No output generated"
    
    msg = result.output[0]
    # content is a list of MessageTextContent objects
    if hasattr(msg.content, '__iter__') and not isinstance(msg.content, str):
        texts = []
        for item in msg.content:
            if hasattr(item, 'text'):
                texts.append(item.text)
        return ''.join(texts)
    return str(msg.content)


class CodeGenerationAgent:
    """Agent for code generation tasks using BeeAI ChatModel."""
    
    def __init__(self, local_llm: ChatModel, fallback_llm: Optional[ChatModel] = None):
        self.local_llm = local_llm
        self.fallback_llm = fallback_llm
        
    async def process(self, task_description: str, context: dict = None) -> str:
        """Process a code generation task."""
        system_prompt = """You are a skilled software engineer. Your task is to:
1. Understand the requirements clearly
2. Generate clean, well-structured code
3. Include necessary imports and documentation
4. Follow best practices for the language
5. Explain your implementation

Provide complete, working code."""

        messages = [
            SystemMessage(content=system_prompt),
            UserMessage(content=task_description)
        ]
        
        try:
            result = await self.local_llm.run(messages)
            return extract_text(result)
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            if self.fallback_llm:
                logger.info("Retrying with fallback LLM")
                result = await self.fallback_llm.run(messages)
                return extract_text(result)
            raise


class TextProcessingAgent:
    """Agent for text processing tasks using BeeAI ChatModel."""
    
    def __init__(self, local_llm: ChatModel, fallback_llm: Optional[ChatModel] = None):
        self.local_llm = local_llm
        self.fallback_llm = fallback_llm
        
    async def process(self, task_description: str, context: dict = None) -> str:
        """Process a text processing task."""
        system_prompt = """You are an expert at text analysis and processing. Your task is to:
1. Analyze the input thoroughly
2. Provide clear and structured output
3. Be comprehensive in your analysis
4. Explain your reasoning

Provide detailed and accurate analysis."""

        messages = [
            SystemMessage(content=system_prompt),
            UserMessage(content=task_description)
        ]
        
        try:
            result = await self.local_llm.run(messages)
            return extract_text(result)
        except Exception as e:
            logger.error(f"Text processing failed: {e}")
            if self.fallback_llm:
                logger.info("Retrying with fallback LLM")
                result = await self.fallback_llm.run(messages)
                return extract_text(result)
            raise


class ReasoningAgent:
    """Agent for complex reasoning and planning tasks using BeeAI ChatModel."""
    
    def __init__(self, local_llm: ChatModel, fallback_llm: Optional[ChatModel] = None):
        self.local_llm = local_llm
        self.fallback_llm = fallback_llm
        
    async def process(self, task_description: str, context: dict = None) -> str:
        """Process a reasoning task."""
        system_prompt = """You are an expert reasoning system. Your task is to:
1. Break down complex problems systematically
2. Think through each step carefully
3. Provide clear reasoning and explanations
4. Offer actionable recommendations
5. Consider edge cases and implications

Provide thorough analysis and clear conclusions."""

        messages = [
            SystemMessage(content=system_prompt),
            UserMessage(content=task_description)
        ]
        
        try:
            result = await self.local_llm.run(messages)
            return extract_text(result)
        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            if self.fallback_llm:
                logger.info("Retrying with fallback LLM")
                result = await self.fallback_llm.run(messages)
                return extract_text(result)
            raise
