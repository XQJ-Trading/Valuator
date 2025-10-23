"""MongoDB-based session repository implementation"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from pymongo import DESCENDING, MongoClient
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False

from ..core.utils.logger import logger
from .base import SessionRepository


class MongoSessionRepository(SessionRepository):
    """MongoDB-based implementation of SessionRepository"""

    def __init__(
        self,
        mongodb_uri: str,
        database: str = "ai_agent",
        collection: str = "react_sessions",
    ):
        """
        Initialize MongoDB-based repository

        Args:
            mongodb_uri: MongoDB connection URI
            database: Database name
            collection: Collection name
        """
        if not MONGODB_AVAILABLE:
            raise ImportError(
                "pymongo is not installed. Install it with: pip install pymongo"
            )

        self.mongodb_uri = mongodb_uri
        self.database_name = database
        self.collection_name = collection

        # Initialize connection
        self.client = None
        self.db = None
        self.collection = None
        self._init_connection()

    def _init_connection(self):
        """Initialize MongoDB connection"""
        try:
            self.client = MongoClient(
                self.mongodb_uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=5000,
            )

            # Test connection
            self.client.admin.command("ping")

            self.db = self.client[self.database_name]
            self.collection = self.db[self.collection_name]

            # Create indexes for better query performance
            self.collection.create_index([("session_id", 1)], unique=True)
            self.collection.create_index([("timestamp", DESCENDING)])
            self.collection.create_index([("created_at", DESCENDING)])

            logger.info(
                f"MongoDB connection established: {self.database_name}.{self.collection_name}"
            )

        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error initializing MongoDB: {e}")
            raise

    async def save_session(self, session: Dict[str, Any]) -> str:
        """
        Save a session to MongoDB

        Args:
            session: Session data to save

        Returns:
            session_id: ID of the saved session
        """
        session_id = session.get("session_id")
        if not session_id:
            raise ValueError("Session must have a 'session_id' field")

        # Add MongoDB-specific fields
        mongodb_doc = session.copy()
        mongodb_doc["created_at"] = datetime.now()
        mongodb_doc["source"] = "react_logger"

        try:
            # Run MongoDB operation in thread pool
            await asyncio.to_thread(
                self.collection.replace_one,
                {"session_id": session_id},
                mongodb_doc,
                upsert=True,
            )

            logger.info(f"Saved session to MongoDB: {session_id}")
            return session_id

        except Exception as e:
            logger.error(f"Failed to save session to MongoDB: {e}")
            raise

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific session by ID

        Args:
            session_id: ID of the session to retrieve

        Returns:
            Session data or None if not found
        """
        try:
            # Run MongoDB operation in thread pool
            doc = await asyncio.to_thread(
                self.collection.find_one, {"session_id": session_id}
            )

            if doc:
                # Remove MongoDB's _id field
                doc.pop("_id", None)
                logger.debug(f"Loaded session from MongoDB: {session_id}")
                return doc
            else:
                logger.warning(f"Session not found in MongoDB: {session_id}")
                return None

        except Exception as e:
            logger.error(f"Failed to load session {session_id} from MongoDB: {e}")
            return None

    async def list_sessions(
        self, limit: int = 10, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List sessions with pagination, sorted by creation time (newest first)

        Args:
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip

        Returns:
            List of session data dictionaries
        """
        try:
            # Run MongoDB operation in thread pool
            cursor = await asyncio.to_thread(
                lambda: self.collection.find()
                .sort("created_at", DESCENDING)
                .skip(offset)
                .limit(limit)
            )

            # Convert cursor to list
            docs = await asyncio.to_thread(list, cursor)

            # Remove MongoDB's _id field from each document
            sessions = []
            for doc in docs:
                doc.pop("_id", None)
                sessions.append(doc)

            logger.debug(
                f"Listed {len(sessions)} sessions from MongoDB (limit={limit}, offset={offset})"
            )
            return sessions

        except Exception as e:
            logger.error(f"Failed to list sessions from MongoDB: {e}")
            return []

    async def search_sessions(self, query: str) -> List[Dict[str, Any]]:
        """
        Search sessions by query string using MongoDB text search

        Args:
            query: Search query string

        Returns:
            List of matching session data dictionaries
        """
        try:
            # Use regex for flexible searching
            regex_query = {"$regex": query, "$options": "i"}

            # Search in multiple fields
            search_filter = {
                "$or": [
                    {"query": regex_query},
                    {"final_answer": regex_query},
                    {"steps.content": regex_query},
                ]
            }

            # Run MongoDB operation in thread pool
            cursor = await asyncio.to_thread(
                lambda: self.collection.find(search_filter).sort(
                    "created_at", DESCENDING
                )
            )

            # Convert cursor to list
            docs = await asyncio.to_thread(list, cursor)

            # Remove MongoDB's _id field from each document
            sessions = []
            for doc in docs:
                doc.pop("_id", None)
                sessions.append(doc)

            logger.debug(
                f"Found {len(sessions)} sessions in MongoDB matching query: {query}"
            )
            return sessions

        except Exception as e:
            logger.error(f"Failed to search sessions in MongoDB: {e}")
            return []

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session from MongoDB

        Args:
            session_id: ID of the session to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            # Run MongoDB operation in thread pool
            result = await asyncio.to_thread(
                self.collection.delete_one, {"session_id": session_id}
            )

            if result.deleted_count > 0:
                logger.info(f"Deleted session from MongoDB: {session_id}")
                return True
            else:
                logger.warning(
                    f"Session not found for deletion in MongoDB: {session_id}"
                )
                return False

        except Exception as e:
            logger.error(f"Failed to delete session {session_id} from MongoDB: {e}")
            return False

    async def get_total_count(self) -> int:
        """Get total number of sessions"""
        try:
            count = await asyncio.to_thread(self.collection.count_documents, {})
            return count
        except Exception as e:
            logger.error(f"Failed to count sessions in MongoDB: {e}")
            return 0

    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")
