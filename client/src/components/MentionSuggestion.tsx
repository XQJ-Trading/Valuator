import {
  forwardRef,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { SuggestionKeyDownProps, SuggestionProps } from "@tiptap/suggestion";
import type { DataSource } from "../api";
import styles from "./MentionSuggestion.module.css";

export type FileMentionItem = {
  id: string;
  label: string;
  source: DataSource;
  path: string;
  type: "file" | "directory";
};

export type MentionListHandle = {
  onKeyDown: (props: SuggestionKeyDownProps) => boolean;
};

type ListProps = SuggestionProps<FileMentionItem, FileMentionItem>;

function formatPathHint(relPath: string): string {
  const parent =
    relPath.includes("/") ? relPath.slice(0, relPath.lastIndexOf("/")) : "";
  if (!parent) return relPath;
  if (parent.length <= 36) return parent;
  return `…${parent.slice(-34)}`;
}

const MentionListInner = forwardRef<MentionListHandle, ListProps>(
  ({ items, command }, ref) => {
    const [selectedIndex, setSelectedIndex] = useState(0);
    const selectedIndexRef = useRef(0);

    useImperativeHandle(ref, () => ({
      onKeyDown: ({ event }) => {
        if (event.key === "ArrowUp") {
          event.preventDefault();
          setSelectedIndex((i) => {
            const next = (i + items.length - 1) % Math.max(items.length, 1);
            selectedIndexRef.current = next;
            return next;
          });
          return true;
        }
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setSelectedIndex((i) => {
            const next = (i + 1) % Math.max(items.length, 1);
            selectedIndexRef.current = next;
            return next;
          });
          return true;
        }
        if (event.key === "Enter") {
          event.preventDefault();
          const item = items[selectedIndexRef.current];
          if (item) {
            command(item);
          }
          return true;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          return true;
        }
        return false;
      },
    }));

    const selectItem = (index: number) => {
      const item = items[index];
      if (item) command(item);
    };

    if (!items.length) {
      return (
        <div className={styles.root}>
          <div className={styles.empty}>No matching files</div>
        </div>
      );
    }

    return (
      <div className={styles.root} role="listbox" aria-label="File mentions">
        {items.map((item, index) => (
          <button
            key={`${item.source}:${item.path}`}
            type="button"
            role="option"
            aria-selected={index === selectedIndex}
            className={`${styles.item} ${index === selectedIndex ? styles.itemActive : ""}`}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => selectItem(index)}
          >
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
          </button>
        ))}
      </div>
    );
  },
);

MentionListInner.displayName = "MentionListInner";

/** Wrapper resets selection when the suggestion item list changes (new query). */
export const MentionList = forwardRef<MentionListHandle, ListProps>((props, ref) => {
  const listKey = props.items.map((i) => i.id).join("|");
  return <MentionListInner key={listKey} {...props} ref={ref} />;
});

MentionList.displayName = "MentionList";
