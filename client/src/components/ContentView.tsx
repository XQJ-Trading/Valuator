import { useCallback, useEffect, useState } from "react";
import {
  fetchFile,
  saveFile,
  type DataSource,
  type FileResponse,
} from "../api";
import MarkdownView from "./MarkdownView";
import JsonMarkdownStyleView from "./JsonMarkdownStyleView";
import JsonTreeView from "./JsonTreeView";
import RawTextView from "./RawTextView";
import RenderEverythingView from "./RenderEverythingView";
import { type JsonExt } from "./jsonParse";
import styles from "./ContentView.module.css";

type MdViewMode = "preview" | "render-everything" | "raw";
type JsonViewMode = "preview" | "markdown-style" | "render-everything" | "raw";

function MarkdownFilePanel({
  dataSource,
  filePath,
  content,
  onFileUpdated,
}: {
  dataSource: DataSource;
  filePath: string;
  content: string;
  onFileUpdated: (f: FileResponse) => void;
}) {
  const [mdMode, setMdMode] = useState<MdViewMode>("preview");
  const [draft, setDraft] = useState(content);
  const [savedContent, setSavedContent] = useState(content);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(content);
    setSavedContent(content);
  }, [content]);

  const dirty = draft !== savedContent;

  const persist = useCallback(async () => {
    if (draft === savedContent || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await saveFile(filePath, dataSource, draft);
      setSavedContent(updated.content);
      onFileUpdated(updated);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [draft, savedContent, saving, filePath, dataSource, onFileUpdated]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        void persist();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [persist]);

  return (
    <div className={styles.mdRoot}>
      <div className={styles.toolbar}>
        <div className={styles.toolbarStatus} aria-live="polite">
          {saveError ? (
            <span className={styles.toolbarError} title={saveError}>
              {saveError}
            </span>
          ) : saving ? (
            <span>Saving…</span>
          ) : dirty ? (
            <>
              <span
                className={styles.toolbarDirtyDot}
                aria-hidden
              />
              <span aria-label="Unsaved changes">Modified</span>
            </>
          ) : null}
        </div>
        <div className={styles.segment} role="tablist" aria-label="Markdown view">
          <button
            type="button"
            role="tab"
            aria-selected={mdMode === "preview"}
            className={
              mdMode === "preview"
                ? `${styles.segmentBtn} ${styles.segmentBtnActive}`
                : styles.segmentBtn
            }
            onClick={() => setMdMode("preview")}
          >
            Preview
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mdMode === "render-everything"}
            className={
              mdMode === "render-everything"
                ? `${styles.segmentBtn} ${styles.segmentBtnActive}`
                : styles.segmentBtn
            }
            onClick={() => setMdMode("render-everything")}
          >
            Render Everything
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mdMode === "raw"}
            className={
              mdMode === "raw"
                ? `${styles.segmentBtn} ${styles.segmentBtnActive}`
                : styles.segmentBtn
            }
            onClick={() => setMdMode("raw")}
          >
            Markdown
          </button>
        </div>
      </div>
      <div className={styles.mdBody}>
        {mdMode === "preview" ? (
          <MarkdownView content={draft} />
        ) : mdMode === "render-everything" ? (
          <RenderEverythingView content={draft} ext=".md" />
        ) : (
          <RawTextView
            value={draft}
            onChange={setDraft}
            readOnly={saving}
            ariaLabel={`Markdown source, ${filePath}`}
          />
        )}
      </div>
    </div>
  );
}

function JsonFilePanel({
  dataSource,
  filePath,
  content,
  ext,
  onFileUpdated,
}: {
  dataSource: DataSource;
  filePath: string;
  content: string;
  ext: JsonExt;
  onFileUpdated: (f: FileResponse) => void;
}) {
  const [jsonMode, setJsonMode] = useState<JsonViewMode>("preview");
  const [draft, setDraft] = useState(content);
  const [savedContent, setSavedContent] = useState(content);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(content);
    setSavedContent(content);
  }, [content]);

  const dirty = draft !== savedContent;

  const persist = useCallback(async () => {
    if (draft === savedContent || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await saveFile(filePath, dataSource, draft);
      setSavedContent(updated.content);
      onFileUpdated(updated);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [draft, savedContent, saving, filePath, dataSource, onFileUpdated]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        void persist();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [persist]);

  return (
    <div className={styles.mdRoot}>
      <div className={styles.toolbar}>
        <div className={styles.toolbarStatus} aria-live="polite">
          {saveError ? (
            <span className={styles.toolbarError} title={saveError}>
              {saveError}
            </span>
          ) : saving ? (
            <span>Saving…</span>
          ) : dirty ? (
            <>
              <span className={styles.toolbarDirtyDot} aria-hidden />
              <span aria-label="Unsaved changes">Modified</span>
            </>
          ) : null}
        </div>
        <div className={styles.segment} role="tablist" aria-label="JSON view">
          <button
            type="button"
            role="tab"
            aria-selected={jsonMode === "preview"}
            className={
              jsonMode === "preview"
                ? `${styles.segmentBtn} ${styles.segmentBtnActive}`
                : styles.segmentBtn
            }
            onClick={() => setJsonMode("preview")}
          >
            Preview
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={jsonMode === "markdown-style"}
            className={
              jsonMode === "markdown-style"
                ? `${styles.segmentBtn} ${styles.segmentBtnActive}`
                : styles.segmentBtn
            }
            onClick={() => setJsonMode("markdown-style")}
          >
            Markdown-style
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={jsonMode === "render-everything"}
            className={
              jsonMode === "render-everything"
                ? `${styles.segmentBtn} ${styles.segmentBtnActive}`
                : styles.segmentBtn
            }
            onClick={() => setJsonMode("render-everything")}
          >
            Render Everything
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={jsonMode === "raw"}
            className={
              jsonMode === "raw"
                ? `${styles.segmentBtn} ${styles.segmentBtnActive}`
                : styles.segmentBtn
            }
            onClick={() => setJsonMode("raw")}
          >
            Raw
          </button>
        </div>
      </div>
      <div className={styles.mdBody}>
        {jsonMode === "preview" ? (
          <JsonTreeView content={draft} ext={ext} />
        ) : jsonMode === "markdown-style" ? (
          <JsonMarkdownStyleView content={draft} ext={ext} />
        ) : jsonMode === "render-everything" ? (
          <RenderEverythingView content={draft} ext={ext} />
        ) : (
          <RawTextView
            value={draft}
            onChange={setDraft}
            readOnly={saving}
            ariaLabel={`JSON source, ${filePath}`}
          />
        )}
      </div>
    </div>
  );
}

export default function ContentView({
  dataSource,
  filePath,
}: {
  dataSource: DataSource;
  filePath: string | null;
}) {
  const [file, setFile] = useState<FileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* eslint-disable react-hooks/set-state-in-effect -- sync loading/error from async fetch */
  useEffect(() => {
    if (!filePath) return;
    setLoading(true);
    setError(null);
    fetchFile(filePath, dataSource)
      .then(setFile)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filePath, dataSource]);
  /* eslint-enable react-hooks/set-state-in-effect */

  if (!filePath) {
    return <div className="content-empty">Select a file to view</div>;
  }
  if (loading) return <div className="status-msg">Loading…</div>;
  if (error) return <div className="error-msg">Error: {error}</div>;
  if (!file) return null;

  const ext = file.ext.toLowerCase();

  if (ext === ".md") {
    return (
      <MarkdownFilePanel
        key={filePath}
        dataSource={dataSource}
        filePath={filePath}
        content={file.content}
        onFileUpdated={setFile}
      />
    );
  }

  if (ext === ".json" || ext === ".jsonl") {
    return (
      <JsonFilePanel
        key={filePath}
        dataSource={dataSource}
        filePath={filePath}
        content={file.content}
        ext={ext}
        onFileUpdated={setFile}
      />
    );
  }

  return (
    <div className="content-area">
      <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {file.content}
      </pre>
    </div>
  );
}
