import { useCallback, useEffect, useRef, useState } from "react";
import {
  deletePdf,
  indexPdf,
  listPdfs,
  queryPdf,
  uploadPdf,
  type PdfItem,
  type PdfQueryResponse,
} from "../api";
import MarkdownView from "./MarkdownView";
import styles from "./PdfView.module.css";

const MAX_DOCUMENT_BYTES = 100 * 1024 * 1024;
const ACCEPTED_DOCUMENT_EXTENSIONS = [".pdf", ".txt", ".md", ".markdown", ".pptx"];
const ACCEPTED_DOCUMENT_INPUT =
  "application/pdf,text/plain,text/markdown,.pdf,.txt,.md,.markdown,.pptx";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function PdfView() {
  const [items, setItems] = useState<PdfItem[]>([]);
  const [indexingDocIds, setIndexingDocIds] = useState<Set<string>>(new Set());
  const [deletingDocIds, setDeletingDocIds] = useState<Set<string>>(new Set());
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<PdfQueryResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await listPdfs();
      setItems(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const anyIndexing = indexingDocIds.size > 0;

  const handleUploadFiles = useCallback(
    async (files: FileList | File[]) => {
      const documentFiles = Array.from(files).filter((file) => {
        const name = file.name.toLowerCase();
        return ACCEPTED_DOCUMENT_EXTENSIONS.some((ext) => name.endsWith(ext));
      });
      if (documentFiles.length === 0) {
        setError(
          `accepted file types: ${ACCEPTED_DOCUMENT_EXTENSIONS.join(", ")}`,
        );
        return;
      }
      const oversized = documentFiles.find(
        (file) => file.size > MAX_DOCUMENT_BYTES,
      );
      if (oversized) {
        setError(`${oversized.name} exceeds ${formatBytes(MAX_DOCUMENT_BYTES)}`);
        return;
      }
      setError(null);
      setUploading(true);
      try {
        for (const file of documentFiles) {
          await uploadPdf(file);
        }
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setUploading(false);
      }
    },
    [refresh],
  );

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragging(false);
      if (event.dataTransfer?.files?.length) {
        void handleUploadFiles(event.dataTransfer.files);
      }
    },
    [handleUploadFiles],
  );

  const handleIndex = useCallback(
    async (docId: string) => {
      if (anyIndexing) return;
      setError(null);
      setIndexingDocIds((prev) => new Set(prev).add(docId));
      try {
        await indexPdf(docId);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setIndexingDocIds((prev) => {
          const next = new Set(prev);
          next.delete(docId);
          return next;
        });
      }
    },
    [anyIndexing, refresh],
  );

  const handleDelete = useCallback(
    async (docId: string, filename: string) => {
      if (
        !window.confirm(
          `Delete "${filename}"? The uploaded file and its index will be removed.`,
        )
      ) {
        return;
      }
      setError(null);
      setDeletingDocIds((prev) => new Set(prev).add(docId));
      try {
        await deletePdf(docId);
        setSelectedDocId((current) => (current === docId ? null : current));
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setDeletingDocIds((prev) => {
          const next = new Set(prev);
          next.delete(docId);
          return next;
        });
      }
    },
    [refresh],
  );

  const handleAsk = useCallback(async () => {
    if (!selectedDocId || !query.trim()) return;
    setError(null);
    setAsking(true);
    setAnswer(null);
    try {
      const res = await queryPdf(selectedDocId, query.trim());
      setAnswer(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAsking(false);
    }
  }, [selectedDocId, query]);

  const selectedItem = selectedDocId
    ? items.find((it) => it.doc_id === selectedDocId) ?? null
    : null;
  const canAsk =
    !!selectedItem && selectedItem.indexed && query.trim().length > 0 && !asking;

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>Document Knowledge Base</h2>

      <div
        className={`${styles.dropzone}${dragging ? ` ${styles.dropzoneActive}` : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Upload document"
      >
        {uploading
          ? "uploading.."
          : dragging
            ? "Drop the document here"
            : "Drag & drop a document here, or click to choose"}
        <div className={styles.dropzoneSubtle}>
          PDF, TXT, MD, Markdown, or PPTX. Max 100 MB per file.
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_DOCUMENT_INPUT}
          multiple
          className={styles.hiddenInput}
          onChange={(e) => {
            if (e.target.files) {
              void handleUploadFiles(e.target.files);
              e.target.value = "";
            }
          }}
        />
      </div>

      <div className={styles.list}>
        <div className={styles.listHeader}>Uploaded documents</div>
        {items.length === 0 ? (
          <div className={styles.listEmpty}>No documents uploaded yet.</div>
        ) : (
          items.map((item) => {
            const isIndexingThis = indexingDocIds.has(item.doc_id);
            const isDeletingThis = deletingDocIds.has(item.doc_id);
            const isSelected = selectedDocId === item.doc_id;
            const toggleSelected = () =>
              setSelectedDocId((current) =>
                current === item.doc_id ? null : item.doc_id,
              );
            return (
              <div
                key={item.doc_id}
                className={`${styles.row}${isSelected ? ` ${styles.rowSelected}` : ""}`}
                onClick={toggleSelected}
              >
                <input
                  type="checkbox"
                  className={styles.rowCheckbox}
                  checked={isSelected}
                  onChange={toggleSelected}
                  onClick={(e) => e.stopPropagation()}
                  aria-label={`Select ${item.filename}`}
                />
                <div className={styles.rowFilename} title={item.filename}>
                  {item.filename}
                </div>
                <div className={styles.rowMeta}>{formatBytes(item.size_bytes)}</div>
                {item.indexed ? (
                  <div className={styles.badgeIndexed}>
                    ✓ indexed{item.page_count ? ` (${item.page_count}p)` : ""}
                  </div>
                ) : (
                  <button
                    type="button"
                    className={styles.indexBtn}
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleIndex(item.doc_id);
                    }}
                    disabled={anyIndexing || isDeletingThis}
                  >
                    {isIndexingThis || anyIndexing ? "indexing.." : "Index"}
                  </button>
                )}
                <button
                  type="button"
                  className={styles.deleteBtn}
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleDelete(item.doc_id, item.filename);
                  }}
                  disabled={isIndexingThis || isDeletingThis}
                  aria-label={`Delete ${item.filename}`}
                  title="Delete"
                >
                  {isDeletingThis ? "…" : "✕"}
                </button>
              </div>
            );
          })
        )}
      </div>

      <div className={styles.queryPanel}>
        <div className={styles.querySelected}>
          Selected document:{" "}
          <span className={styles.querySelectedStrong}>
            {selectedItem
              ? `${selectedItem.filename}${selectedItem.indexed ? "" : " (not indexed)"}`
              : "(none)"}
          </span>
        </div>
        <div className={styles.queryRow}>
          <input
            type="text"
            className={styles.queryInput}
            placeholder={
              selectedItem
                ? selectedItem.indexed
                  ? "Ask a question about this document.."
                  : "Index this document first."
                : "Select an indexed document above to ask a question."
            }
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && canAsk) {
                void handleAsk();
              }
            }}
            disabled={!selectedItem || !selectedItem.indexed || asking}
          />
          <button
            type="button"
            className={styles.askBtn}
            onClick={() => void handleAsk()}
            disabled={!canAsk}
          >
            {asking ? "asking.." : "Ask"}
          </button>
        </div>

        {answer && (
          <div className={styles.answerBlock}>
            <div className={styles.answerLabel}>Answer</div>
            <div className={styles.answerText}>
              <MarkdownView content={answer.answer} />
            </div>
            {answer.citations.length > 0 && (
              <>
                <div className={styles.answerLabel}>Citations</div>
                <div className={styles.citations}>
                  {answer.citations.map((c, idx) => (
                    <div key={`${c.node_id}-${idx}`} className={styles.citation}>
                      <div className={styles.citationHead}>
                        {c.node_id} · pages {c.page_range[0]}-{c.page_range[1]}
                      </div>
                      {c.snippet}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {error && <div className={styles.errorText}>{error}</div>}
    </div>
  );
}
