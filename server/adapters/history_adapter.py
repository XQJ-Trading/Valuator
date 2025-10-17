"""Adapter to convert session logs to stream event format"""

from typing import Any, Dict, List


class HistoryAdapter:
    """Adapter for converting session log format to stream event format"""

    @staticmethod
    def session_to_stream_events(session: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert a session log to stream event format

        Args:
            session: Session data from repository (JSON log format)

        Returns:
            List of stream events compatible with frontend
        """
        if not session:
            return []

        # For new chat sessions, events are already stored in StreamEvent format
        if "events" in session:
            return session["events"]

        # Legacy support: convert old format with "steps"
        events = []

        # Start event
        events.append({"type": "start", "query": session.get("query", "")})

        # Convert steps to stream events (skip final_answer type as it will be added separately)
        steps = session.get("steps", [])
        for step in steps:
            # Skip final_answer steps as they'll be added from session.final_answer
            if step.get("type") == "final_answer":
                continue

            event = HistoryAdapter._step_to_event(step)
            if event:
                events.append(event)

        # Final answer event (use session's final_answer for consistency)
        final_answer = session.get("final_answer")
        if final_answer:
            events.append(
                {
                    "type": "final_answer",
                    "content": final_answer,
                    "success": session.get("success", False),
                }
            )

        # End event
        events.append({"type": "end"})

        return events

    @staticmethod
    def _step_to_event(step: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a single step to a stream event

        Args:
            step: Step data from session log

        Returns:
            Stream event dictionary
        """
        step_type = step.get("type")

        if step_type == "thought":
            return {"type": "thought", "content": step.get("content", "")}

        elif step_type == "action":
            event = {"type": "action", "content": step.get("content", "")}

            # Add tool information if present
            if step.get("tool"):
                event["tool"] = step["tool"]
            if step.get("tool_input"):
                event["tool_input"] = step["tool_input"]

            return event

        elif step_type == "observation":
            event = {"type": "observation", "content": step.get("content", "")}

            # Add tool output and error if present
            if step.get("tool_output"):
                event["tool_output"] = step["tool_output"]
            if step.get("error"):
                event["error"] = step["error"]

            # Add tool_result if present (from newer logs)
            if step.get("tool_result"):
                event["tool_result"] = step["tool_result"]

            return event

        elif step_type == "final_answer":
            return {"type": "final_answer", "content": step.get("content", "")}

        # Unknown step type - return as-is with warning
        return step

    @staticmethod
    def session_to_summary(session: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a session to a summary format for list views

        Args:
            session: Session data from repository

        Returns:
            Summary dictionary with key information
        """
        # Support both new format (events) and legacy format (steps)
        event_count = len(session.get("events", session.get("steps", [])))

        return {
            "session_id": session.get("session_id", "unknown"),
            "timestamp": session.get("timestamp", ""),
            "query": session.get("query", ""),
            "final_answer": session.get("final_answer", "")[
                :200
            ],  # Truncate for summary
            "success": session.get("success", False),
            "duration": session.get("duration", 0),
            "step_count": event_count,
            "tools_used": HistoryAdapter._extract_tools_used(session),
        }

    @staticmethod
    def _extract_tools_used(session: Dict[str, Any]) -> List[str]:
        """Extract list of unique tools used in session"""
        tools = set()

        # Check new format first (events)
        events = session.get("events", [])
        if events:
            for event in events:
                if event.get("type") == "action" and event.get("metadata", {}).get(
                    "tool"
                ):
                    tools.add(event["metadata"]["tool"])
                # Also check direct tool field for compatibility
                elif event.get("type") == "action" and event.get("tool"):
                    tools.add(event["tool"])
        else:
            # Legacy format (steps)
            steps = session.get("steps", [])
            for step in steps:
                if step.get("type") == "action" and step.get("tool"):
                    tools.add(step["tool"])

        return list(tools)

    @staticmethod
    def sessions_to_summaries(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert multiple sessions to summary format

        Args:
            sessions: List of session data from repository

        Returns:
            List of summary dictionaries
        """
        return [HistoryAdapter.session_to_summary(session) for session in sessions]
