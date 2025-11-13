"""Task rewrite LLM client - independent Gemini client"""

from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI

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

        self._model_cache: dict[str, ChatGoogleGenerativeAI] = {}

    def _get_model(self, model_name: str) -> ChatGoogleGenerativeAI:
        """
        Get or create a model instance (with caching)

        Args:
            model_name: Name of the Gemini model

        Returns:
            ChatGoogleGenerativeAI instance
        """
        if model_name not in self._model_cache:
            self._model_cache[model_name] = ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=self.api_key,
                temperature=0.7,
                max_output_tokens=2048,
            )
            logger.debug(f"Created LLM client for model: {model_name}")

        return self._model_cache[model_name]

    async def rewrite_task(
        self,
        task: str,
        custom_prompt: Optional[str] = None,
        model: str = "gemini-flash-latest",
    ) -> str:
        """
        Rewrite a task using LLM

        Args:
            task: Original task text
            custom_prompt: Optional custom prompt
            model: Gemini model name

        Returns:
            Rewritten task text

        Raises:
            Exception: If LLM call fails
        """
        from ..task_rewrite.prompts import TaskRewritePrompts

        # Format the prompt
        prompt = TaskRewritePrompts.format_prompt(task, custom_prompt)

        # Get model instance
        llm = self._get_model(model)

        try:
            logger.info(f"Calling LLM for task rewrite (model: {model})")
            response = await llm.ainvoke(prompt)

            # Extract text from response
            if hasattr(response, "content"):
                rewritten_task = response.content
            else:
                rewritten_task = str(response)

            logger.info(f"Task rewrite completed (model: {model})")
            return rewritten_task.strip()

        except Exception as e:
            logger.error(f"Failed to rewrite task with LLM: {e}")
            raise

