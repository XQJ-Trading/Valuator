"""Background task runner - executes sessions independently"""

import asyncio
from datetime import datetime
from typing import Optional

from ...core.agent.react_agent import AIAgent
from ...core.utils.logger import logger
from .manager import SessionManager
from .models import SessionEvent, SessionStatus


class BackgroundTaskRunner:
    """Runs background tasks independently from API responses"""

    def __init__(self, session_manager: SessionManager):
        """
        Initialize BackgroundTaskRunner

        Args:
            session_manager: SessionManager instance for managing sessions
        """
        self.session_manager = session_manager
        logger.info("BackgroundTaskRunner initialized")

    async def solve_in_background(
        self, session_id: str, query: str, model: Optional[str] = None
    ) -> None:
        """
        Solve a query in the background and update session with events

        Runs independently and continues even if client disconnects

        Args:
            session_id: Session ID
            query: User query
            model: Model to use (optional)
        """
        logger.info(f"Starting background task for session: {session_id}")

        try:
            # Update session status to RUNNING
            await self.session_manager.update_session_status(
                session_id, SessionStatus.RUNNING
            )

            # Create agent
            agent = AIAgent(model_name=model)

            # Stream events from agent
            async for event_dict in agent.solve_stream(query):
                # Convert dict event to SessionEvent
                session_event = SessionEvent(
                    type=event_dict.get("type", ""),
                    content=event_dict.get("content", ""),
                    timestamp=datetime.now(),
                    tool=event_dict.get("tool"),
                    tool_input=event_dict.get("tool_input"),
                    tool_output=event_dict.get("tool_output"),
                    error=event_dict.get("error"),
                    metadata=event_dict.get("metadata"),
                )

                # Add event to session
                await self.session_manager.add_event(session_id, session_event)

                logger.debug(f"Session {session_id} event: {session_event.type}")

            # Mark as completed
            await self.session_manager.update_session_status(
                session_id, SessionStatus.COMPLETED
            )
            logger.info(f"Background task completed for session: {session_id}")

        except Exception as e:
            logger.error(f"Error in background task for session {session_id}: {e}")

            # Add error event
            error_event = SessionEvent(
                type="error",
                content="",
                timestamp=datetime.now(),
                error=str(e),
            )
            await self.session_manager.add_event(session_id, error_event)

            # Mark as failed
            await self.session_manager.update_session_status(
                session_id, SessionStatus.FAILED
            )
