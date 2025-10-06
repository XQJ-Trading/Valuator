"""History controller for handling session history API endpoints"""

from typing import Dict, Any, List, Optional
from fastapi import HTTPException

from server.repositories.base import SessionRepository
from server.core.utils.logger import logger


class HistoryController:
    """Controller for history operations"""
    
    def __init__(self, history_repository: SessionRepository):
        """Initialize history controller with repository"""
        self.repository = history_repository
        
    async def get_sessions(
        self, 
        limit: int = 10, 
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get list of sessions with pagination
        
        Args:
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip
            
        Returns:
            Dict containing sessions list and metadata
        """
        try:
            logger.info(f"Fetching sessions: limit={limit}, offset={offset}")
            
            sessions = await self.repository.list_sessions(limit=limit, offset=offset)
            total_count = await self.repository.get_total_count() if hasattr(self.repository, 'get_total_count') else len(sessions)
            
            return {
                "sessions": sessions,
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"Error fetching sessions: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """
        Get specific session by ID
        
        Args:
            session_id: ID of the session to retrieve
            
        Returns:
            Dict containing session data
        """
        try:
            logger.info(f"Fetching session: {session_id}")
            
            session = await self.repository.get_session(session_id)
            
            if session is None:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            
            return {
                "session": session,
                "status": "success"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching session {session_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def search_sessions(self, query: str) -> Dict[str, Any]:
        """
        Search sessions by query string
        
        Args:
            query: Search query string
            
        Returns:
            Dict containing matching sessions
        """
        try:
            logger.info(f"Searching sessions: {query}")
            
            sessions = await self.repository.search_sessions(query)
            
            return {
                "sessions": sessions,
                "query": query,
                "count": len(sessions),
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"Error searching sessions with query '{query}': {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def delete_session(self, session_id: str) -> Dict[str, Any]:
        """
        Delete a session
        
        Args:
            session_id: ID of the session to delete
            
        Returns:
            Dict containing deletion result
        """
        try:
            logger.info(f"Deleting session: {session_id}")
            
            success = await self.repository.delete_session(session_id)
            
            if not success:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            
            return {
                "session_id": session_id,
                "deleted": True,
                "status": "success"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def save_session(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save a session
        
        Args:
            session_data: Session data to save
            
        Returns:
            Dict containing save result
        """
        try:
            session_id = session_data.get("session_id")
            logger.info(f"Saving session: {session_id}")
            
            saved_session_id = await self.repository.save_session(session_data)
            
            return {
                "session_id": saved_session_id,
                "saved": True,
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def get_repository_status(self) -> Dict[str, Any]:
        """Get repository status information"""
        try:
            return {
                "repository_type": type(self.repository).__name__,
                "status": "connected",
                "features": {
                    "save_session": hasattr(self.repository, 'save_session'),
                    "get_session": hasattr(self.repository, 'get_session'),
                    "list_sessions": hasattr(self.repository, 'list_sessions'),
                    "search_sessions": hasattr(self.repository, 'search_sessions'),
                    "delete_session": hasattr(self.repository, 'delete_session'),
                    "get_total_count": hasattr(self.repository, 'get_total_count'),
                }
            }
        except Exception as e:
            logger.error(f"Error getting repository status: {e}")
            raise HTTPException(status_code=500, detail=str(e))
