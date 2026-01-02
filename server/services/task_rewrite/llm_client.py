"""Task rewrite LLM client - independent Gemini client"""

from typing import Optional

from ...core.models.gemini_direct import GeminiDirectModel
from ...core.utils.config import config
from ...core.utils.logger import logger


class TaskRewriteLLMClient:
    """Independent LLM client for task rewriting (separate from core)"""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize LLM client

        Args:
            api_key: Google API key (defaults to config.google_api_key)
        """
        self.api_key = api_key or config.google_api_key
        if not self.api_key:
            raise ValueError(
                "Google API key is required. Set GOOGLE_API_KEY in environment or pass api_key parameter."
            )

        self._model_cache: dict[str, GeminiDirectModel] = {}

    def _get_model(
        self, model_name: str, thinking_level: Optional[str] = None
    ) -> GeminiDirectModel:
        """
        Get or create a model instance (with caching)

        Args:
            model_name: Name of the Gemini model
            thinking_level: Thinking level for Gemini 3.0 ('high', 'low', or None)

        Returns:
            GeminiDirectModel instance
        """
        # Create cache key including thinking_level
        cache_key = f"{model_name}:{thinking_level or 'none'}"

        if cache_key not in self._model_cache:
            # Always use direct API
            self._model_cache[cache_key] = GeminiDirectModel(
                model=model_name,
                google_api_key=self.api_key,
                temperature=0.7,
                max_output_tokens=2048,
                thinking_level=thinking_level,
                streaming=False,
            )
            logger.debug(
                f"Created Direct API LLM client for model: {model_name}, thinking_level: {thinking_level}"
            )

        return self._model_cache[cache_key]

    async def rewrite_task(
        self,
        task: str,
        custom_prompt: Optional[str] = None,
        model: str = config.agent_model,
        thinking_level: Optional[str] = None,
    ) -> str:
        """
        Rewrite a task using LLM

        Args:
            task: Original task text
            custom_prompt: Optional custom prompt
            model: Gemini model name
            thinking_level: Thinking level for Gemini 3.0 ('high', 'low', or None)

        Returns:
            Rewritten task text

        Raises:
            Exception: If LLM call fails
        """
        if not task or not task.strip():
            raise ValueError("Task cannot be empty")

        from .prompts import TaskRewritePrompts

        prompt = TaskRewritePrompts.format_prompt(task, custom_prompt)
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        llm = self._get_model(model, thinking_level)

        try:
            logger.info(f"Calling LLM for task rewrite (model: {model})")
            from langchain_core.messages import HumanMessage

            messages = [HumanMessage(content=prompt)]
            if (
                not messages
                or not messages[0].content
                or not messages[0].content.strip()
            ):
                raise ValueError("Message content cannot be empty")

            response = await llm.ainvoke(messages)
            rewritten_task = response.content if hasattr(response, "content") else str(response)

            logger.info(f"Task rewrite completed (model: {model})")
            return rewritten_task.strip()

        except Exception as e:
            logger.error(f"Failed to rewrite task with LLM: {e}")
            raise
