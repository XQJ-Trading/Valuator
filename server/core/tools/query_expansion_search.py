"""
Query expansion enhanced web search tool for AI Agent"""

import json
from typing import Any, Dict, List

from ..utils.config import config
from ..utils.logger import logger
from .base import BaseTool, ToolResult


class QueryExpansionSearchTool(BaseTool):
    """
    Enhanced web search tool with query expansion capabilities.

    This tool expands the original query into multiple related queries to gather
    more comprehensive information, executes them in parallel asynchronously,
    and consolidates the results.
    """

    def __init__(self):
        super().__init__(
            name="query_expansion_search",
            description="Enhanced web search with query expansion. Expands queries to gather more comprehensive information from multiple perspectives.",
        )

        # Query expansion configuration
        self.max_expansions = 5  # Reduced default from 5 to 3 for better performance
        self.max_concurrent_searches = 5
        self.default_expansion_depth = 3  # New default for automatic usage
        self.consolidation_prompt = """
        Based on the following search results from multiple expanded queries,
        provide a comprehensive and consolidated summary:

        {results}

        Please synthesize the information and provide:
        1. Key facts and findings
        2. Different perspectives covered
        3. Any contradictions or variations in information
        4. Overall conclusions or insights
        """

        from .react_tool import PerplexitySearchTool

        self.search_tool = PerplexitySearchTool()
        logger.info("QueryExpansionSearchTool initialized")

    async def _analyze_and_decompose_query(
        self, query: str, user_specified_depth: int = None
    ) -> List[str]:
        """
        Analyze query content and let LLM determine the optimal decomposition approach entirely

        Args:
            query: Original search query
            user_specified_depth: User-specified depth (optional - overrides LLM recommendation)

        Returns:
            List of decomposed sub-queries
        """
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(
                model=config.agent_model,
                temperature=0.1,  # Focused reasoning for decomposition
                max_tokens=800,  # Enough for reasonable analysis and sub-queries
                api_key=config.google_api_key,
            )

            # Let LLM analyze and decompose without hard-coded limits
            decomposition_prompt = f"""
            Analyze the following search query and determine how best to break it down into sub-queries for more effective web search:

            Query: "{query}"

            Your task:
            1. ANALYZE the query's complexity and specific requirements
            2. IDENTIFY how many meaningful sub-queries would be optimal (consider different aspects, time periods, data types, etc.)
            3. GENERATE that number of focused, specific sub-queries

            Guidelines:
            - Focus on creating sub-queries that are complementary and non-overlapping
            - Each sub-query should be searchable and answer a distinct aspect
            - Don't create more sub-queries than necessary - quality over quantity
            - Consider: time periods, different data points, geographic aspects, comparative elements

            Instructions:
            - First, reason about the query's structure and how to best decompose it
            - Then provide exactly the number of sub-queries you deem optimal
            - Format your response as a JSON array: ["sub-query 1", "sub-query 2", ...]

            Return ONLY the JSON array - no additional text or explanation.
            """

            messages = [
                SystemMessage(
                    content="You are an expert query decomposition specialist. Analyze search queries and break them into optimal sub-queries for comprehensive web search."
                ),
                HumanMessage(content=decomposition_prompt),
            ]

            response = await llm.ainvoke(messages)
            response_text = response.content.strip()

            # Try to parse JSON array
            try:
                # Clean up response
                if response_text.startswith("```json"):
                    response_text = (
                        response_text.replace("```json", "").replace("```", "").strip()
                    )
                elif response_text.startswith("```"):
                    response_text = response_text.replace("```", "").strip()

                if response_text.startswith("[") and response_text.endswith("]"):
                    sub_queries = json.loads(response_text)
                    if isinstance(sub_queries, list) and sub_queries:
                        # Filter to valid strings and remove duplicates
                        valid_queries = []
                        seen = set()
                        for q in sub_queries:
                            if isinstance(q, str) and q.strip():
                                clean_q = q.strip()
                                if clean_q.lower() not in seen:
                                    valid_queries.append(clean_q)
                                    seen.add(clean_q.lower())

                        if valid_queries:
                            self.logger.info(
                                f"LLM determined optimal decomposition: {len(valid_queries)} sub-queries: {valid_queries[:3]}{'...' if len(valid_queries) > 3 else ''}"
                            )
                            return valid_queries

            except json.JSONDecodeError:
                pass

            # Fallback with more targeted extraction
            import re

            quoted_strings = re.findall(r'"([^"]*)"', response_text)
            if quoted_strings and len(quoted_strings) > 1:
                valid_queries = [q.strip() for q in quoted_strings if q.strip()]
                valid_queries = list(set(valid_queries))  # Remove duplicates
                if len(valid_queries) >= 2:
                    self.logger.info(
                        f"Extracted {len(valid_queries)} sub-queries from LLM response"
                    )
                    return valid_queries

            # Last resort fallback
            self.logger.warning("LLM decomposition failed, using fallback analysis")
            return await self._emergency_decompose_query(query)

        except Exception as e:
            self.logger.warning(f"LLM-based decomposition failed: {e}, using fallback")
            return await self._emergency_decompose_query(query)

    async def _emergency_decompose_query(self, query: str) -> List[str]:
        """Emergency fallback decomposition when LLM completely fails"""
        # Split by various delimiters
        import re

        elements = re.split(r"[,\s]+(?:and\s+|or\s+)?", query)

        # Clean and filter elements
        clean_elements = []
        for elem in elements:
            elem = elem.strip()
            if len(elem) > 2 and elem.lower() not in ["the", "for", "with", "from"]:
                clean_elements.append(elem)

        # If we have multiple elements, break into 2-3 queries
        if len(clean_elements) >= 2:
            chunk_size = max(1, len(clean_elements) // 3)
            sub_queries = []

            for i in range(0, len(clean_elements), chunk_size):
                chunk = clean_elements[i : i + chunk_size]
                if chunk:
                    if len(chunk) == 1:
                        sub_queries.append(f"{chunk[0]} information")
                    else:
                        sub_queries.append(" ".join(chunk))

            return sub_queries[:3]  # Max 3 as fallback

        # Ultra simple fallback
        words = query.split()
        if len(words) > 1:
            mid = len(words) // 2
            return [query, " ".join(words[:mid]), " ".join(words[mid:])]

        # Last resort: just return the original query once
        return [query]

    async def execute(
        self, query: str, expansion_depth: int = 5, **kwargs
    ) -> ToolResult:
        """
        Execute query expansion search

        Args:
            query: Original search query
            expansion_depth: Number of query expansions to generate (max 5, default 5)
            **kwargs: Additional parameters for search

        Returns:
            ToolResult with consolidated search results
        """
        try:
            self.logger.info(f"Starting query expansion search for: {query}")

            # Let LLM determine optimal decomposition entirely
            decomposed_queries = await self._analyze_and_decompose_query(
                query, expansion_depth
            )

            # Step 2: Execute searches in parallel
            all_results = await self._execute_parallel_searches(
                decomposed_queries, **kwargs
            )

            # Step 3: Consolidate results
            consolidated_result = await self._consolidate_results(query, all_results)

            return ToolResult(
                success=True,
                result=consolidated_result,
                metadata={
                    "original_query": query,
                    "expanded_queries_count": len(decomposed_queries),
                    "total_searches_executed": len(all_results),
                    "decomposition_method": "llm_adaptive",
                },
            )

        except Exception as e:
            self.logger.error(f"Query expansion search failed: {e}")
            return ToolResult(
                success=False,
                result=None,
                error=f"Query expansion search failed: {str(e)}",
            )

    async def _expand_query(self, original_query: str, depth: int) -> List[str]:
        """
        Generate expanded queries using Query Rewrite + Query Decomposition approach
        """

        # Step 1: Query Rewrite - Improve the original query
        rewritten_query = await self._rewrite_query(original_query)

        # Step 2: Query Decomposition - Break down into sub-queries
        decomposed_queries = await self._decompose_query(rewritten_query, depth)

        self.logger.info(f"Query rewrite: '{original_query}' -> '{rewritten_query}'")
        self.logger.info(
            f"Query decomposition: Generated {len(decomposed_queries)} sub-queries: {decomposed_queries}"
        )

        # Return decomposed queries for recursive expansion
        return decomposed_queries

    async def _rewrite_query(self, original_query: str) -> str:
        """Rewrite the original query to be more effective for search"""
        try:
            from langchain_core.messages import HumanMessage
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(
                model=config.agent_model,
                temperature=0.1,
                max_tokens=200,
                api_key=config.google_api_key,
            )

            # For complex queries with multiple elements, don't rewrite - use as-is
            if "," in original_query or " and " in original_query.lower():
                return original_query

            rewrite_prompt = f"""
            Given the search query: "{original_query}"

            Rewrite this query to be more effective for web search. Make it:
            1. More specific and detailed
            2. Use keywords that are likely to appear in relevant web content
            3. Include context that helps distinguish this topic from similar ones

            Return only the rewritten query as a string, nothing else.
            """

            messages = [HumanMessage(content=rewrite_prompt)]
            response = await llm.ainvoke(messages)

            rewritten = response.content.strip()
            # Clean up response (remove quotes if present)
            rewritten = rewritten.strip('"').strip("'")

            return rewritten if rewritten else original_query

        except Exception as e:
            self.logger.warning(f"Query rewrite failed: {e}")
            return original_query

    def _analyze_query_depth(self, query: str, requested_depth: int) -> int:
        """
        Analyze query content to determine optimal expansion depth

        Args:
            query: The search query
            requested_depth: User requested depth

        Returns:
            Optimal depth based on query complexity
        """
        import re

        # Split by comma or 'and'
        elements = re.split(r"[,\s]+(?:and\s+)?", query)
        elements = [elem.strip() for elem in elements if elem.strip()]
        elements = [elem for elem in elements if len(elem) > 2]  # Filter short elements

        self.logger.info(
            f"Analyzed query '{query}' -> found {len(elements)} elements: {elements}"
        )

        # If we have clear separate concepts, use them as basis for depth
        if len(elements) >= 2:
            return min(len(elements), self.max_expansions)

        # For complex single queries, use maximum depth (default 5)
        return min(requested_depth, self.max_expansions)

    async def _decompose_query(self, rewritten_query: str, depth: int) -> List[str]:
        """Decompose the rewritten query into sub-queries for parallel execution"""
        try:
            from langchain_core.messages import HumanMessage
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(
                model=config.agent_model,
                temperature=0.1,  # 더 낮은 temperature로 속도와 정확성 향상
                max_tokens=600,
                api_key=config.google_api_key,
            )

            decomposition_prompt = f"""
            Given the search query: "{rewritten_query}"

            Break this query down into exactly {depth} different sub-queries that explore different aspects of the topic.
            Each sub-query should be independent and focus on one specific aspect.

            Return only a JSON array of exactly {depth} strings.
            Format: ["query 1", "query 2", "query 3"]
            """

            messages = [HumanMessage(content=decomposition_prompt)]
            response = await llm.ainvoke(messages)

            # Parse JSON response
            response_text = response.content.strip()

            # Try to extract JSON array
            try:
                # Clean up the response
                if response_text.startswith("```json"):
                    response_text = (
                        response_text.replace("```json", "").replace("```", "").strip()
                    )
                elif response_text.startswith("```"):
                    response_text = response_text.replace("```", "").strip()

                if response_text.startswith("[") and response_text.endswith("]"):
                    sub_queries = json.loads(response_text)
                    if isinstance(sub_queries, list) and sub_queries:
                        # Filter to only strings and take exactly depth number
                        valid_queries = [
                            str(q).strip() for q in sub_queries if str(q).strip()
                        ]
                        if len(valid_queries) >= depth:
                            return valid_queries[:depth]
                        elif len(valid_queries) > 0:
                            # If we have fewer than depth, return what we have
                            return valid_queries
            except json.JSONDecodeError:
                pass

            # Fallback 1: try to extract from text with patterns
            import re

            # Look for patterns like "1. query" or "- query" or quoted strings
            patterns = [
                r'^\s*\d+\.\s*"([^"]+)"',
                r"^\s*\d+\.\s*([^\n,]+)",
                r'^\s*-\s*"([^"]+)"',
                r"^\s*-\s*([^\n,]+)",
                r'"([^"]+)"',
            ]

            extracted = []
            for pattern in patterns:
                matches = re.findall(pattern, response_text, re.MULTILINE)
                if matches:
                    extracted.extend(matches)
                    if len(extracted) >= depth:
                        break

            if len(extracted) >= depth:
                return [q.strip() for q in extracted[:depth]]

            # Fallback 2: Simple decomposition based on keywords
            return self._simple_decomposition(rewritten_query, depth)

        except Exception as e:
            self.logger.warning(f"Query decomposition failed: {e}")
            return self._simple_decomposition(rewritten_query, depth)

    def _simple_decomposition(self, query: str, depth: int) -> List[str]:
        """Simple fallback decomposition when LLM fails"""
        # Extract key terms
        words = query.lower().split()
        key_terms = [
            w
            for w in words
            if len(w) > 3
            and w
            not in [
                "what",
                "when",
                "where",
                "which",
                "with",
                "from",
                "that",
                "this",
                "have",
                "been",
                "were",
                "will",
                "would",
                "could",
                "should",
                "about",
                "their",
                "there",
                "these",
                "those",
            ]
        ]

        if len(key_terms) < 2:
            # Very simple query, just return variations
            return [f"{query} overview", f"{query} details", f"{query} information"][
                :depth
            ]

        # Create different combinations
        sub_queries = []

        # Original query first
        sub_queries.append(query)

        # Focus on first key term
        if len(key_terms) > 0:
            sub_queries.append(
                f"{key_terms[0]} {' '.join(key_terms[1:2]) if len(key_terms) > 1 else ''} details".strip()
            )

        # Focus on business/financial if those terms appear
        if any(
            term in " ".join(key_terms)
            for term in ["business", "company", "corp", "inc", "ltd"]
        ):
            sub_queries.append(f"{query} financial profile")
            sub_queries.append(f"{query} business overview")

        # Focus on technical aspects
        elif any(
            term in " ".join(key_terms)
            for term in ["technology", "tech", "software", "system"]
        ):
            sub_queries.append(f"{query} technical details")
            sub_queries.append(f"{query} features and capabilities")

        # Fill remaining slots
        while len(sub_queries) < depth:
            if len(key_terms) > 1:
                sub_queries.append(f"{key_terms[0]} {key_terms[1]} information")
            else:
                sub_queries.append(f"{query} analysis")

        return sub_queries[:depth]

    async def _expand_with_llm(self, query: str, depth: int) -> List[str]:
        """Use LLM to generate more intelligent query expansions"""
        try:
            from langchain_core.messages import HumanMessage
            from langchain_google_genai import ChatGoogleGenerativeAI

            # Lazy import to avoid dependency issues
            llm = ChatGoogleGenerativeAI(
                model=config.agent_model,
                temperature=0.1,  # 더 낮은 temperature로 속도 향상
                max_tokens=500,  # 더 짧은 토큰으로 응답 속도 향상
                api_key=config.google_api_key,
            )

            expansion_prompt = f"""
            Given the search query: "{query}"

            Generate {depth} different but related search queries that would help gather more comprehensive information from different perspectives. Each query should:

            1. Complement the original query
            2. Explore different aspects, latest developments, or related concepts
            3. Be search-friendly (natural language)

            Return only the queries as a JSON array of strings, without any additional text.
            """

            messages = [HumanMessage(content=expansion_prompt)]
            response = await llm.ainvoke(messages)

            # Parse JSON response
            response_text = response.content.strip()
            if response_text.startswith("[") and response_text.endswith("]"):
                return json.loads(response_text)

            # Fallback: try to extract quoted strings
            import re

            queries = re.findall(r'"([^"]*)"', response_text)
            return queries[:depth]

        except Exception as e:
            self.logger.warning(f"LLM expansion failed: {e}")
            return []

    async def _execute_parallel_searches(
        self, queries: List[str], **search_kwargs
    ) -> List[Dict[str, Any]]:
        """Execute multiple searches in parallel"""

        async def single_search(query: str) -> Dict[str, Any]:
            """Execute a single search and return formatted result"""
            try:
                result = await self.search_tool.execute(query=query, **search_kwargs)
                return {
                    "query": query,
                    "success": result.success,
                    "result": result.result,
                    "error": result.error,
                    "metadata": result.metadata,
                }
            except Exception as e:
                self.logger.error(f"Search failed for query '{query}': {e}")
                return {
                    "query": query,
                    "success": False,
                    "result": None,
                    "error": str(e),
                    "metadata": {},
                }

        # Execute searches in parallel using asyncio.gather for efficiency
        # This allows multiple searches to run concurrently for better performance
        self.logger.info(
            f"Starting parallel searches for {len(queries)} queries: {queries}"
        )

        # Create tasks for concurrent execution
        tasks = [single_search(query) for query in queries]

        # Execute all searches concurrently and wait for all to complete
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error(f"Failed to execute parallel searches: {e}")
            return []

        # Process results, handling any exceptions that occurred
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Search {i+1} failed: {result}")
                processed_results.append(
                    {
                        "query": queries[i] if i < len(queries) else f"Query {i}",
                        "success": False,
                        "result": None,
                        "error": str(result),
                        "metadata": {},
                    }
                )
            else:
                processed_results.append(result)
                self.logger.info(
                    f"Search {i+1} completed {'successfully' if result['success'] else 'with error'}: {result['query']}"
                )

        successful_searches = sum(1 for r in processed_results if r["success"])
        self.logger.info(
            f"Completed {successful_searches}/{len(processed_results)} parallel searches out of {len(queries)} queries"
        )

        return processed_results

    async def _consolidate_results(
        self, original_query: str, all_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Consolidate results from multiple searches"""

        successful_results = [r for r in all_results if r["success"] and r["result"]]

        if not successful_results:
            return {
                "original_query": original_query,
                "total_searches": len(all_results),
                "successful_searches": 0,
                "consolidated_answer": "No successful search results to consolidate",
                "tried_queries": [r["query"] for r in all_results],
                "errors": [r["error"] for r in all_results if r["error"]],
            }

        # Prepare results for consolidation
        results_summary = ""
        for i, result in enumerate(successful_results, 1):
            query = result["query"]
            answer = result["result"].get("answer", "") if result["result"] else ""
            sources = result["result"].get("sources", []) if result["result"] else []

            results_summary += f"\n--- Query {i}: {query} ---\n"
            results_summary += f"Answer: {answer}\n"
            if sources:
                results_summary += f"Sources: {', '.join(sources[:3])}\n"

        # Try LLM-based consolidation
        try:
            consolidated_answer = await self._consolidate_with_llm(
                original_query, results_summary, successful_results
            )
        except Exception as e:
            self.logger.warning(f"LLM consolidation failed: {e}")
            consolidated_answer = self._consolidate_fallback(successful_results)

        return {
            "original_query": original_query,
            "total_searches": len(all_results),
            "successful_searches": len(successful_results),
            "consolidated_answer": consolidated_answer,
            "search_details": [
                {
                    "query": r["query"],
                    "success": r["success"],
                    "has_answer": bool(r["result"] and r["result"].get("answer")),
                    "error": r["error"],
                }
                for r in all_results
            ],
            "all_answers": [
                {
                    "query": r["query"],
                    "answer": r["result"].get("answer", "") if r["result"] else "",
                    "sources": r["result"].get("sources", []) if r["result"] else [],
                }
                for r in successful_results
            ],
        }

    async def _consolidate_with_llm(
        self,
        original_query: str,
        results_summary: str,
        successful_results: List[Dict[str, Any]],
    ) -> str:
        """Use LLM to consolidate search results"""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(
                model=config.agent_model,
                temperature=0.2,
                max_tokens=2000,
                api_key=config.google_api_key,
            )

            consolidation_content = self.consolidation_prompt.format(
                results=results_summary
            )

            messages = [
                SystemMessage(
                    content="You are an expert information synthesizer. Consolidate search results into a coherent, comprehensive summary."
                ),
                HumanMessage(content=consolidation_content),
            ]

            response = await llm.ainvoke(messages)
            return response.content.strip()

        except Exception as e:
            self.logger.error(f"LLM consolidation error: {e}")
            raise e

    def _consolidate_fallback(self, successful_results: List[Dict[str, Any]]) -> str:
        """Fallback consolidation when LLM is not available"""
        answers = []
        for result in successful_results:
            if result["result"] and result["result"].get("answer"):
                query = result["query"]
                answer = result["result"]["answer"]
                answers.append(f"From '{query}': {answer[:500]}...")

        return (
            "\n\n".join(answers[:3])
            if answers
            else "Unable to consolidate results due to processing errors."
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
                            "description": "Original search query to expand and search",
                        },
                        "expansion_depth": {
                            "type": "integer",
                            "description": "Number of query expansions to generate (1-5, default: 5)",
                            "minimum": 1,
                            "maximum": 5,
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
        }
