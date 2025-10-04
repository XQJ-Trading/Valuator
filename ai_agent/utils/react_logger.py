"""Simple ReAct session logging with Repository pattern"""

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

from .config import config
from .logger import logger


class ReActLogger:
    """Simple logger for ReAct sessions using Repository pattern"""
    
    def __init__(self, repository=None):
        """
        Initialize ReAct logger with a repository
        
        Args:
            repository: SessionRepository instance for data persistence
                       If None, will be lazily initialized based on config
        """
        self._repository = repository
        self.current_session = None
        
        logger.info("Initialized ReActLogger with Repository pattern")
    
    @property
    def repository(self):
        """Lazy initialization of repository based on config"""
        if self._repository is None:
            self._repository = self._create_repository_from_config()
        return self._repository
    
    def _create_repository_from_config(self):
        """Create repository based on configuration"""
        from ..repositories import FileSessionRepository, MongoSessionRepository
        
        if config.mongodb_enabled and config.mongodb_uri:
            try:
                logger.info("Initializing MongoDB repository for session logging")
                return MongoSessionRepository(
                    mongodb_uri=config.mongodb_uri,
                    database=config.mongodb_database,
                    collection=config.mongodb_collection
                )
            except Exception as e:
                logger.warning(f"Failed to initialize MongoDB repository: {e}")
                logger.info("Falling back to file repository")
                return FileSessionRepository("logs/react_sessions")
        else:
            logger.info("Initializing file repository for session logging")
            return FileSessionRepository("logs/react_sessions")
    
    def start_session(self, query: str) -> str:
        """Start a new ReAct session"""
        timestamp = datetime.now()
        session_id = timestamp.strftime("%Y%m%d_%H%M%S_session")
        
        self.current_session = {
            "session_id": session_id,
            "timestamp": timestamp.isoformat(),
            "query": query,
            "steps": [],
            "final_answer": None,
            "success": False,
            "duration": 0,
            "start_time": timestamp
        }
        
        logger.info(f"Started ReAct session: {session_id}")
        return session_id
    
    def log_step(
        self, 
        step_type: str, 
        content: str, 
        tool_name: Optional[str] = None, 
        tool_input: Optional[Dict] = None, 
        tool_output: Any = None, 
        error: Optional[str] = None,
        api_query: Optional[str] = None, 
        api_response: Optional[str] = None
    ):
        """Log a ReAct step"""
        if not self.current_session:
            return
        
        step = {
            "type": step_type,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        if tool_name:
            step["tool"] = tool_name
        if tool_input:
            step["tool_input"] = tool_input
        if tool_output:
            step["tool_output"] = str(tool_output)[:500]  # Limit output size
        if error:
            step["error"] = error
        if api_query:
            step["api_query"] = self._truncate_api_query(api_query)
        if api_response:
            step["api_response"] = api_response[:1000]  # Limit response size
            
        self.current_session["steps"].append(step)
        logger.debug(f"Logged {step_type} step: {content[:50]}...")
    
    def _truncate_api_query(self, api_query: str) -> str:
        """Truncate API query to first 300 chars + last 600 chars"""
        if not api_query:
            return ""
        
        total_chars = len(api_query)
        
        # If the query is short enough, return as is
        if total_chars <= 900:  # 300 + 600
            return api_query
        
        # Get first 300 chars
        first_part = api_query[:300]
        
        # Get last 600 chars
        last_part = api_query[-600:]
        
        # Calculate how many characters are being skipped
        skipped_chars = total_chars - 900
        
        # Combine with ellipsis indicating truncation
        return f"{first_part}\n\n... [생략된 문자 수: {skipped_chars}자] ...\n\n{last_part}"
    
    def end_session(self, final_answer: Optional[str] = None, success: bool = True):
        """End the current ReAct session and save using repository"""
        if not self.current_session:
            return
        
        # Calculate duration
        end_time = datetime.now()
        duration = (end_time - self.current_session["start_time"]).total_seconds()
        
        # Update session info
        self.current_session["final_answer"] = final_answer
        self.current_session["success"] = success
        self.current_session["duration"] = round(duration, 2)
        self.current_session["end_time"] = end_time.isoformat()
        
        # Remove start_time (not JSON serializable)
        session_to_save = self.current_session.copy()
        del session_to_save["start_time"]
        
        # Save using repository (async operation, run in event loop)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If event loop is running, schedule the coroutine
                asyncio.create_task(self.repository.save_session(session_to_save))
            else:
                # If no event loop is running, run it synchronously
                loop.run_until_complete(self.repository.save_session(session_to_save))
            
            logger.info(f"Saved ReAct session: {session_to_save['session_id']}")
            
        except Exception as e:
            logger.error(f"Failed to save ReAct session: {e}")
        
        # Clear current session
        self.current_session = None
    
    async def get_recent_sessions(self, limit: int = 10) -> list:
        """Get list of recent sessions using repository"""
        try:
            sessions = await self.repository.list_sessions(limit=limit, offset=0)
            return [session.get("session_id", "unknown") for session in sessions]
        except Exception as e:
            logger.error(f"Failed to get recent sessions: {e}")
            return []
    
    async def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load a specific session using repository"""
        try:
            return await self.repository.get_session(session_id)
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None


# View functions for backward compatibility
async def view_session_log_async(session_id: str = None, repository=None):
    """Async function to view a ReAct session log"""
    if repository is None:
        from ..repositories import FileSessionRepository
        repository = FileSessionRepository("logs/react_sessions")
    
    if not session_id:
        # Show recent sessions
        sessions = await repository.list_sessions(limit=5, offset=0)
        print("\n📋 Recent ReAct Sessions:")
        print("-" * 50)
        for i, session in enumerate(sessions, 1):
            print(f"{i}. {session.get('session_id', 'Unknown')}")
        
        if sessions:
            try:
                choice = input("\nEnter session number to view (or press Enter to exit): ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(sessions):
                    session_id = sessions[int(choice) - 1].get("session_id")
                else:
                    return
            except (ValueError, IndexError):
                print("Invalid choice")
                return
    
    # Load and display session
    session = await repository.get_session(session_id)
    if not session:
        print(f"❌ Could not load session: {session_id}")
        return
    
    # Display session
    print(f"\n🧠 ReAct Session: {session.get('session_id', 'Unknown')}")
    print("=" * 80)
    print(f"📅 Time: {session.get('timestamp', 'Unknown')}")
    print(f"❓ Query: {session.get('query', 'Unknown')}")
    print(f"⏱️  Duration: {session.get('duration', 0)} seconds")
    print(f"✅ Success: {session.get('success', False)}")
    print("\n🔄 Steps:")
    print("-" * 50)
    
    for i, step in enumerate(session.get('steps', []), 1):
        step_type = step.get('type', 'unknown')
        content = step.get('content', '')
        
        if step_type == 'thought':
            print(f"\n💭 Thought {i}: {content}")
        elif step_type == 'action':
            print(f"\n⚡ Action {i}: {content}")
            if step.get('tool'):
                print(f"   🛠️  Tool: {step['tool']}")
        elif step_type == 'observation':
            print(f"\n👁️  Observation {i}: {content}")
            if step.get('error'):
                print(f"   ❌ Error: {step['error']}")
        elif step_type == 'final_answer':
            print(f"\n🎯 Final Answer: {content}")
    
    if session.get('final_answer'):
        print(f"\n🎯 Final Answer: {session['final_answer']}")
    
    print("\n" + "=" * 80)


def view_session_log(session_id: str = None, logs_dir: str = "logs/react_sessions"):
    """Synchronous wrapper for view_session_log_async"""
    from ..repositories import FileSessionRepository
    repository = FileSessionRepository(logs_dir)
    asyncio.run(view_session_log_async(session_id, repository))


async def list_all_sessions_async(repository=None):
    """Async function to list all saved ReAct sessions"""
    if repository is None:
        from ..repositories import FileSessionRepository
        repository = FileSessionRepository("logs/react_sessions")
    
    sessions = await repository.list_sessions(limit=50, offset=0)
    
    if not sessions:
        print("📭 No ReAct sessions found.")
        return
    
    print(f"\n📚 All ReAct Sessions ({len(sessions)} total):")
    print("-" * 80)
    
    for i, session in enumerate(sessions, 1):
        session_id = session.get('session_id', 'Unknown')
        timestamp = session.get('timestamp', 'Unknown')
        query = session.get('query', 'No query')[:50]
        print(f"{i:2d}. [{timestamp}] {session_id}")
        print(f"     Query: {query}...")


def list_all_sessions(logs_dir: str = "logs/react_sessions"):
    """Synchronous wrapper for list_all_sessions_async"""
    from ..repositories import FileSessionRepository
    repository = FileSessionRepository(logs_dir)
    asyncio.run(list_all_sessions_async(repository))


# Global logger instance (with lazy repository initialization)
react_logger = ReActLogger()
