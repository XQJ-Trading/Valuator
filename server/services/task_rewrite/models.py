"""Task rewrite data models"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class TaskRewriteHistory:
    """Task rewrite history data model"""

    rewrite_id: str
    original_task: str
    rewritten_task: str
    model: str
    custom_prompt: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "rewrite_id": self.rewrite_id,
            "original_task": self.original_task,
            "rewritten_task": self.rewritten_task,
            "model": self.model,
            "custom_prompt": self.custom_prompt,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRewriteHistory":
        """Create instance from dictionary"""
        # Handle datetime conversion
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now()

        return cls(
            rewrite_id=data["rewrite_id"],
            original_task=data["original_task"],
            rewritten_task=data["rewritten_task"],
            model=data["model"],
            custom_prompt=data.get("custom_prompt"),
            created_at=created_at,
            metadata=data.get("metadata", {}),
        )
