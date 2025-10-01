"""Simple ReAct session logging"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False

from .config import config
from .logger import logger


class ReActLogger:
    """Simple logger for ReAct sessions"""
    
    def __init__(self, logs_dir: str = "logs/react_sessions"):
        """Initialize ReAct logger"""
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.current_session = None
        
        # Initialize MongoDB connection if enabled
        self.mongodb_client = None
        self.mongodb_db = None
        self.mongodb_collection = None
        self._init_mongodb()
    
    def _init_mongodb(self):
        """Initialize MongoDB connection"""
        if not config.mongodb_enabled or not config.mongodb_uri:
            logger.debug("MongoDB logging disabled or URI not configured")
            return
        
        if not MONGODB_AVAILABLE:
            logger.warning("MongoDB logging enabled but pymongo not installed")
            return
        
        try:
            self.mongodb_client = MongoClient(
                config.mongodb_uri,
                serverSelectionTimeoutMS=5000,  # 5 second timeout
                connectTimeoutMS=5000,
                socketTimeoutMS=5000
            )
            
            # Test connection
            self.mongodb_client.admin.command('ping')
            
            self.mongodb_db = self.mongodb_client[config.mongodb_database]
            self.mongodb_collection = self.mongodb_db[config.mongodb_collection]
            
            logger.info(f"MongoDB connection established: {config.mongodb_database}.{config.mongodb_collection}")
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"Failed to connect to MongoDB: {e}")
            self.mongodb_client = None
        except Exception as e:
            logger.error(f"Unexpected error initializing MongoDB: {e}")
            self.mongodb_client = None
        
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
    
    def log_step(self, step_type: str, content: str, tool_name: str = None, 
                 tool_input: Dict = None, tool_output: Any = None, error: str = None,
                 api_query: str = None, api_response: str = None):
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
            step["api_query"] = self._truncate_api_query(api_query)  # Truncate to first 300 + last 600 chars
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
    
    def end_session(self, final_answer: str = None, success: bool = True):
        """End the current ReAct session and save to file"""
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
        del self.current_session["start_time"]
        
        # Save to JSON file
        filename = f"{self.current_session['session_id']}.json"
        filepath = self.logs_dir / filename
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.current_session, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved ReAct session to JSON file: {filepath}")
            
        except Exception as e:
            logger.error(f"Failed to save ReAct session to JSON file: {e}")
        
        # Save to MongoDB (if enabled and available)
        self._save_to_mongodb()
        
        # Clear current session
        self.current_session = None
    
    def _save_to_mongodb(self):
        """Save current session to MongoDB"""
        if not self.mongodb_collection or not self.current_session:
            return
        
        try:
            # Create a copy for MongoDB (without circular references)
            mongodb_doc = self.current_session.copy()
            
            # Add MongoDB-specific fields
            mongodb_doc["created_at"] = datetime.now()
            mongodb_doc["source"] = "react_logger"
            
            # Insert document
            result = self.mongodb_collection.insert_one(mongodb_doc)
            
            logger.info(f"Saved ReAct session to MongoDB: {result.inserted_id}")
            
        except Exception as e:
            logger.error(f"Failed to save ReAct session to MongoDB: {e}")
            # Don't raise - we want JSON saving to continue working even if MongoDB fails
    
    def get_recent_sessions(self, limit: int = 10) -> list:
        """Get list of recent session files"""
        try:
            files = list(self.logs_dir.glob("*.json"))
            files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            return [f.name for f in files[:limit]]
        except Exception as e:
            logger.error(f"Failed to get recent sessions: {e}")
            return []
    
    def load_session(self, session_file: str) -> Optional[Dict[str, Any]]:
        """Load a specific session"""
        try:
            filepath = self.logs_dir / session_file
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load session {session_file}: {e}")
            return None


def view_session_log(session_file: str = None, logs_dir: str = "logs/react_sessions"):
    """Simple function to view a ReAct session log"""
    logger_instance = ReActLogger(logs_dir)
    
    if not session_file:
        # Show recent sessions
        recent = logger_instance.get_recent_sessions(5)
        print("\n📋 Recent ReAct Sessions:")
        print("-" * 50)
        for i, filename in enumerate(recent, 1):
            print(f"{i}. {filename}")
        
        if recent:
            try:
                choice = input("\nEnter session number to view (or press Enter to exit): ").strip()
                if choice.isdigit():
                    session_file = recent[int(choice) - 1]
                else:
                    return
            except (ValueError, IndexError):
                print("Invalid choice")
                return
    
    # Load and display session
    session = logger_instance.load_session(session_file)
    if not session:
        print(f"❌ Could not load session: {session_file}")
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
            if step.get('api_query'):
                print(f"   📤 API Query: {step['api_query'][:200]}{'...' if len(step['api_query']) > 200 else ''}")
        elif step_type == 'action':
            print(f"\n⚡ Action {i}: {content}")
            if step.get('tool'):
                print(f"   🛠️  Tool: {step['tool']}")
            if step.get('api_query'):
                print(f"   📤 API Query: {step['api_query'][:200]}{'...' if len(step['api_query']) > 200 else ''}")
        elif step_type == 'observation':
            print(f"\n👁️  Observation {i}: {content}")
            if step.get('error'):
                print(f"   ❌ Error: {step['error']}")
            if step.get('api_query'):
                print(f"   📤 API Query: {step['api_query'][:200]}{'...' if len(step['api_query']) > 200 else ''}")
        elif step_type == 'final_answer':
            print(f"\n🎯 Final Answer: {content}")
            if step.get('api_query'):
                print(f"   📤 API Query: {step['api_query'][:200]}{'...' if len(step['api_query']) > 200 else ''}")
    
    if session.get('final_answer'):
        print(f"\n🎯 Final Answer: {session['final_answer']}")
    
    print("\n" + "=" * 80)


def list_all_sessions(logs_dir: str = "logs/react_sessions"):
    """List all saved ReAct sessions"""
    logger_instance = ReActLogger(logs_dir)
    sessions = logger_instance.get_recent_sessions(50)  # Get more sessions
    
    if not sessions:
        print("📭 No ReAct sessions found.")
        return
    
    print(f"\n📚 All ReAct Sessions ({len(sessions)} total):")
    print("-" * 80)
    
    for i, filename in enumerate(sessions, 1):
        # Extract date from filename
        try:
            date_part = filename.split('_')[0]
            time_part = filename.split('_')[1]
            formatted_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
            formatted_time = f"{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
            print(f"{i:2d}. {formatted_date} {formatted_time} - {filename}")
        except:
            print(f"{i:2d}. {filename}")


# Global logger instance
react_logger = ReActLogger()
