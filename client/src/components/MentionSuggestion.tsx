import type { DataSource } from "../api";
import styles from "./MentionSuggestion.module.css";

export type FileMentionItem = {
  id: string;
  label: string;
  source: DataSource;
  path: string;
  type: "file" | "directory";
};

function formatPathHint(relPath: string): string {
  const parent =
    relPath.includes("/") ? relPath.slice(0, relPath.lastIndexOf("/")) : "";
  if (!parent) return relPath;
  if (parent.length <= 36) return parent;
  return `…${parent.slice(-34)}`;
}

export function renderMentionItem(item: FileMentionItem, focused: boolean) {
  return (
    <div className={`${styles.item} ${focused ? styles.itemActive : ""}`}>
      <span className={styles.icon} aria-hidden>
        {item.type === "directory" ? "📁" : "📄"}
      </span>
      <div className={styles.main}>
        <span className={styles.name}>{item.label}</span>
        <span className={styles.meta} title={item.path}>
          {formatPathHint(item.path)}
        </span>
      </div>
      <span className={styles.source}>{item.source}</span>
    </div>
  );
}
