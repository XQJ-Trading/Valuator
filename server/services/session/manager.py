"""Session manager - handles session lifecycle and state management"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, Dict, List, Optional

from ...core.utils.logger import logger
from .models import SessionData, SessionEvent, SessionStatus


class SessionManager:
    """Manages session lifecycle and streaming"""

    def __init__(self, history_repository: Optional[Any] = None):
        """
        Initialize SessionManager

        Args:
            history_repository: Optional repository for persisting sessions
        """
        self.sessions: Dict[str, SessionData] = {}
        self.history_repository = history_repository
        # Mapping of session_id to list of async queues for subscribers
        self.subscribers: Dict[str, List[asyncio.Queue]] = {}
        logger.info("SessionManager initialized")

    # ========================================================================
    # Session Creation & Lifecycle
    # ========================================================================

    async def create_session(self, query: str, model: str) -> SessionData:
        """
        Create a new session

        Args:
            query: User query
            model: Model to use

        Returns:
            Created session
        """
        timestamp = datetime.now()
        session_id = timestamp.strftime("chat_%Y%m%d_%H%M%S")

        session = SessionData(
            session_id=session_id,
            query=query,
            model=model,
            status=SessionStatus.CREATED,
            created_at=timestamp,
            events=[],
            subscriber_count=0,
        )

        self.sessions[session_id] = session
        self.subscribers[session_id] = []

        logger.info(f"Created session: {session_id}")
        return session

    async def get_session(self, session_id: str) -> Optional[SessionData]:
        """
        Get active session from memory

        Args:
            session_id: Session ID

        Returns:
            Session data or None if not found
        """
        return self.sessions.get(session_id)

    async def list_sessions(
        self, limit: int = 20, offset: int = 0
    ) -> List[SessionData]:
        """
        List active sessions

        Args:
            limit: Maximum number
            offset: Offset

        Returns:
            List of sessions
        """
        sessions_list = list(self.sessions.values())
        # Sort by created_at descending
        sessions_list.sort(key=lambda s: s.created_at, reverse=True)
        return sessions_list[offset : offset + limit]

    async def cleanup_session(self, session_id: str) -> bool:
        """
        End and cleanup a session, save to history

        Args:
            session_id: Session ID

        Returns:
            Success status
        """
        session = self.sessions.get(session_id)
        if session is None:
            return False

        # Update status
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.now()

        # Save to history if repository available
        if self.history_repository is not None:
            try:
                await self.history_repository.save_session(session.to_dict())
                logger.info(f"Saved session to history: {session_id}")
            except Exception as e:
                logger.error(f"Failed to save session to history: {e}")

        # Remove from active sessions
        del self.sessions[session_id]

        # Clean up subscribers
        if session_id in self.subscribers:
            del self.subscribers[session_id]

        logger.info(f"Cleaned up session: {session_id}")
        return True

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """
        Clean up old completed sessions

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of cleaned sessions
        """
        now = datetime.now()
        cutoff = now - timedelta(hours=max_age_hours)

        sessions_to_cleanup = [
            session_id
            for session_id, session in self.sessions.items()
            if session.status == SessionStatus.COMPLETED
            and session.completed_at is not None
            and session.completed_at < cutoff
        ]

        count = 0
        for session_id in sessions_to_cleanup:
            if await self.cleanup_session(session_id):
                count += 1

        logger.info(f"Cleaned up {count} old sessions")
        return count

    # ========================================================================
    # Event Management
    # ========================================================================

    async def add_event(self, session_id: str, event: SessionEvent) -> bool:
        """
        Add event to session

        Args:
            session_id: Session ID
            event: Event to add

        Returns:
            Success status
        """
        session = self.sessions.get(session_id)
        if session is None:
            logger.warning(f"Session not found: {session_id}")
            return False

        session.events.append(event)

        # Broadcast to all subscribers
        if session_id in self.subscribers:
            for queue in self.subscribers[session_id]:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"Subscriber queue full for session: {session_id}")

        return True

    # ========================================================================
    # Status Management
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
        session = self.sessions.get(session_id)
        if session is None:
            return False

        session.status = status

        if status == SessionStatus.COMPLETED or status == SessionStatus.FAILED:
            session.completed_at = datetime.now()

        logger.info(f"Updated session {session_id} status to {status.value}")
        return True

    # ========================================================================
    # Event Streaming & Subscriptions
    # ========================================================================

    async def subscribe_to_session(
        self, session_id: str
    ) -> AsyncGenerator[SessionEvent, None]:
        """
        Subscribe to session events as a stream

        Yields all existing events first, then new events as they arrive

        Args:
            session_id: Session ID to subscribe to

        Yields:
            Session events
        """
        session = self.sessions.get(session_id)
        if session is None:
            logger.warning(f"Session not found for subscription: {session_id}")
            return

        # Create a queue for this subscriber
        subscriber_queue: asyncio.Queue[SessionEvent] = asyncio.Queue()
        self.subscribers[session_id].append(subscriber_queue)
        session.subscriber_count = len(self.subscribers[session_id])

        logger.info(
            f"New subscriber for session {session_id}, total: {session.subscriber_count}"
        )

        try:
            # First, yield all existing events
            for event in session.events:
                yield event

            # Then, wait for new events
            while True:
                event = await subscriber_queue.get()

                # Check if session is still active
                if session_id not in self.sessions:
                    logger.info(f"Session ended during subscription: {session_id}")
                    break

                yield event

        except asyncio.CancelledError:
            logger.info(f"Subscription cancelled for session {session_id}")
        except Exception as e:
            logger.error(f"Error in subscription for session {session_id}: {e}")
        finally:
            # Cleanup subscriber
            if session_id in self.subscribers:
                if subscriber_queue in self.subscribers[session_id]:
                    self.subscribers[session_id].remove(subscriber_queue)

                session = self.sessions.get(session_id)
                if session:
                    session.subscriber_count = len(self.subscribers[session_id])

                logger.info(
                    f"Removed subscriber for session {session_id}, remaining: {session.subscriber_count if session else 0}"
                )

    # ========================================================================
    # Utility Methods
    # ========================================================================

    async def get_session_subscriber_count(self, session_id: str) -> int:
        """
        Get number of active subscribers for a session

        Args:
            session_id: Session ID

        Returns:
            Subscriber count
        """
        session = self.sessions.get(session_id)
        if session:
            return session.subscriber_count
        return 0

    def get_active_session_count(self) -> int:
        """
        Get count of active sessions

        Returns:
            Count of sessions
        """
        return len(self.sessions)
