import { useEffect, useState } from "react";
import { fetchTree, type DataSource, type TreeEntry } from "../api";
import styles from "./UserSessionView.module.css";

interface SessionItem {
  path: string;
  displayName: string;
  relativeTime: string;
  rawName: string;
}

function parseSessionItem(entry: TreeEntry): SessionItem {
  const m = entry.name.match(/^(\d{8})-(\d{4})-(.+)$/);
  const displayName = m ? m[3] : entry.name;
  const relativeTime = m ? formatRelativeTime(m[1], m[2]) : "";
  return { path: entry.path, displayName, relativeTime, rawName: entry.name };
}

function formatRelativeTime(dateStr: string, timeStr: string): string {
  const year = parseInt(dateStr.substring(0, 4), 10);
  const month = parseInt(dateStr.substring(4, 6), 10);
  const day = parseInt(dateStr.substring(6, 8), 10);
  const hours = parseInt(timeStr.substring(0, 2), 10);
  const mins = parseInt(timeStr.substring(2, 4), 10);

  const sessionDate = new Date(year, month - 1, day, hours, mins, 0);
  const now = new Date();
  const diffMs = now.getTime() - sessionDate.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  return `${Math.floor(diffDays / 30)}mo ago`;
}

export default function UserSessionView({
  dataSource,
  onSelectDirectory,
  onUserSelectDirectory,
  onSelect,
}: {
  dataSource: DataSource;
  onSelectDirectory: (path: string) => void;
  onUserSelectDirectory?: () => void;
  onSelect: (path: string | null) => void;
}) {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    void (async () => {
      try {
        const result = await fetchTree("", dataSource);
        if (cancelled) return;

        const items = result.children
          .filter((e) => e.type === "directory")
          .map(parseSessionItem)
          .sort((a, b) => b.rawName.localeCompare(a.rawName));

        setSessions(items);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load sessions");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [dataSource]);

  const handleSessionClick = (session: SessionItem) => {
    setSelectedPath(session.path);
    onSelectDirectory(session.path);
    onUserSelectDirectory?.();
    onSelect(null);
  };

  return (
    <div className={styles.sidebar}>
      <div className={styles.explorerHeader}>
        <span className={styles.explorerTitle}>Explorer</span>
      </div>

      <div className={styles.sectionHeader}>Threads</div>

      <div className={styles.sessionList}>
        {loading && <div className={styles.loadingPlaceholder}>Loading sessions...</div>}
        {error && <div className={styles.errorMessage}>{error}</div>}
        {!loading && sessions.length === 0 && (
          <div className={styles.emptyMessage}>No sessions found</div>
        )}
        {!loading &&
          sessions.map((session) => (
            <div
              key={session.path}
              className={`${styles.sessionRow} ${selectedPath === session.path ? styles.selected : ""}`}
              onClick={() => handleSessionClick(session)}
            >
              <svg
                className={styles.folderIcon}
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="currentColor"
                aria-hidden
              >
                <path d="M2.5 3.5h4.5l1 1.5H13.5V13h-11V3.5zm1 1V12h9V6.5H7.6L6.6 5h-3v-.5z" />
              </svg>
              <span className={styles.sessionName}>{session.displayName}</span>
              <span className={styles.sessionTime}>{session.relativeTime}</span>
            </div>
          ))}
      </div>
    </div>
  );
}
