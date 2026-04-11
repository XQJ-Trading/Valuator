import { useCallback, useEffect, useState, type ReactNode } from "react";
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
type FilePanelMode = MdViewMode | JsonViewMode;

function TabBar({
  openTabs,
  activeTabPath,
  onSelectTab,
  onCloseTab,
}: {
  openTabs: string[];
  activeTabPath: string | null;
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
}) {
  return (
    <div className={styles.tabBar} role="tablist">
      {openTabs.map((path) => {
        const name = path.split("/").at(-1) ?? path;
        const isActive = path === activeTabPath;
        return (
          <div
            key={path}
            role="tab"
            aria-selected={isActive}
            className={
              isActive
                ? `${styles.tabItem} ${styles.tabItemActive}`
                : styles.tabItem
            }
            onClick={() => onSelectTab(path)}
          >
            <span className={styles.tabLabel} title={path}>
              {name}
            </span>
            <button
              type="button"
              className={styles.tabClose}
              aria-label={`Close ${name}`}
              onClick={(e) => {
                e.stopPropagation();
                onCloseTab(path);
              }}
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}

function EditableFilePanel({
  dataSource,
  filePath,
  content,
  onFileUpdated,
  activeMode,
  onModeChange,
  modes,
  ariaLabel,
  children,
}: {
  dataSource: DataSource;
  filePath: string;
  content: string;
  onFileUpdated: (f: FileResponse) => void;
  activeMode: FilePanelMode;
  onModeChange: (mode: FilePanelMode) => void;
  modes: Array<{ value: FilePanelMode; label: string }>;
  ariaLabel: string;
  children: (args: {
    draft: string;
    saving: boolean;
    setDraft: (value: string) => void;
  }) => ReactNode;
}) {
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
        <div className={styles.segment} role="tablist" aria-label={ariaLabel}>
          {modes.map((mode) => (
            <button
              key={mode.value}
              type="button"
              role="tab"
              aria-selected={activeMode === mode.value}
              className={
                activeMode === mode.value
                  ? `${styles.segmentBtn} ${styles.segmentBtnActive}`
                  : styles.segmentBtn
              }
              onClick={() => onModeChange(mode.value)}
            >
              {mode.label}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.mdBody}>{children({ draft, saving, setDraft })}</div>
    </div>
  );
}

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

  return (
    <EditableFilePanel
      dataSource={dataSource}
      filePath={filePath}
      content={content}
      onFileUpdated={onFileUpdated}
      activeMode={mdMode}
      onModeChange={(mode) => setMdMode(mode as MdViewMode)}
      modes={[
        { value: "preview", label: "Preview" },
        { value: "render-everything", label: "Render Everything" },
        { value: "raw", label: "Markdown" },
      ]}
      ariaLabel="Markdown view"
    >
      {({ draft, saving, setDraft }) =>
        mdMode === "preview" ? (
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
        )
      }
    </EditableFilePanel>
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

  return (
    <EditableFilePanel
      dataSource={dataSource}
      filePath={filePath}
      content={content}
      onFileUpdated={onFileUpdated}
      activeMode={jsonMode}
      onModeChange={(mode) => setJsonMode(mode as JsonViewMode)}
      modes={[
        { value: "preview", label: "Preview" },
        { value: "markdown-style", label: "Markdown-style" },
        { value: "render-everything", label: "Render Everything" },
        { value: "raw", label: "Raw" },
      ]}
      ariaLabel="JSON view"
    >
      {({ draft, saving, setDraft }) =>
        jsonMode === "preview" ? (
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
        )
      }
    </EditableFilePanel>
  );
}

export default function ContentView({
  dataSource,
  filePath,
}: {
  dataSource: DataSource;
  filePath: string | null;
}) {
  const [openTabs, setOpenTabs] = useState<string[]>([]);
  const [activeTabPath, setActiveTabPath] = useState<string | null>(null);
  const [file, setFile] = useState<FileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync filePath prop changes to tabs
  useEffect(() => {
    if (!filePath) return;
    setOpenTabs((prev) =>
      prev.includes(filePath) ? prev : [...prev, filePath]
    );
    setActiveTabPath(filePath);
  }, [filePath]);

  // Fetch file content based on active tab
  /* eslint-disable react-hooks/set-state-in-effect -- sync loading/error from async fetch */
  useEffect(() => {
    if (!activeTabPath) return;
    setLoading(true);
    setError(null);
    fetchFile(activeTabPath, dataSource)
      .then(setFile)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [activeTabPath, dataSource]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const closeTab = (path: string) => {
    setOpenTabs((prev) => {
      const next = prev.filter((p) => p !== path);
      if (activeTabPath === path) {
        const idx = prev.indexOf(path);
        setActiveTabPath(next[idx] ?? next[idx - 1] ?? null);
      }
      return next;
    });
  };

  if (openTabs.length === 0) {
    return <div className="content-empty">Select a file to view</div>;
  }

  if (!activeTabPath) {
    return <div className="content-empty">Select a file to view</div>;
  }

  if (loading) return <div className="status-msg">Loading…</div>;
  if (error) return <div className="error-msg">Error: {error}</div>;
  if (!file) return null;

  const ext = file.ext.toLowerCase();

  const renderContent = () => {
    if (ext === ".md") {
      return (
        <MarkdownFilePanel
          key={activeTabPath}
          dataSource={dataSource}
          filePath={activeTabPath}
          content={file.content}
          onFileUpdated={setFile}
        />
      );
    }

    if (ext === ".json" || ext === ".jsonl") {
      return (
        <JsonFilePanel
          key={activeTabPath}
          dataSource={dataSource}
          filePath={activeTabPath}
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
  };

  return (
    <div className={styles.tabViewRoot}>
      <TabBar
        openTabs={openTabs}
        activeTabPath={activeTabPath}
        onSelectTab={setActiveTabPath}
        onCloseTab={closeTab}
      />
      {renderContent()}
    </div>
  );
}
