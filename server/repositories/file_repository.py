"""File-based session repository implementation"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.utils.logger import logger
from .base import SessionRepository


class FileSessionRepository(SessionRepository):
    """File-based implementation of SessionRepository"""

    def __init__(self, logs_dir: str = "logs/react_sessions"):
        """
        Initialize file-based repository

        Args:
            logs_dir: Directory to store session JSON files
        """
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized FileSessionRepository at {self.logs_dir}")

    async def save_session(self, session: Dict[str, Any]) -> str:
        """
        Save a session to a JSON file

        Args:
            session: Session data to save

        Returns:
            session_id: ID of the saved session
        """
        session_id = session.get("session_id")
        if not session_id:
            raise ValueError("Session must have a 'session_id' field")

        filename = f"{session_id}.json"
        filepath = self.logs_dir / filename

        # Run file I/O in thread pool to avoid blocking
        await asyncio.to_thread(self._write_json_file, filepath, session)

        logger.info(f"Saved session to file: {filepath}")
        return session_id

    def _write_json_file(self, filepath: Path, data: Dict[str, Any]):
        """Write JSON data to file (sync)"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific session by ID

        Args:
            session_id: ID of the session to retrieve

        Returns:
            Session data or None if not found
        """
        filename = f"{session_id}.json"
        filepath = self.logs_dir / filename

        if not filepath.exists():
            logger.warning(f"Session not found: {session_id}")
            return None

        try:
            # Run file I/O in thread pool
            session = await asyncio.to_thread(self._read_json_file, filepath)
            logger.debug(f"Loaded session: {session_id}")
            return session
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def _read_json_file(self, filepath: Path) -> Dict[str, Any]:
        """Read JSON data from file (sync)"""
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    async def list_sessions(
        self, limit: int = 10, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List sessions with pagination, sorted by modification time (newest first)

        Args:
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip

        Returns:
            List of session data dictionaries
        """
        try:
            # Get all JSON files
            files = await asyncio.to_thread(lambda: list(self.logs_dir.glob("*.json")))

            # Sort by modification time (newest first)
            files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

            # Apply pagination
            paginated_files = files[offset : offset + limit]

            # Load session data
            sessions = []
            for filepath in paginated_files:
                try:
                    session = await asyncio.to_thread(self._read_json_file, filepath)
                    sessions.append(session)
                except Exception as e:
                    logger.error(f"Failed to load session from {filepath}: {e}")
                    continue

            logger.debug(
                f"Listed {len(sessions)} sessions (limit={limit}, offset={offset})"
            )
            return sessions

        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            return []

    async def search_sessions(self, query: str) -> List[Dict[str, Any]]:
        """
        Search sessions by query string (searches in query and final_answer fields)

        Args:
            query: Search query string

        Returns:
            List of matching session data dictionaries
        """
        try:
            # Get all sessions
            all_sessions = await self.list_sessions(limit=1000)  # Reasonable limit

            # Filter by query
            query_lower = query.lower()
            matching_sessions = []

            for session in all_sessions:
                # Search in query field
                session_query = session.get("query", "").lower()
                if query_lower in session_query:
                    matching_sessions.append(session)
                    continue

                # Search in final_answer field
                final_answer = session.get("final_answer", "").lower()
                if query_lower in final_answer:
                    matching_sessions.append(session)
                    continue

                # Search in steps content
                steps = session.get("steps", [])
                for step in steps:
                    step_content = step.get("content", "").lower()
                    if query_lower in step_content:
                        matching_sessions.append(session)
                        break

            logger.debug(
                f"Found {len(matching_sessions)} sessions matching query: {query}"
            )
            return matching_sessions

        except Exception as e:
            logger.error(f"Failed to search sessions: {e}")
            return []

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session file

        Args:
            session_id: ID of the session to delete

        Returns:
            True if deleted, False if not found
        """
        filename = f"{session_id}.json"
        filepath = self.logs_dir / filename

        if not filepath.exists():
            logger.warning(f"Session not found for deletion: {session_id}")
            return False

        try:
            await asyncio.to_thread(filepath.unlink)
            logger.info(f"Deleted session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    async def get_total_count(self) -> int:
        """Get total number of sessions"""
        try:
            files = await asyncio.to_thread(lambda: list(self.logs_dir.glob("*.json")))
            return len(files)
        except Exception as e:
            logger.error(f"Failed to count sessions: {e}")
            return 0
