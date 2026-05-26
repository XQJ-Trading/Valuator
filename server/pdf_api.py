from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

from valuator.documents import (
    Answer,
    DocumentLoader,
    IndexStore,
    IndexedDocument,
    AnswerGenerator,
    PageIndexer,
    RawDocument,
    TOCDetector,
    TreeRetriever,
    document_hash,
    remove_detected_toc_from_pages,
    transform_toc,
)
from valuator.models.factory import create_llm_client
from valuator.utils.time_utils import kst_isoformat

from scripts.run_page_index_poc import PageIndexTraceWriter

router = APIRouter(prefix="/api/pdf", tags=["pdf"])

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data" / "page_index"
UPLOAD_ROOT = DATA_ROOT / "uploads"
DB_PATH = ROOT / "data" / "page_index.db"

PDF_MIME = "application/pdf"
MAX_PDF_BYTES = 50 * 1024 * 1024


class PdfItem(BaseModel):
    doc_id: str
    filename: str
    size_bytes: int
    indexed: bool
    doc_hash: str | None = None
    page_count: int | None = None


class PdfListResponse(BaseModel):
    items: list[PdfItem] = Field(default_factory=list)


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    size_bytes: int
    indexed: bool


class IndexResponse(BaseModel):
    doc_id: str
    doc_hash: str
    page_count: int


class DeleteResponse(BaseModel):
    doc_id: str
    deleted_index_rows: int


class QueryRequest(BaseModel):
    query: str


class CitationResponse(BaseModel):
    node_id: str
    page_range: list[int]
    snippet: str


class RetrievedNodeSummary(BaseModel):
    node_id: str
    title: str
    page_range: list[int]
    page_count: int


class QueryResponse(BaseModel):
    doc_id: str
    doc_hash: str
    query: str
    answer: str
    citations: list[CitationResponse]
    used_node_ids: list[str]
    retrieved_nodes: list[RetrievedNodeSummary]
    reasoning: str


def _safe_doc_id_stem(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip())
    return normalized.strip("-._") or "document"


def _unique_doc_id(stem: str) -> str:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    candidate = stem
    suffix = 2
    while (UPLOAD_ROOT / f"{candidate}.pdf").exists():
        candidate = f"{stem}-{suffix}"
        suffix += 1
    return candidate


def _upload_path(doc_id: str) -> Path:
    return UPLOAD_ROOT / f"{doc_id}.pdf"


def _doc_dir(doc_id: str) -> Path:
    return DATA_ROOT / doc_id


def _store() -> IndexStore:
    return IndexStore(DB_PATH)


def _validate_pdf_upload(file: UploadFile) -> None:
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only .pdf files are accepted")
    if file.content_type and file.content_type != PDF_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"unexpected content-type: {file.content_type}",
        )


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile) -> UploadResponse:
    _validate_pdf_upload(file)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {MAX_PDF_BYTES} bytes",
        )
    stem = _safe_doc_id_stem(Path(file.filename or "document.pdf").stem)
    doc_id = _unique_doc_id(stem)
    target = _upload_path(doc_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    store = _store()
    indexed_doc = store.get_by_doc_id(doc_id)
    return UploadResponse(
        doc_id=doc_id,
        filename=file.filename or f"{doc_id}.pdf",
        size_bytes=len(raw),
        indexed=indexed_doc is not None,
    )


@router.get("", response_model=PdfListResponse)
async def list_pdfs() -> PdfListResponse:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    store = _store()
    items: list[PdfItem] = []
    for path in sorted(UPLOAD_ROOT.glob("*.pdf")):
        doc_id = path.stem
        indexed_doc = store.get_by_doc_id(doc_id)
        items.append(
            PdfItem(
                doc_id=doc_id,
                filename=path.name,
                size_bytes=path.stat().st_size,
                indexed=indexed_doc is not None,
                doc_hash=indexed_doc.doc_hash if indexed_doc else None,
                page_count=indexed_doc.page_count if indexed_doc else None,
            )
        )
    return PdfListResponse(items=items)


async def _build_index(doc_id: str) -> IndexedDocument:
    upload_path = _upload_path(doc_id)
    if not upload_path.exists():
        raise HTTPException(status_code=404, detail=f"pdf not found: {doc_id}")

    raw_bytes = upload_path.read_bytes()
    raw_document = RawDocument(
        doc_id=doc_id,
        source=str(upload_path),
        raw_bytes_or_text=raw_bytes,
        mime=PDF_MIME,
    )
    loader = DocumentLoader.pdf()
    pages = loader.pages_from_raw(raw_document)
    doc_hash = document_hash(raw_document)

    doc_dir = _doc_dir(doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    usage_path = doc_dir / "llm_usage.jsonl"
    llm_calls_path = doc_dir / "llm_calls.jsonl"
    trace_writer = PageIndexTraceWriter(
        usage_path=usage_path,
        llm_calls_path=llm_calls_path,
        session_started_at=kst_isoformat(),
    )
    client = create_llm_client(usage_writer=trace_writer)

    toc_detector = TOCDetector(client)
    detected_toc = await toc_detector.detect(pages)
    index_pages = remove_detected_toc_from_pages(pages, detected_toc)
    toc_text_removed_pages = sum(
        1 for page in index_pages if page.source_locator.get("toc_removed")
    )
    outlines, toc_transform_metrics = await transform_toc(
        client,
        detected_toc,
        index_pages,
    )
    indexer = PageIndexer(client)
    tree = await indexer.build_tree(
        index_pages,
        detected_toc=detected_toc,
        outlines=outlines,
    )
    trace_writer.append_total()

    indexed = IndexedDocument(
        doc_id=doc_id,
        doc_hash=doc_hash,
        page_count=len(index_pages),
        tree=tree,
        metadata={
            "input_file": str(upload_path),
            "source": raw_document.source,
            "mime": raw_document.mime,
            "raw_page_count": len(pages),
            "toc_text_removed_pages": toc_text_removed_pages,
            **loader.metadata(),
            "detected_toc_pages": detected_toc.toc_pages if detected_toc else [],
            "toc_detection_metrics": asdict(toc_detector.metrics),
            "toc_transform_metrics": asdict(toc_transform_metrics),
            "toc_entry_count": toc_transform_metrics.entry_count,
            "toc_has_page_numbers": toc_transform_metrics.has_page_numbers,
            "tree_build_route": indexer.metrics.tree_build_route,
            "metrics": asdict(indexer.metrics),
        },
    )
    store = _store()
    store.record(indexed, index_pages)

    tree_path = doc_dir / "tree.json"
    tree_path.write_text(
        json.dumps(
            indexed.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return indexed


@router.post("/{doc_id}/index", response_model=IndexResponse)
async def index_pdf(doc_id: str) -> IndexResponse:
    indexed = await _build_index(doc_id)
    return IndexResponse(
        doc_id=indexed.doc_id,
        doc_hash=indexed.doc_hash,
        page_count=indexed.page_count,
    )


@router.delete("/{doc_id}", response_model=DeleteResponse)
async def delete_pdf(doc_id: str) -> DeleteResponse:
    upload_path = _upload_path(doc_id)
    if not upload_path.exists():
        raise HTTPException(status_code=404, detail=f"pdf not found: {doc_id}")
    upload_path.unlink()
    doc_dir = _doc_dir(doc_id)
    if doc_dir.exists():
        shutil.rmtree(doc_dir)
    deleted_rows = _store().delete_by_doc_id(doc_id)
    return DeleteResponse(doc_id=doc_id, deleted_index_rows=deleted_rows)


@router.post("/{doc_id}/query", response_model=QueryResponse)
async def query_pdf(doc_id: str, body: QueryRequest) -> QueryResponse:
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    store = _store()
    document = store.get_by_doc_id(doc_id)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"document not indexed: {doc_id}",
        )

    doc_dir = _doc_dir(doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    usage_path = doc_dir / "query_llm_usage.jsonl"
    llm_calls_path = doc_dir / "query_llm_calls.jsonl"
    trace_writer = PageIndexTraceWriter(
        usage_path=usage_path,
        llm_calls_path=llm_calls_path,
        session_started_at=kst_isoformat(),
    )
    retriever_client = create_llm_client(usage_writer=trace_writer)
    generator_client = create_llm_client(
        model="gemini-3.1-flash-lite",
        usage_writer=trace_writer,
    )

    retrieval = await TreeRetriever(retriever_client).retrieve(
        store=store,
        document=document,
        sub_query=query,
    )
    answer: Answer = await AnswerGenerator(generator_client).generate(retrieval=retrieval)
    trace_writer.append_total()

    return QueryResponse(
        doc_id=answer.doc_id,
        doc_hash=answer.doc_hash,
        query=answer.query,
        answer=answer.answer,
        citations=[
            CitationResponse(
                node_id=c.node_id,
                page_range=list(c.page_range),
                snippet=c.snippet,
            )
            for c in answer.citations
        ],
        used_node_ids=list(answer.used_node_ids),
        retrieved_nodes=[
            RetrievedNodeSummary(
                node_id=node.node_id,
                title=node.title,
                page_range=list(node.page_range),
                page_count=len(node.pages),
            )
            for node in retrieval.selected_nodes
        ],
        reasoning=retrieval.selection.reasoning,
    )
