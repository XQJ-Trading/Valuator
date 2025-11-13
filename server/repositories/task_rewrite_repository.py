"""Task rewrite repository implementations"""

import asyncio
import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

try:
    from pymongo import DESCENDING, MongoClient
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False

from ..core.utils.logger import logger

if TYPE_CHECKING:
    from ..services.task_rewrite.models import TaskRewriteHistory


class TaskRewriteRepository(ABC):
    """Abstract base class for task rewrite storage repositories"""

    @abstractmethod
    async def save_rewrite(self, history: "TaskRewriteHistory") -> str:
        """
        Save a task rewrite history to storage

        Args:
            history: TaskRewriteHistory instance to save

        Returns:
            rewrite_id: ID of the saved rewrite
        """
        pass

    @abstractmethod
    async def get_rewrite(self, rewrite_id: str) -> Optional["TaskRewriteHistory"]:
        """
        Retrieve a specific rewrite by ID

        Args:
            rewrite_id: ID of the rewrite to retrieve

        Returns:
            TaskRewriteHistory or None if not found
        """
        pass

    @abstractmethod
    async def list_rewrites(
        self, limit: int = 10, offset: int = 0
    ) -> List["TaskRewriteHistory"]:
        """
        List rewrites with pagination

        Args:
            limit: Maximum number of rewrites to return
            offset: Number of rewrites to skip

        Returns:
            List of TaskRewriteHistory instances
        """
        pass

    @abstractmethod
    async def delete_rewrite(self, rewrite_id: str) -> bool:
        """
        Delete a rewrite

        Args:
            rewrite_id: ID of the rewrite to delete

        Returns:
            True if deleted, False if not found
        """
        pass


class FileTaskRewriteRepository(TaskRewriteRepository):
    """File-based implementation of TaskRewriteRepository"""

    def __init__(self, logs_dir: str = "logs/task_rewrite"):
        """
        Initialize file-based repository

        Args:
            logs_dir: Directory to store rewrite JSON files
        """
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized FileTaskRewriteRepository at {self.logs_dir}")

    async def save_rewrite(self, history: "TaskRewriteHistory") -> str:
        """
        Save a rewrite to a JSON file

        Args:
            history: TaskRewriteHistory instance to save

        Returns:
            rewrite_id: ID of the saved rewrite
        """
        filename = f"{history.rewrite_id}.json"
        filepath = self.logs_dir / filename

        data = history.to_dict()

        # Run file I/O in thread pool to avoid blocking
        await asyncio.to_thread(self._write_json_file, filepath, data)

        logger.info(f"Saved task rewrite to file: {filepath}")
        return history.rewrite_id

    def _write_json_file(self, filepath: Path, data: Dict[str, Any]):
        """Write JSON data to file (sync)"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    async def get_rewrite(self, rewrite_id: str) -> Optional["TaskRewriteHistory"]:
        """
        Retrieve a specific rewrite by ID

        Args:
            rewrite_id: ID of the rewrite to retrieve

        Returns:
            TaskRewriteHistory or None if not found
        """
        filename = f"{rewrite_id}.json"
        filepath = self.logs_dir / filename

        if not filepath.exists():
            logger.warning(f"Task rewrite not found: {rewrite_id}")
            return None

        try:
            from ..services.task_rewrite.models import TaskRewriteHistory

            # Run file I/O in thread pool
            data = await asyncio.to_thread(self._read_json_file, filepath)
            logger.debug(f"Loaded task rewrite: {rewrite_id}")
            return TaskRewriteHistory.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load task rewrite {rewrite_id}: {e}")
            return None

    def _read_json_file(self, filepath: Path) -> Dict[str, Any]:
        """Read JSON data from file (sync)"""
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    async def list_rewrites(
        self, limit: int = 10, offset: int = 0
    ) -> List["TaskRewriteHistory"]:
        """
        List rewrites with pagination, sorted by modification time (newest first)

        Args:
            limit: Maximum number of rewrites to return
            offset: Number of rewrites to skip

        Returns:
            List of TaskRewriteHistory instances
        """
        try:
            # Get all JSON files
            files = await asyncio.to_thread(lambda: list(self.logs_dir.glob("*.json")))

            # Sort by modification time (newest first)
            files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

            # Apply pagination
            paginated_files = files[offset : offset + limit]

            # Load rewrite data
            from ..services.task_rewrite.models import TaskRewriteHistory

            rewrites = []
            for filepath in paginated_files:
                try:
                    data = await asyncio.to_thread(self._read_json_file, filepath)
                    rewrite = TaskRewriteHistory.from_dict(data)
                    rewrites.append(rewrite)
                except Exception as e:
                    logger.error(f"Failed to load rewrite from {filepath}: {e}")
                    continue

            logger.debug(
                f"Listed {len(rewrites)} task rewrites (limit={limit}, offset={offset})"
            )
            return rewrites

        except Exception as e:
            logger.error(f"Failed to list task rewrites: {e}")
            return []

    async def delete_rewrite(self, rewrite_id: str) -> bool:
        """
        Delete a rewrite file

        Args:
            rewrite_id: ID of the rewrite to delete

        Returns:
            True if deleted, False if not found
        """
        filename = f"{rewrite_id}.json"
        filepath = self.logs_dir / filename

        if not filepath.exists():
            logger.warning(f"Task rewrite not found for deletion: {rewrite_id}")
            return False

        try:
            await asyncio.to_thread(filepath.unlink)
            logger.info(f"Deleted task rewrite: {rewrite_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete task rewrite {rewrite_id}: {e}")
            return False


class MongoTaskRewriteRepository(TaskRewriteRepository):
    """MongoDB-based implementation of TaskRewriteRepository"""

    def __init__(
        self,
        mongodb_uri: str,
        database: str = "ai_agent",
        collection: str = "task_rewrite",
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
            self.collection.create_index([("rewrite_id", 1)], unique=True)
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

    async def save_rewrite(self, history: "TaskRewriteHistory") -> str:
        """
        Save a rewrite to MongoDB

        Args:
            history: TaskRewriteHistory instance to save

        Returns:
            rewrite_id: ID of the saved rewrite
        """
        data = history.to_dict()
        # Add MongoDB-specific fields
        mongodb_doc = data.copy()
        mongodb_doc["created_at"] = history.created_at

        try:
            # Run MongoDB operation in thread pool
            await asyncio.to_thread(
                self.collection.replace_one,
                {"rewrite_id": history.rewrite_id},
                mongodb_doc,
                upsert=True,
            )

            logger.info(f"Saved task rewrite to MongoDB: {history.rewrite_id}")
            return history.rewrite_id

        except Exception as e:
            logger.error(f"Failed to save task rewrite to MongoDB: {e}")
            raise

    async def get_rewrite(self, rewrite_id: str) -> Optional["TaskRewriteHistory"]:
        """
        Retrieve a specific rewrite by ID

        Args:
            rewrite_id: ID of the rewrite to retrieve

        Returns:
            TaskRewriteHistory or None if not found
        """
        try:
            # Run MongoDB operation in thread pool
            doc = await asyncio.to_thread(
                self.collection.find_one, {"rewrite_id": rewrite_id}
            )

            if doc:
                from ..services.task_rewrite.models import TaskRewriteHistory

                # Remove MongoDB's _id field
                doc.pop("_id", None)
                logger.debug(f"Loaded task rewrite from MongoDB: {rewrite_id}")
                return TaskRewriteHistory.from_dict(doc)
            else:
                logger.warning(f"Task rewrite not found in MongoDB: {rewrite_id}")
                return None

        except Exception as e:
            logger.error(f"Failed to load task rewrite {rewrite_id} from MongoDB: {e}")
            return None

    async def list_rewrites(
        self, limit: int = 10, offset: int = 0
    ) -> List["TaskRewriteHistory"]:
        """
        List rewrites with pagination, sorted by creation time (newest first)

        Args:
            limit: Maximum number of rewrites to return
            offset: Number of rewrites to skip

        Returns:
            List of TaskRewriteHistory instances
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
            from ..services.task_rewrite.models import TaskRewriteHistory

            rewrites = []
            for doc in docs:
                doc.pop("_id", None)
                rewrite = TaskRewriteHistory.from_dict(doc)
                rewrites.append(rewrite)

            logger.debug(
                f"Listed {len(rewrites)} task rewrites from MongoDB (limit={limit}, offset={offset})"
            )
            return rewrites

        except Exception as e:
            logger.error(f"Failed to list task rewrites from MongoDB: {e}")
            return []

    async def delete_rewrite(self, rewrite_id: str) -> bool:
        """
        Delete a rewrite from MongoDB

        Args:
            rewrite_id: ID of the rewrite to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            # Run MongoDB operation in thread pool
            result = await asyncio.to_thread(
                self.collection.delete_one, {"rewrite_id": rewrite_id}
            )

            if result.deleted_count > 0:
                logger.info(f"Deleted task rewrite from MongoDB: {rewrite_id}")
                return True
            else:
                logger.warning(
                    f"Task rewrite not found for deletion in MongoDB: {rewrite_id}"
                )
                return False

        except Exception as e:
            logger.error(
                f"Failed to delete task rewrite {rewrite_id} from MongoDB: {e}"
            )
            return False

    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")
