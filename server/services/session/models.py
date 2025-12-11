"""Session data models and enums"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union


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
    tool_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    query: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary - compatible with v1 chat stream format"""
        result: Dict[str, Any] = {
            "type": self.type,
            "content": self.content,
        }

        # v1 형식과 호환되도록 필드 추가
        if self.tool:
            result["tool"] = self.tool
        if self.tool_input:
            result["tool_input"] = self.tool_input
        if self.tool_output:
            result["tool_output"] = self.tool_output
        if self.tool_result:
            result["tool_result"] = self.tool_result
        if self.error:
            result["error"] = self.error
        if self.metadata:
            result["metadata"] = self.metadata
        if self.query:
            result["query"] = self.query

        # v1 호환성을 위해 timestamp 추가 (없으면 생략)
        if self.timestamp:
            result["timestamp"] = self.timestamp.isoformat()

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
        """Convert to dictionary - compatible with v1 chat stream format"""
        # Extract final answer from events
        final_answer = ""
        for event in self.events:
            if event.type == "final_answer":
                final_answer = event.content
                break

        # Calculate duration (created_at to completed_at or now)
        if self.completed_at:
            duration = (self.completed_at - self.created_at).total_seconds()
        else:
            duration = (datetime.now() - self.created_at).total_seconds()

        # Determine success based on status
        success = self.status == SessionStatus.COMPLETED

        return {
            "session_id": self.session_id,
            "timestamp": self.created_at.isoformat(),  # v1 호환성을 위해 timestamp 사용
            "query": self.query,
            "events": [event.to_dict() for event in self.events],
            "final_answer": final_answer,  # v1 호환성
            "success": success,  # v1 호환성
            "duration": duration,  # v1 호환성
            "model": self.model,
            "source": "server_chat",  # v1 호환성
            # 추가 필드들 (v1에 없지만 유지)
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "event_count": len(self.events),
            "subscriber_count": self.subscriber_count,
            "error": self.error,
        }
