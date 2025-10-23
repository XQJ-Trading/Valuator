"""Base repository interface for session storage"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class SessionRepository(ABC):
    """Abstract base class for session storage repositories"""

    @abstractmethod
    async def save_session(self, session: Dict[str, Any]) -> str:
        """
        Save a session to storage

        Args:
            session: Session data to save

        Returns:
            session_id: ID of the saved session
        """
        pass

    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific session by ID

        Args:
            session_id: ID of the session to retrieve

        Returns:
            Session data or None if not found
        """
        pass

    @abstractmethod
    async def list_sessions(
        self, limit: int = 10, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List sessions with pagination

        Args:
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip

        Returns:
            List of session data dictionaries
        """
        pass

    @abstractmethod
    async def search_sessions(self, query: str) -> List[Dict[str, Any]]:
        """
        Search sessions by query string

        Args:
            query: Search query string

        Returns:
            List of matching session data dictionaries
        """
        pass

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session

        Args:
            session_id: ID of the session to delete

        Returns:
            True if deleted, False if not found
        """
        pass
