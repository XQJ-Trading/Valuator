"""ReAct state management"""

from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel


class ReActStepType(Enum):
    """Types of ReAct steps"""
    THOUGHT = "thought"
    ACTION = "action" 
    OBSERVATION = "observation"
    FINAL_ANSWER = "final_answer"


@dataclass
class ReActStep:
    """Single step in ReAct process"""
    step_type: ReActStepType
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[Any] = None
    error: Optional[str] = None


class ReActState(BaseModel):
    """State management for ReAct process"""
    
    original_query: str
    steps: List[ReActStep] = []
    current_step: int = 0
    max_steps: int = 10
    is_completed: bool = False
    final_answer: Optional[str] = None
    error: Optional[str] = None
    context: Dict[str, Any] = {}
    
    class Config:
        arbitrary_types_allowed = True
    
    def add_step(self, step: ReActStep):
        """Add a new step to the process"""
        self.steps.append(step)
        self.current_step += 1
    
    def add_thought(self, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add a thought step"""
        step = ReActStep(
            step_type=ReActStepType.THOUGHT,
            content=content,
            metadata=metadata or {}
        )
        self.add_step(step)
    
    def add_action(self, content: str, tool_name: str, tool_input: Dict[str, Any], 
                   metadata: Optional[Dict[str, Any]] = None):
        """Add an action step"""
        step = ReActStep(
            step_type=ReActStepType.ACTION,
            content=content,
            tool_name=tool_name,
            tool_input=tool_input,
            metadata=metadata or {}
        )
        self.add_step(step)
    
    def add_observation(self, content: str, tool_output: Any = None, error: Optional[str] = None,
                       metadata: Optional[Dict[str, Any]] = None):
        """Add an observation step"""
        step = ReActStep(
            step_type=ReActStepType.OBSERVATION,
            content=content,
            tool_output=tool_output,
            error=error,
            metadata=metadata or {}
        )
        self.add_step(step)
    
    def set_final_answer(self, answer: str):
        """Set the final answer and mark as completed"""
        step = ReActStep(
            step_type=ReActStepType.FINAL_ANSWER,
            content=answer
        )
        self.add_step(step)
        self.final_answer = answer
        self.is_completed = True
    
    def should_continue(self) -> bool:
        """Check if the ReAct process should continue"""
        if self.is_completed:
            return False
        if self.current_step >= self.max_steps:
            return False
        if self.error:
            return False
        return True
    
    def get_last_step(self) -> Optional[ReActStep]:
        """Get the last step"""
        return self.steps[-1] if self.steps else None
    
    def get_steps_by_type(self, step_type: ReActStepType) -> List[ReActStep]:
        """Get all steps of a specific type"""
        return [step for step in self.steps if step.step_type == step_type]
    
    def format_history(self) -> str:
        """Format the step history for display"""
        formatted = f"Query: {self.original_query}\n\n"
        
        for i, step in enumerate(self.steps, 1):
            if step.step_type == ReActStepType.THOUGHT:
                formatted += f"Thought {i}: {step.content}\n\n"
            elif step.step_type == ReActStepType.ACTION:
                formatted += f"Action {i}: {step.content}\n"
                if step.tool_name:
                    formatted += f"Tool: {step.tool_name}\n"
                    formatted += f"Input: {step.tool_input}\n\n"
            elif step.step_type == ReActStepType.OBSERVATION:
                formatted += f"Observation {i}: {step.content}\n"
                if step.error:
                    formatted += f"Error: {step.error}\n"
                formatted += "\n"
            elif step.step_type == ReActStepType.FINAL_ANSWER:
                formatted += f"Final Answer: {step.content}\n"
        
        return formatted
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary"""
        return {
            "original_query": self.original_query,
            "steps": [
                {
                    "step_type": step.step_type.value,
                    "content": step.content,
                    "timestamp": step.timestamp.isoformat(),
                    "metadata": step.metadata,
                    "tool_name": step.tool_name,
                    "tool_input": step.tool_input,
                    "tool_output": step.tool_output,
                    "error": step.error
                }
                for step in self.steps
            ],
            "current_step": self.current_step,
            "max_steps": self.max_steps,
            "is_completed": self.is_completed,
            "final_answer": self.final_answer,
            "error": self.error,
            "context": self.context
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReActState":
        """Create state from dictionary"""
        state = cls(
            original_query=data["original_query"],
            current_step=data.get("current_step", 0),
            max_steps=data.get("max_steps", 10),
            is_completed=data.get("is_completed", False),
            final_answer=data.get("final_answer"),
            error=data.get("error"),
            context=data.get("context", {})
        )
        
        # Reconstruct steps
        for step_data in data.get("steps", []):
            step = ReActStep(
                step_type=ReActStepType(step_data["step_type"]),
                content=step_data["content"],
                timestamp=datetime.fromisoformat(step_data["timestamp"]),
                metadata=step_data.get("metadata", {}),
                tool_name=step_data.get("tool_name"),
                tool_input=step_data.get("tool_input"),
                tool_output=step_data.get("tool_output"),
                error=step_data.get("error")
            )
            state.steps.append(step)
        
        return state
