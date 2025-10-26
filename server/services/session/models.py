"""Session data models and enums"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class SessionStatus(str, Enum):
    """Session lifecycle states"""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SessionEvent:
    """Individual session event"""

    type: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tool: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result = {
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
        if self.tool:
            result["tool"] = self.tool
        if self.tool_input:
            result["tool_input"] = self.tool_input
        if self.tool_output:
            result["tool_output"] = self.tool_output
        if self.error:
            result["error"] = self.error
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class SessionData:
    """Session data container"""

    session_id: str
    query: str
    model: str
    status: SessionStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    events: list[SessionEvent] = field(default_factory=list)
    subscriber_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "session_id": self.session_id,
            "query": self.query,
            "model": self.model,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "events": [event.to_dict() for event in self.events],
            "event_count": len(self.events),
            "subscriber_count": self.subscriber_count,
            "error": self.error,
        }
