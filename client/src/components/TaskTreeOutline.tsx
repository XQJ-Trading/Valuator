import { useEffect, useRef, useState } from "react";
import {
  fetchBrowseOutline,
  fetchFile,
  type BrowseOutlineRow,
  type DataSource,
} from "../api";
import { browseDirToFinalPath, browseDirToReportPath } from "../browseOutline";
import { parseTaskTreeMd, type TaskOutlineRow } from "../taskTreeParse";
import { taskIdToTaskMdPath } from "../taskTreePaths";
import styles from "./TaskTreeOutline.module.css";

const TASK_TREE_REL = "plan/active/task_tree.md";

const TITLE_TASK_TREE_FALLBACK = "plan/active/task_tree.md 기반 목차";

function browseTitle(
  dataSourceLabel: string,
  browseRootPath: string | null,
): string {
  if (browseRootPath) {
    return `${dataSourceLabel} 세션의 \`${browseRootPath}\` — 각 하위 폴더의 README·report.md를 읽어 목차를 만듭니다.`;
  }
  return `${dataSourceLabel} 세션의 \`browse/\` — 하위 폴더의 README·report.md를 읽어 목차를 만듭니다.`;
}

/** First path segment under the data root, e.g. session folder name; omit → server uses latest. */
function sessionFolderFromSelection(selectedDirectoryPath: string | null): string | null {
  const raw = (selectedDirectoryPath || "").trim().replace(/^\/+|\/+$/g, "");
  if (!raw) return null;
  return raw.split("/")[0] || null;
}

export type { TaskOutlineRow };

export default function TaskTreeOutline({
  dataSource,
  enabled,
  onOpenTaskFile,
  selectedDirectoryPath,
  outlineChatTick,
  outlineFolderEnsureTick,
}: {
  dataSource: DataSource;
  enabled: boolean;
  onOpenTaskFile: (relPath: string) => void;
  selectedDirectoryPath: string | null;
  /** Bumps on chat `agent_finished` or reset — reload outline from disk (fast, no browse rebuild). */
  outlineChatTick: number;
  /** Bumps when the user selects a folder in Explorer — may rebuild browse/ from tasks (can be slow). */
  outlineFolderEnsureTick: number;
}) {
  const [browseRows, setBrowseRows] = useState<BrowseOutlineRow[] | null>(null);
  const [browseRootUsed, setBrowseRootUsed] = useState<string | null>(null);
  const [taskRows, setTaskRows] = useState<TaskOutlineRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadGenerationRef = useRef(0);
  const prevFolderEnsureTickRef = useRef(0);
  const loadedKeyRef = useRef<{ dataSource: DataSource; selectedDir: string | null; chatTick: number } | null>(null);

  const dataSourceLabel = dataSource === "guide" ? "Guide" : "Session";

  useEffect(() => {
    if (!enabled) return;

    // Skip fetch if same dataSource + selectedDir + chatTick
    const folderTickAdvanced = outlineFolderEnsureTick > prevFolderEnsureTickRef.current;
    const currentKey = { dataSource, selectedDir: selectedDirectoryPath, chatTick: outlineChatTick };
    const prev = loadedKeyRef.current;
    if (
      !folderTickAdvanced &&
      prev &&
      prev.dataSource === currentKey.dataSource &&
      prev.selectedDir === currentKey.selectedDir &&
      prev.chatTick === currentKey.chatTick
    ) {
      return;
    }

    const myGeneration = ++loadGenerationRef.current;
    setLoading(true);
    setError(null);
    setBrowseRows(null);
    setBrowseRootUsed(null);
    setTaskRows([]);

    void (async () => {
      try {
        const sessionFolder = sessionFolderFromSelection(selectedDirectoryPath);
        if (folderTickAdvanced) {
          prevFolderEnsureTickRef.current = outlineFolderEnsureTick;
        }
        const ensureBrowse = folderTickAdvanced;
        const out = await fetchBrowseOutline(dataSource, sessionFolder, {
          ensureBrowse,
        });
        if (loadGenerationRef.current !== myGeneration) return;
        if (out.rows.length > 0) {
          setBrowseRows(out.rows);
          setBrowseRootUsed(out.browseRootPath);
          loadedKeyRef.current = currentKey;
          return;
        }
        try {
          const f = await fetchFile(TASK_TREE_REL, dataSource);
          if (loadGenerationRef.current !== myGeneration) return;
          setTaskRows(parseTaskTreeMd(f.content));
          setError(null);
          loadedKeyRef.current = currentKey;
        } catch (e) {
          if (loadGenerationRef.current !== myGeneration) return;
          setTaskRows([]);
          setError(e instanceof Error ? e.message : "load failed");
        }
      } catch (e) {
        if (loadGenerationRef.current !== myGeneration) return;
        setTaskRows([]);
        setError(e instanceof Error ? e.message : "load failed");
      } finally {
        if (loadGenerationRef.current === myGeneration) {
          setLoading(false);
        }
      }
    })();
  }, [
    dataSource,
    enabled,
    selectedDirectoryPath,
    outlineChatTick,
    outlineFolderEnsureTick,
  ]);

  const useBrowse = (browseRows?.length ?? 0) > 0;
  const displayRows = useBrowse ? browseRows! : taskRows;

  const headerTitle = (() => {
    if (error) return "목차";
    if (useBrowse) return browseTitle(dataSourceLabel, browseRootUsed);
    return `${dataSourceLabel} · ${TITLE_TASK_TREE_FALLBACK}`;
  })();

  const showTaskTreeSource = !loading && !error && !useBrowse;

  if (!enabled) {
    return (
      <div className={styles.root}>
        <div className={styles.header}>
          <span className={styles.headerTitle}>
            {browseTitle("Session", null)}
          </span>
        </div>
        <div className={styles.hint}>Session 또는 Guide 뷰에서 세션 데이터를 연 다음 목차가 채워집니다.</div>
      </div>
    );
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <span className={styles.headerTitle}>
          {loading ? (
            <span className={styles.headerLoading}>
              <span className={styles.headerSpinner} aria-hidden />
              목차 불러오는 중…
            </span>
          ) : (
            headerTitle
          )}
        </span>
        {showTaskTreeSource ? (
          <span className={styles.headerSource} title="폴백: task_tree.md">
            task_tree.md
          </span>
        ) : null}
      </div>
      <div
        className={styles.scroll}
        role="navigation"
        aria-label={loading ? "목차 불러오는 중" : headerTitle}
        aria-busy={loading}
      >
        {!loading && error ? (
          <div className={styles.error} role="alert">
            <p className={styles.errorLead}>서버에서 browse 목차를 구성합니다.</p>
            <p className={styles.errorDetail} title={error ?? undefined}>
              {error}
            </p>
          </div>
        ) : null}
        {!loading && !error && displayRows.length === 0 ? (
          <div className={styles.empty}>browse/가 비어 있거나 task_tree.md가 없습니다.</div>
        ) : null}
        {!loading && !error && useBrowse
          ? browseRows!.map((row, idx) => {
              const pad = 8 + row.depth * 12;
              const openPath =
                idx === 0
                  ? browseDirToFinalPath(row.relPath)
                  : browseDirToReportPath(row.relPath);
              return (
                <button
                  key={`${row.relPath}-${idx}`}
                  type="button"
                  className={styles.row}
                  style={{ paddingLeft: pad }}
                  onClick={() => onOpenTaskFile(openPath)}
                >
                  <span className={styles.browseTitle}>{row.title}</span>
                  <span className={styles.browsePath}>{row.relPath}</span>
                </button>
              );
            })
          : null}
        {!loading && !error && !useBrowse
          ? taskRows.map((row, idx) => {
              const path = taskIdToTaskMdPath(row.taskId);
              const pad = 8 + row.depth * 12;
              const st = row.status?.toLowerCase() ?? "";
              const statusClass =
                st === "done" || st === "complete" ? styles.statusDone : styles.statusOther;
              return (
                <button
                  key={`${row.taskId}-${idx}`}
                  type="button"
                  className={styles.row}
                  style={{ paddingLeft: pad }}
                  disabled={!path}
                  onClick={() => {
                    if (path) onOpenTaskFile(path);
                  }}
                >
                  <span className={styles.taskId}>{row.taskName ?? row.taskId}</span>
                  <span className={styles.label}>{row.label}</span>
                  {row.status ? (
                    <span className={`${styles.meta} ${statusClass}`}>[{row.status}]</span>
                  ) : null}
                </button>
              );
            })
          : null}
      </div>
    </div>
  );
}
