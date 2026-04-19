import { useEffect, useRef, useState } from "react";
import { useChatSession } from "../ChatSessionContext";
import styles from "./SlashMenu.module.css";

export default function SlashMenu() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const {
    webSearchProvider,
    setWebSearchProvider,
    webSearchProviders,
    webSearchProvidersLoading,
    pending,
    loadingList,
  } = useChatSession();

  useEffect(() => {
    if (!open) return;
    function handleMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [open]);

  const isActive = webSearchProvider !== "";

  return (
    <div ref={containerRef} className={styles.container}>
      {open && (
        <div className={styles.popup}>
          <div className={styles.section}>Search &amp; Tools</div>
          <div className={styles.row}>
            <span className={styles.label}>Web Search</span>
            <select
              className={styles.select}
              value={webSearchProvider}
              disabled={pending || loadingList || webSearchProvidersLoading || webSearchProviders.length === 0}
              onChange={(e) =>
                setWebSearchProvider(e.target.value as "perplexity" | "tavily" | "")
              }
            >
              <option value="">Off</option>
              {webSearchProviders.includes("perplexity") && (
                <option value="perplexity">Perplexity</option>
              )}
              {webSearchProviders.includes("tavily") && (
                <option value="tavily">Tavily</option>
              )}
              {webSearchProviders.length === 0 && (
                <option value="" disabled>Unavailable</option>
              )}
            </select>
          </div>
        </div>
      )}
      <button
        type="button"
        className={`${styles.button} ${isActive ? styles.buttonActive : ""}`}
        onClick={() => setOpen((v) => !v)}
        title="Actions"
      >
        /
      </button>
    </div>
  );
}
