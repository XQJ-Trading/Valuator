"""Session service layer - manages session lifecycle and streaming"""

import asyncio
from typing import Any, AsyncGenerator, Dict, Optional

from ...core.utils.config import config
from ...core.utils.logger import logger
from .manager import SessionManager
from .models import SessionData, SessionEvent, SessionStatus
from .runner import BackgroundTaskRunner


class SessionService:
    """
    High-level service for session management

    Integrates SessionManager and BackgroundTaskRunner to provide
    a clean interface for session operations
    """

    def __init__(self, history_repository: Optional[Any] = None):
        """
        Initialize SessionService

        Args:
            history_repository: Optional repository for persisting sessions
        """
        self.session_manager = SessionManager(history_repository=history_repository)
        self.history_repository = history_repository
        self.background_runner = BackgroundTaskRunner(
            self.session_manager, history_repository=history_repository
        )
        logger.info("SessionService initialized")

    # ========================================================================
    # Session Creation & Lifecycle
    # ========================================================================

    async def start_session(
        self,
        query: str,
        model: Optional[str] = None,
        thinking_level: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> SessionData:
        """
        Create and start a new session with background task

        Args:
            query: User query
            model: Model to use
            thinking_level: Thinking level for Gemini 3.0 ('high', 'low', or None)
            context: Optional runtime context payload

        Returns:
            Created session
        """
        # Create session
        session = await self.session_manager.create_session(
            query=query, model=model or config.agent_model, context=context
        )

        # Start background task
        asyncio.create_task(
            self.background_runner.solve_in_background(
                session.session_id, query, model, thinking_level, context
            )
        )

        logger.info(f"Started session: {session.session_id}")
        return session

    async def get_session(self, session_id: str) -> Optional[SessionData]:
        """
        Get session from memory or history

        Tries to get from active sessions first, then falls back to history

        Args:
            session_id: Session ID

        Returns:
            Session data or None if not found
        """
        # 1. Try active sessions first
        session = await self.session_manager.get_session(session_id)
        if session is not None:
            return session

        return None

    async def list_sessions(
        self, limit: int = 20, offset: int = 0
    ) -> list[SessionData]:
        """
        List active sessions

        Args:
            limit: Maximum number
            offset: Offset

        Returns:
            List of sessions
        """
        return await self.session_manager.list_sessions(limit=limit, offset=offset)

    async def end_session(self, session_id: str) -> bool:
        """
        End and cleanup a session

        Args:
            session_id: Session ID

        Returns:
            Success status
        """
        return await self.session_manager.cleanup_session(session_id)

    # ========================================================================
    # Event Streaming
    # ========================================================================

    async def subscribe_to_session(self, session_id: str) -> AsyncGenerator[Any, None]:
        """
        Subscribe to session events as a stream

        Args:
            session_id: Session ID to subscribe to

        Yields:
            Session events as dictionaries (JSON-serializable)
        """
        async for event in self.session_manager.subscribe_to_session(session_id):
            yield event

    # ========================================================================
    # Session Status Management
    # ========================================================================

    async def update_session_status(
        self, session_id: str, status: SessionStatus
    ) -> bool:
        """
        Update session status

        Args:
            session_id: Session ID
            status: New status

        Returns:
            Success status
        """
        return await self.session_manager.update_session_status(session_id, status)

    async def add_event(self, session_id: str, event: SessionEvent) -> bool:
        """
        Add event to session

        Args:
            session_id: Session ID
            event: Event to add

        Returns:
            Success status
        """
        return await self.session_manager.add_event(session_id, event)

    # ========================================================================
    # Utility Methods
    # ========================================================================

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """
        Clean up old completed sessions

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of cleaned sessions
        """
        return await self.session_manager.cleanup_old_sessions(
            max_age_hours=max_age_hours
        )

    async def get_session_subscriber_count(self, session_id: str) -> int:
        """
        Get number of active subscribers for a session

        Args:
            session_id: Session ID

        Returns:
            Subscriber count
        """
        session = await self.session_manager.get_session(session_id)
        if session:
            return session.subscriber_count
        return 0
