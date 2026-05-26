from __future__ import annotations

from valuator.models.protocol import LlmClient

from .types import Answer, RetrievalResult, RetrievedNode

ANSWER_GENERATOR_SYSTEM_PROMPT = (
    "Return JSON only. Use ONLY the provided excerpts. "
    "The answer field renders as Markdown.\n"
    "\n"
    "1. Cite every claim with a verbatim snippet. Arithmetic over cited "
    "numbers is allowed (sums, ratios, percentages, growth rates). "
    "Qualifiers (scope, magnitude, frequency, approximation) and "
    "causal/comparative bridges not in the snippets are not.\n"
    "\n"
    "2. Be complete. Use all materially relevant cited numbers. Present "
    "multi-period and multi-entity data on every axis the excerpts cover; "
    "do not collapse a time series to one period.\n"
    "\n"
    "3. If parts of the question are not covered, name them and answer only "
    "the covered parts. Empty citations only when no part is supported.\n"
    "\n"
    "4. Choose form by content: tables for cross-entity and/or cross-period "
    "comparisons, prose for narrative. Do not bullet single facts."
)

ANSWER_PROMPT_TEMPLATE = (
    "Document id: {doc_id}\n\n"
    "Question:\n{query}\n\n"
    "Document excerpts (one block per retrieved node):\n{nodes_block}\n\n"
    "Cite using node_id values from the excerpts above."
)

ANSWER_RESPONSE_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["doc_id", "answer", "citations", "used_node_ids"],
    "properties": {
        "doc_id": {"type": "string"},
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["node_id", "page_range", "snippet"],
                "properties": {
                    "node_id": {"type": "string"},
                    "page_range": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "snippet": {"type": "string"},
                },
            },
        },
        "used_node_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


class AnswerGenerator:
    def __init__(self, client: LlmClient) -> None:
        self.client = client

    async def generate(
        self,
        *,
        retrieval: RetrievalResult,
        trace_method: str = "page_index.answer",
    ) -> Answer:
        nodes_block = _format_nodes_block(retrieval.selected_nodes)
        data = await self.client.generate_json(
            prompt=ANSWER_PROMPT_TEMPLATE.format(
                doc_id=retrieval.doc_id,
                query=retrieval.query,
                nodes_block=nodes_block,
            ),
            system_prompt=ANSWER_GENERATOR_SYSTEM_PROMPT,
            response_json_schema=ANSWER_RESPONSE_JSON_SCHEMA,
            trace_method=trace_method,
        )
        answer = Answer.model_validate(
            {
                "doc_id": retrieval.doc_id,
                "doc_hash": retrieval.doc_hash,
                "query": retrieval.query,
                "answer": data["answer"],
                "citations": data["citations"],
                "used_node_ids": data["used_node_ids"],
            }
        )
        known_ids = {node.node_id for node in retrieval.selected_nodes}
        unknown_citation_ids = sorted(
            {c.node_id for c in answer.citations} - known_ids
        )
        if unknown_citation_ids:
            raise ValueError(
                f"answer cites unknown node ids: {unknown_citation_ids}"
            )
        unknown_used_ids = sorted(set(answer.used_node_ids) - known_ids)
        if unknown_used_ids:
            raise ValueError(
                f"answer used_node_ids contain unknown ids: {unknown_used_ids}"
            )
        return answer


def _format_nodes_block(nodes: list[RetrievedNode]) -> str:
    if not nodes:
        return "(no excerpts retrieved)"
    blocks: list[str] = []
    for node in nodes:
        header = (
            f"--- node_id: {node.node_id} | title: {node.title} | "
            f"pages: {node.page_range[0]}-{node.page_range[1]} ---"
        )
        page_texts = "\n\n".join(
            f"[page {page.ordinal}]\n{page.text}" for page in node.pages
        )
        blocks.append(f"{header}\n{page_texts}")
    return "\n\n".join(blocks)
