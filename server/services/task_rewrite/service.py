"""Task rewrite service"""

import uuid
from typing import Optional

from ...core.utils.logger import logger
from .llm_client import TaskRewriteLLMClient
from .models import TaskRewriteHistory
from ...repositories.task_rewrite_repository import TaskRewriteRepository


class TaskRewriteService:
    """Service for task rewriting functionality"""

    def __init__(
        self,
        repository: TaskRewriteRepository,
        llm_client: Optional[TaskRewriteLLMClient] = None,
    ):
        """
        Initialize TaskRewriteService

        Args:
            repository: TaskRewriteRepository instance
            llm_client: Optional TaskRewriteLLMClient (creates default if not provided)
        """
        self.repository = repository
        self.llm_client = llm_client or TaskRewriteLLMClient()
        logger.info("TaskRewriteService initialized")

    async def rewrite_task(
        self,
        task: str,
        model: str = "gemini-flash-latest",
        custom_prompt: Optional[str] = None,
        thinking_level: Optional[str] = None,
    ) -> TaskRewriteHistory:
        """
        Rewrite a task and save to history

        Args:
            task: Original task text
            model: Gemini model name
            custom_prompt: Optional custom prompt
            thinking_level: Thinking level for Gemini 3.0 ('high', 'low', or None)

        Returns:
            TaskRewriteHistory instance

        Raises:
            Exception: If rewrite fails
        """
        try:
            logger.info(f"Starting task rewrite (model: {model})")

            # Call LLM to rewrite the task
            rewritten_task = await self.llm_client.rewrite_task(
                task=task,
                custom_prompt=custom_prompt,
                model=model,
                thinking_level=thinking_level,
            )

            # Create history record
            rewrite_id = str(uuid.uuid4())
            history = TaskRewriteHistory(
                rewrite_id=rewrite_id,
                original_task=task,
                rewritten_task=rewritten_task,
                model=model,
                custom_prompt=custom_prompt,
                metadata={},
            )

            # Save to repository
            await self.repository.save_rewrite(history)

            logger.info(f"Task rewrite completed: {rewrite_id}")
            return history

        except Exception as e:
            logger.error(f"Failed to rewrite task: {e}")
            raise

    async def get_rewrite(self, rewrite_id: str) -> Optional[TaskRewriteHistory]:
        """
        Get a rewrite by ID

        Args:
            rewrite_id: Rewrite ID

        Returns:
            TaskRewriteHistory or None if not found
        """
        return await self.repository.get_rewrite(rewrite_id)

    async def list_rewrites(
        self, limit: int = 10, offset: int = 0
    ) -> list[TaskRewriteHistory]:
        """
        List rewrites with pagination

        Args:
            limit: Maximum number of rewrites
            offset: Number of rewrites to skip

        Returns:
            List of TaskRewriteHistory instances
        """
        return await self.repository.list_rewrites(limit=limit, offset=offset)

    async def delete_rewrite(self, rewrite_id: str) -> bool:
        """
        Delete a rewrite

        Args:
            rewrite_id: Rewrite ID

        Returns:
            True if deleted, False if not found
        """
        return await self.repository.delete_rewrite(rewrite_id)
