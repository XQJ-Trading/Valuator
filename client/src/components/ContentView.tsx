import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
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
import ConfirmCloseDialog from "./ConfirmCloseDialog";
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
  dirtyPaths,
}: {
  openTabs: string[];
  activeTabPath: string | null;
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
  dirtyPaths: Set<string>;
}) {
  return (
    <div className={styles.tabBar} role="tablist">
      {openTabs.map((path) => {
        const name = path.split("/").at(-1) ?? path;
        const isActive = path === activeTabPath;
        const isDirty = dirtyPaths.has(path);
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
              {isDirty ? `● ${name}` : name}
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

type EditableFilePanelProps = {
  draft: string;
  onDraftChange: (value: string) => void;
  onSave: () => void;
  saving: boolean;
  saveError: string | null;
  dirty: boolean;
  activeMode: FilePanelMode;
  onModeChange: (mode: FilePanelMode) => void;
  modes: Array<{ value: FilePanelMode; label: string }>;
  ariaLabel: string;
  mobileLayout?: boolean;
  children: (args: {
    draft: string;
    saving: boolean;
    setDraft: (value: string) => void;
  }) => ReactNode;
};

function EditableFilePanel({
  draft,
  onDraftChange,
  onSave,
  saving,
  saveError,
  dirty,
  activeMode,
  onModeChange,
  modes,
  ariaLabel,
  mobileLayout,
  children,
}: EditableFilePanelProps) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key === "s") {
        e.preventDefault();
        onSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onSave]);

  const rootCls = mobileLayout ? `${styles.mdRoot} ${styles.mdRootMobile}` : styles.mdRoot;
  const bodyCls = mobileLayout ? `${styles.mdBody} ${styles.mdBodyMobile}` : styles.mdBody;
  const saveDisabled = !dirty || saving;

  return (
    <div className={rootCls}>
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
        <div className={styles.toolbarActions}>
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
          <button
            type="button"
            className={styles.saveBtn}
            onClick={onSave}
            disabled={saveDisabled}
            aria-label="Save file"
            title={saveDisabled ? "변경사항 없음" : "저장 (Ctrl+S)"}
          >
            저장
          </button>
        </div>
      </div>
      <div className={bodyCls}>{children({ draft, saving, setDraft: onDraftChange })}</div>
    </div>
  );
}

type FilePanelSharedProps = {
  filePath: string;
  draft: string;
  onDraftChange: (value: string) => void;
  onSave: () => void;
  saving: boolean;
  saveError: string | null;
  dirty: boolean;
  mobileLayout?: boolean;
};

function MarkdownFilePanel(props: FilePanelSharedProps) {
  const [mdMode, setMdMode] = useState<MdViewMode>("preview");
  const { filePath, ...panelProps } = props;

  return (
    <EditableFilePanel
      {...panelProps}
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

function JsonFilePanel(props: FilePanelSharedProps & { ext: JsonExt }) {
  const [jsonMode, setJsonMode] = useState<JsonViewMode>("preview");
  const { ext, filePath, ...panelProps } = props;

  return (
    <EditableFilePanel
      {...panelProps}
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
  mobileLayout,
}: {
  dataSource: DataSource;
  filePath: string | null;
  mobileLayout?: boolean;
}) {
  const [tabsDataSource, setTabsDataSource] = useState<DataSource>(dataSource);
  const [openTabs, setOpenTabs] = useState<string[]>([]);
  const [activeTabPath, setActiveTabPath] = useState<string | null>(null);
  const [file, setFile] = useState<FileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [pendingClose, setPendingClose] = useState<string | null>(null);
  const pushToast = useToast();

  // dataSource가 바뀌면 이전 source의 탭/draft 상태를 render 중에 즉시 초기화한다.
  if (tabsDataSource !== dataSource) {
    setTabsDataSource(dataSource);
    setOpenTabs([]);
    setActiveTabPath(null);
    setFile(null);
    setDrafts({});
    setSaving(false);
    setSaveError(null);
    setPendingClose(null);
  }

  useEffect(() => {
    if (!filePath) return;
    setOpenTabs((prev) =>
      prev.includes(filePath) ? prev : [...prev, filePath]
    );
    setActiveTabPath(filePath);
  }, [filePath]);

  useEffect(() => {
    if (!activeTabPath) return;
    setLoading(true);
    setSaveError(null);
    fetchFile(activeTabPath, dataSource)
      .then(setFile)
      .catch((e: Error) =>
        pushToast({ type: "warning", title: "File not found", message: e.message })
      )
      .finally(() => setLoading(false));
  }, [activeTabPath, dataSource, pushToast]);

  const persist = useCallback(
    async (path: string): Promise<boolean> => {
      const content = drafts[path];
      if (content === undefined) return true;
      setSaving(true);
      setSaveError(null);
      try {
        const updated = await saveFile(path, dataSource, content);
        setDrafts((prev) => {
          if (prev[path] === undefined) return prev;
          const next = { ...prev };
          delete next[path];
          return next;
        });
        if (path === activeTabPath) setFile(updated);
        return true;
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Save failed";
        setSaveError(msg);
        pushToast({ type: "warning", title: "저장 실패", message: msg });
        return false;
      } finally {
        setSaving(false);
      }
    },
    [drafts, dataSource, activeTabPath, pushToast],
  );

  const removeTab = useCallback(
    (path: string) => {
      setDrafts((prev) => {
        if (prev[path] === undefined) return prev;
        const next = { ...prev };
        delete next[path];
        return next;
      });
      setOpenTabs((prev) => {
        const next = prev.filter((p) => p !== path);
        if (activeTabPath === path) {
          const idx = prev.indexOf(path);
          setActiveTabPath(next[idx] ?? next[idx - 1] ?? null);
        }
        return next;
      });
    },
    [activeTabPath],
  );

  const closeTab = useCallback(
    (path: string) => {
      if (drafts[path] !== undefined) {
        setPendingClose(path);
        return;
      }
      removeTab(path);
    },
    [drafts, removeTab],
  );

  const handleDialogSave = useCallback(async () => {
    if (!pendingClose) return;
    const path = pendingClose;
    const ok = await persist(path);
    if (ok) {
      setPendingClose(null);
      removeTab(path);
    }
  }, [pendingClose, persist, removeTab]);

  const handleDialogDiscard = useCallback(() => {
    if (!pendingClose) return;
    const path = pendingClose;
    setPendingClose(null);
    removeTab(path);
  }, [pendingClose, removeTab]);

  const handleDialogCancel = useCallback(() => {
    setPendingClose(null);
  }, []);

  const handleDraftChange = useCallback(
    (value: string) => {
      if (!activeTabPath) return;
      const key = activeTabPath;
      setDrafts((prev) => ({ ...prev, [key]: value }));
      setSaveError(null);
    },
    [activeTabPath],
  );

  const handleSaveActive = useCallback(() => {
    if (!activeTabPath) return;
    void persist(activeTabPath);
  }, [activeTabPath, persist]);

  const dirtyPaths = new Set(Object.keys(drafts));

  if (openTabs.length === 0 || !activeTabPath) {
    return <div className="content-empty">Select a file to view</div>;
  }

  if (loading) return <div className="status-msg">Loading…</div>;
  if (!file) return null;

  const ext = file.ext.toLowerCase();
  const currentDraft =
    drafts[activeTabPath] !== undefined ? drafts[activeTabPath] : file.content;
  const dirty = drafts[activeTabPath] !== undefined;

  const sharedProps: FilePanelSharedProps = {
    filePath: activeTabPath,
    draft: currentDraft,
    onDraftChange: handleDraftChange,
    onSave: handleSaveActive,
    saving,
    saveError,
    dirty,
    mobileLayout,
  };

  const renderContent = () => {
    if (ext === ".md") {
      return <MarkdownFilePanel key={activeTabPath} {...sharedProps} />;
    }
    if (ext === ".json" || ext === ".jsonl") {
      return <JsonFilePanel key={activeTabPath} {...sharedProps} ext={ext} />;
    }
    return (
      <div className="content-area">
        <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {file.content}
        </pre>
      </div>
    );
  };

  const tabViewCls = mobileLayout
    ? `${styles.tabViewRoot} ${styles.tabViewRootMobile}`
    : styles.tabViewRoot;

  const pendingFileName = pendingClose
    ? (pendingClose.split("/").at(-1) ?? pendingClose)
    : "";

  return (
    <div className={tabViewCls}>
      <TabBar
        openTabs={openTabs}
        activeTabPath={activeTabPath}
        onSelectTab={setActiveTabPath}
        onCloseTab={closeTab}
        dirtyPaths={dirtyPaths}
      />
      {renderContent()}
      {pendingClose && (
        <ConfirmCloseDialog
          fileName={pendingFileName}
          onSave={handleDialogSave}
          onDiscard={handleDialogDiscard}
          onCancel={handleDialogCancel}
        />
      )}
    </div>
  );
}
