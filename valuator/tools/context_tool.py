"""Tool for loading contextual knowledge needed to solve problems."""

from pathlib import Path
from typing import Any, Dict, Optional

from .base import ObservationData, ToolResult
from .react_tool import ReActBaseTool

FILE_PATH = Path(__file__).resolve()
WORKSPACE_ROOT = FILE_PATH.parents[3]
CONTEXT_DIR = FILE_PATH.parents[1] / "agent" / "context"
DEFAULT_FILE = CONTEXT_DIR / "README.md"


class ContextTool(ReActBaseTool):
    def __init__(self):
        super().__init__(
            name="context_tool",
            description=(
                "Retrieve contextual knowledge needed to solve problems. "
                "Use this to load domain-specific context that helps formulate "
                "action plans aligned with the query. The loaded context provides "
                "guidelines, specifications, and requirements that inform how to "
                "approach and solve the problem systematically."
            ),
        )

    def _resolve_path(
        self,
        path: Optional[str],
        profile: Optional[str],
        default: Optional[str] = None,
    ) -> Path:
        """Resolve target path with precedence: path > profile > default > README."""
        if path:
            path_obj = Path(path)
            return path_obj if path_obj.is_absolute() else WORKSPACE_ROOT / path_obj
        if profile:
            return CONTEXT_DIR / profile
        if default:
            return CONTEXT_DIR / default
        return DEFAULT_FILE

    async def _execute_impl(
        self,
        path: Optional[str] = None,
        profile: Optional[str] = None,
        default: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        target_path = self._resolve_path(path=path, profile=profile, default=default)
        path_str = str(target_path)
        content = target_path.read_text(encoding="utf-8")

        observation = ObservationData(
            data={"context": content, "path": path_str},
            observation=f"Context loaded from {path_str}",
            store_output=False,
            store_result=False,
            skip_llm=False,
            log_query="context_tool",
            log_response=path_str,
        )
        return ToolResult(
            success=True,
            result=observation,
            metadata={"path": path_str},
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "string",
                        "description": "Filename within agent/context directory (e.g., 'valuation_prompt.md'). Takes precedence over default but not over path.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Absolute file path or relative path from workspace root. Takes precedence over profile and default.",
                    },
                    "default": {
                        "type": "string",
                        "description": "README.md",
                    },
                },
                "required": [],
            },
        }
