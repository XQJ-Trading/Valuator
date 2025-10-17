"""Web search tool for AI Agent"""

import asyncio
from typing import Any, Dict, List, Optional

import aiohttp

from .base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    """Web search tool for searching the internet"""

    def __init__(
        self, api_key: Optional[str] = None, search_engine_id: Optional[str] = None
    ):
        super().__init__(
            name="web_search", description="Search the web for information"
        )
        self.api_key = api_key
        self.search_engine_id = search_engine_id
        self.base_url = "https://www.googleapis.com/customsearch/v1"

    async def execute(
        self, query: str, num_results: int = 5, language: str = "en"
    ) -> ToolResult:
        """
        Search the web for information

        Args:
            query: Search query
            num_results: Number of results to return (max 10)
            language: Language code for search results

        Returns:
            ToolResult with search results
        """
        try:
            if not self.api_key or not self.search_engine_id:
                return ToolResult(
                    success=False,
                    result=None,
                    error="Search API key and search engine ID not configured",
                )

            # Limit results
            num_results = min(num_results, 10)

            # Build API request
            params = {
                "key": self.api_key,
                "cx": self.search_engine_id,
                "q": query,
                "num": num_results,
                "lr": f"lang_{language}",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        search_results = self._format_search_results(data)

                        return ToolResult(
                            success=True,
                            result=search_results,
                            metadata={
                                "query": query,
                                "total_results": data.get("searchInformation", {}).get(
                                    "totalResults", "0"
                                ),
                                "search_time": data.get("searchInformation", {}).get(
                                    "searchTime", "0"
                                ),
                            },
                        )
                    else:
                        error_data = await response.json()
                        return ToolResult(
                            success=False,
                            result=None,
                            error=f"Search API error: {error_data.get('error', {}).get('message', 'Unknown error')}",
                        )

        except Exception as e:
            return ToolResult(
                success=False, result=None, error=f"Search request error: {str(e)}"
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get tool schema for function calling"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to look up on the web",
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "Number of search results to return (1-10, default: 5)",
                            "minimum": 1,
                            "maximum": 10,
                            "default": 5,
                        },
                        "language": {
                            "type": "string",
                            "description": "Language code for search results (e.g., 'en', 'ko', 'ja')",
                            "default": "en",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def _format_search_results(self, data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Format search results for display"""
        results = []

        for item in data.get("items", []):
            result = {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "display_link": item.get("displayLink", ""),
            }
            results.append(result)

        return results
