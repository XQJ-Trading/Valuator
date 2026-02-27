"""Task rewrite LLM client - independent Gemini client"""

from typing import Optional

from valuator.models.gemini_direct import GeminiClient
from valuator.utils.config import config
from valuator.utils.logger import logger


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

        self._model_cache: dict[str, GeminiClient] = {}

    def _get_model(
        self, model_name: str, thinking_level: Optional[str] = None
    ) -> GeminiClient:
        """
        Get or create a model instance (with caching)

        Args:
            model_name: Name of the Gemini model
            thinking_level: Thinking level for Gemini 3.0 ('high', 'low', or None)

        Returns:
            GeminiClient instance
        """
        # Create cache key including thinking_level
        cache_key = f"{model_name}:{thinking_level or 'none'}"

        if cache_key not in self._model_cache:
            # thinking_level is accepted for API compatibility, but current client path is prompt-only.
            _ = thinking_level
            self._model_cache[cache_key] = GeminiClient(
                model=model_name,
                api_key=self.api_key,
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
            rewritten_task = await llm.generate(prompt=prompt, system_prompt="")

            logger.info(f"Task rewrite completed (model: {model})")
            return rewritten_task.strip()

        except Exception as e:
            logger.error(f"Failed to rewrite task with LLM: {e}")
            raise
