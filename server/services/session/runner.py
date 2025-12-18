"""Background task runner - executes sessions independently"""

import asyncio
from datetime import datetime
from typing import Optional, Any

from ...core.agent.react_agent import AIAgent
from ...core.utils.logger import logger
from .manager import SessionManager
from .models import SessionStatus
from ...repositories import SessionRepository


class BackgroundTaskRunner:
    """Runs background tasks independently from API responses"""

    def __init__(
        self,
        session_manager: SessionManager,
        history_repository: Optional[SessionRepository] = None,
    ):
        """
        Initialize BackgroundTaskRunner

        Args:
            session_manager: SessionManager instance for managing sessions
            history_repository: Optional repository for persisting sessions
        """
        self.session_manager = session_manager
        self.history_repository = history_repository
        logger.info("BackgroundTaskRunner initialized")

    async def solve_in_background(
        self,
        session_id: str,
        query: str,
        model: Optional[str] = None,
        thinking_level: Optional[str] = None,
    ) -> None:
        """
        Solve a query in the background and update session with events

        Runs independently and continues even if client disconnects

        Args:
            session_id: Session ID
            query: User query
            model: Model to use (optional)
            thinking_level: Thinking level for Gemini 3.0 ('high', 'low', or None)
        """
        logger.info(f"Starting background task for session: {session_id}")

        try:
            # Update session status to RUNNING
            await self.session_manager.update_session_status(
                session_id, SessionStatus.RUNNING
            )

            # Create agent
            agent = AIAgent(model_name=model, thinking_level=thinking_level)

            # Stream events from agent and publish as dict
            async for event_dict in agent.solve_stream(query):
                # Publish event dict directly to session
                await self.session_manager.add_event(session_id, event_dict)

                logger.debug(f"Session {session_id} event: {event_dict.get('type')}")

            # Send end event to notify client
            end_event_dict = {
                "type": "end",
                "content": "",
                "timestamp": datetime.now().isoformat(),
            }
            await self.session_manager.add_event(session_id, end_event_dict)

            # Mark as completed
            await self.session_manager.update_session_status(
                session_id, SessionStatus.COMPLETED
            )

            # Delay cleanup so clients can still subscribe to finished sessions
            self.session_manager.schedule_cleanup(session_id, delay_seconds=60)

        except Exception as e:
            logger.error(f"Error in background task for session {session_id}: {e}")

            # Add error event as dict
            error_event_dict = {
                "type": "error",
                "content": "",
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
            }
            await self.session_manager.add_event(session_id, error_event_dict)

            # Mark as failed
            await self.session_manager.update_session_status(
                session_id, SessionStatus.FAILED
            )

            # Save failed session to history repository
            session = await self.session_manager.get_session(session_id)
            if session and self.history_repository:
                try:
                    await self.history_repository.save_session(session.to_dict())
                    logger.info(f"Saved failed session to history: {session_id}")
                except Exception as e:
                    logger.error(f"Failed to save failed session to history: {e}")
