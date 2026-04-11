import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import {
  fetchFile,
  saveFile,
  type DataSource,
  type FileResponse,
} from "../api";
import { useToast } from "../ToastContext";
import MarkdownView from "./MarkdownView";
import JsonMarkdownStyleView from "./JsonMarkdownStyleView";
import JsonTreeView from "./JsonTreeView";
import RawTextView from "./RawTextView";
import RenderEverythingView from "./RenderEverythingView";
import { type JsonExt } from "./jsonParse";
import styles from "./ContentView.module.css";

type MdViewMode = "preview" | "render-everything" | "raw";
type JsonViewMode = "preview" | "markdown-style" | "render-everything" | "raw";

type PanelHandle = { persist: () => Promise<void>; dirty: boolean };

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

const MarkdownFilePanel = forwardRef<
  PanelHandle,
  {
    dataSource: DataSource;
    filePath: string;
    content: string;
    onFileUpdated: (f: FileResponse) => void;
  }
>(function MarkdownFilePanel(
  { dataSource, filePath, content, onFileUpdated },
  ref,
) {
  const [mdMode, setMdMode] = useState<MdViewMode>("preview");
  const [draft, setDraft] = useState(content);
  const [savedContent, setSavedContent] = useState(content);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const localKey = `valuator.draft.${dataSource}.${filePath}`;

  useEffect(() => {
    setDraft(content);
    setSavedContent(content);
  }, [content]);

  // Restore draft from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(localKey);
    if (stored !== null && stored !== content) setDraft(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = draft !== savedContent;

  const persist = useCallback(async () => {
    if (draft === savedContent || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await saveFile(filePath, dataSource, draft);
      setSavedContent(updated.content);
      localStorage.removeItem(localKey);
      onFileUpdated(updated);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [draft, savedContent, saving, filePath, dataSource, localKey, onFileUpdated]);

  // 3s debounce save to localStorage
  useEffect(() => {
    const id = setTimeout(() => localStorage.setItem(localKey, draft), 3000);
    return () => clearTimeout(id);
  }, [draft, localKey]);

  // Save to localStorage immediately on unmount (captures last edits when switching tabs)
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const savedContentRef = useRef(savedContent);
  savedContentRef.current = savedContent;
  useEffect(() => {
    return () => {
      if (draftRef.current !== savedContentRef.current) {
        localStorage.setItem(localKey, draftRef.current);
      }
    };
  }, [localKey]);

  // 30s API auto-save interval
  useEffect(() => {
    const id = setInterval(() => void persist(), 30_000);
    return () => clearInterval(id);
  }, [persist]);

  useImperativeHandle(ref, () => ({ persist, dirty }), [persist, dirty]);

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
});

const JsonFilePanel = forwardRef<
  PanelHandle,
  {
    dataSource: DataSource;
    filePath: string;
    content: string;
    ext: JsonExt;
    onFileUpdated: (f: FileResponse) => void;
  }
>(function JsonFilePanel(
  { dataSource, filePath, content, ext, onFileUpdated },
  ref,
) {
  const [jsonMode, setJsonMode] = useState<JsonViewMode>("preview");
  const [draft, setDraft] = useState(content);
  const [savedContent, setSavedContent] = useState(content);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const localKey = `valuator.draft.${dataSource}.${filePath}`;

  useEffect(() => {
    setDraft(content);
    setSavedContent(content);
  }, [content]);

  // Restore draft from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(localKey);
    if (stored !== null && stored !== content) setDraft(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = draft !== savedContent;

  const persist = useCallback(async () => {
    if (draft === savedContent || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await saveFile(filePath, dataSource, draft);
      setSavedContent(updated.content);
      localStorage.removeItem(localKey);
      onFileUpdated(updated);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [draft, savedContent, saving, filePath, dataSource, localKey, onFileUpdated]);

  // 3s debounce save to localStorage
  useEffect(() => {
    const id = setTimeout(() => localStorage.setItem(localKey, draft), 3000);
    return () => clearTimeout(id);
  }, [draft, localKey]);

  // Save to localStorage immediately on unmount (captures last edits when switching tabs)
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const savedContentRef = useRef(savedContent);
  savedContentRef.current = savedContent;
  useEffect(() => {
    return () => {
      if (draftRef.current !== savedContentRef.current) {
        localStorage.setItem(localKey, draftRef.current);
      }
    };
  }, [localKey]);

  // 30s API auto-save interval
  useEffect(() => {
    const id = setInterval(() => void persist(), 30_000);
    return () => clearInterval(id);
  }, [persist]);

  useImperativeHandle(ref, () => ({ persist, dirty }), [persist, dirty]);

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
});

export default function ContentView({
  dataSource,
  filePath,
}: {
  dataSource: DataSource;
  filePath: string | null;
}) {
  const [tabsDataSource, setTabsDataSource] = useState<DataSource>(dataSource);
  const [openTabs, setOpenTabs] = useState<string[]>([]);
  const [activeTabPath, setActiveTabPath] = useState<string | null>(null);
  const [file, setFile] = useState<FileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const pushToast = useToast();
  const activePanelRef = useRef<PanelHandle | null>(null);

  // dataSource가 바뀌면 이전 source의 탭 상태를 render 중에 즉시 초기화한다.
  // effect 안에서 하면 이전 activeTabPath로 fetch가 먼저 실행된 뒤에야 리셋되므로 render 중 처리.
  if (tabsDataSource !== dataSource) {
    setTabsDataSource(dataSource);
    setOpenTabs([]);
    setActiveTabPath(null);
    setFile(null);
  }

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
    fetchFile(activeTabPath, dataSource)
      .then(setFile)
      .catch((e: Error) =>
        pushToast({ type: "warning", title: "File not found", message: e.message })
      )
      .finally(() => setLoading(false));
  }, [activeTabPath, dataSource]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const closeTab = useCallback(async (path: string) => {
    // Active panel: save via mounted component's persist
    if (path === activeTabPath && activePanelRef.current?.dirty) {
      await activePanelRef.current.persist();
    } else {
      // Inactive tab: check localStorage for unsaved draft
      const localKey = `valuator.draft.${dataSource}.${path}`;
      const stored = localStorage.getItem(localKey);
      if (stored !== null) {
        try {
          await saveFile(path, dataSource, stored);
          localStorage.removeItem(localKey);
        } catch {
          // Don't block tab close on save failure
        }
      }
    }
    setOpenTabs((prev) => {
      const next = prev.filter((p) => p !== path);
      if (activeTabPath === path) {
        const idx = prev.indexOf(path);
        setActiveTabPath(next[idx] ?? next[idx - 1] ?? null);
      }
      return next;
    });
  }, [activeTabPath, dataSource]);

  if (openTabs.length === 0) {
    return <div className="content-empty">Select a file to view</div>;
  }

  if (!activeTabPath) {
    return <div className="content-empty">Select a file to view</div>;
  }

  if (loading) return <div className="status-msg">Loading…</div>;
  if (!file) return null;

  const ext = file.ext.toLowerCase();

  const renderContent = () => {
    if (ext === ".md") {
      return (
        <MarkdownFilePanel
          key={activeTabPath}
          ref={activePanelRef}
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
          ref={activePanelRef}
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
