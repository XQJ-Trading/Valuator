import { useEffect, useState } from "react";
import { fetchTree, fetchFile } from "../api";
import { useToast } from "../ToastContext";
import styles from "./StepAnalysisCard.module.css";

interface StepUsage {
  prompt_tokens: number;
  cached_prompt_tokens: number;
  uncached_prompt_tokens: number;
  completion_tokens: number;
  thought_tokens: number;
  total_tokens: number;
  cache_write_tokens: number;
}

interface StepData {
  session_id: string;
  llm_call_index: number;
  started_at: string;
  timestamp: string;
  trace_method: string;
  task_id: string | null;
  model: string;
  cache_source: string | null;
  prompt: string;
  system_prompt: string;
  response_mime_type: string | null;
  response_json_schema: object | null;
  response_text: string | null;
  usage: StepUsage;
  latency_ms: number;
  error: string | null;
}

export default function StepAnalysisCard({
  onSessionChange,
}: {
  onSessionChange?: (session: string) => void;
}) {
  const pushToast = useToast();

  const [sessions, setSessions] = useState<string[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [selectedSession, setSelectedSession] = useState("");

  const [steps, setSteps] = useState<StepData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    void loadSessions();
  }, []);

  useEffect(() => {
    if (selectedSession) {
      onSessionChange?.(selectedSession);
      void loadSteps(selectedSession);
    }
  }, [selectedSession]);

  async function loadSessions() {
    setSessionsLoading(true);
    try {
      const tree = await fetchTree("", "session");
      const dirs = tree.children
        .filter((e) => e.type === "directory")
        .map((e) => e.name)
        .reverse();
      setSessions(dirs);
      const newSession = dirs[0] || "";
      setSelectedSession(newSession);
      if (newSession) {
        onSessionChange?.(newSession);
      }
    } catch (err) {
      pushToast({ type: "error", title: "세션 목록 로드 실패", message: String(err) });
    } finally {
      setSessionsLoading(false);
    }
  }

  async function loadSteps(sessionId: string) {
    setLoading(true);
    setError(null);
    setSteps([]);
    setExpandedRows(new Set());
    setSearchQuery("");

    try {
      // Try to fetch the debug/steps directory
      let stepsPath = `${sessionId}/debug/steps`;
      let stepsTree: { children: Array<{ name: string; type: string }> };

      try {
        stepsTree = await fetchTree(stepsPath, "session");
      } catch {
        // debug/steps directory doesn't exist
        setError("No debug data available for this session");
        return;
      }

      // Filter step_*.json files and sort
      const stepFiles = stepsTree.children
        .filter((e) => e.type === "file" && e.name.startsWith("step_") && e.name.endsWith(".json"))
        .sort((a, b) => {
          const aNum = parseInt(a.name.match(/\d+/)?.at(0) ?? "0");
          const bNum = parseInt(b.name.match(/\d+/)?.at(0) ?? "0");
          return aNum - bNum;
        });

      if (stepFiles.length === 0) {
        setError("No step files found in debug directory");
        return;
      }

      // Load step files in parallel (batches of 10)
      const stepData: StepData[] = [];
      for (let i = 0; i < stepFiles.length; i += 10) {
        const batch = stepFiles.slice(i, i + 10);
        const batchPromises = batch.map(async (file) => {
          try {
            const filePath = `${stepsPath}/${file.name}`;
            const fileData = await fetchFile(filePath, "session");
            const parsed = JSON.parse(fileData.content) as StepData;
            return parsed;
          } catch (err) {
            console.warn(`Failed to parse ${file.name}:`, err);
            return null;
          }
        });

        const batchResults = await Promise.all(batchPromises);
        stepData.push(...batchResults.filter((s) => s !== null));
      }

      // Sort by llm_call_index
      stepData.sort((a, b) => a.llm_call_index - b.llm_call_index);
      setSteps(stepData);
    } catch (err) {
      const msg = String(err);
      setError(msg);
      pushToast({ type: "error", title: "Step 데이터 로드 실패", message: msg });
    } finally {
      setLoading(false);
    }
  }

  function toggleRow(index: number) {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedRows(newExpanded);
  }

  function calculateCacheHitRate(usage: StepUsage): number {
    const total = usage.cached_prompt_tokens + usage.uncached_prompt_tokens;
    return total > 0 ? Math.round((usage.cached_prompt_tokens / total) * 100) : 0;
  }

  function getCacheHitDisplay(usage: StepUsage, cacheSource: string | null): string {
    // No cache source = caching not supported/available
    if (!cacheSource) return "N/A";

    const rate = calculateCacheHitRate(usage);
    if (rate === 0) return "0%";
    if (rate === 100) return "100% ⚡";
    return `${rate}% ⚡`;
  }

  function getCacheHitClass(usage: StepUsage, cacheSource: string | null): string {
    if (!cacheSource) return styles.cacheHitZero;

    const rate = calculateCacheHitRate(usage);
    if (rate === 0) return styles.cacheHitZero;
    if (rate === 100) return styles.cacheHitFull;
    return styles.cacheHitPartial;
  }

  async function copyToClipboard(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      pushToast({ type: "info", title: "복사됨", message: "클립보드에 복사되었습니다" });
    } catch (err) {
      pushToast({ type: "error", title: "복사 실패", message: String(err) });
    }
  }

  function formatLatency(ms: number): string {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function formatTokens(tokens: number): string {
    if (tokens < 1000) return String(tokens);
    return `${(tokens / 1000).toFixed(1)}k`;
  }

  function getTaskIdDisplay(taskId: string | null): string {
    return taskId || "—";
  }

  const query = searchQuery.trim().toLowerCase();
  const filteredSteps = query
    ? steps.filter(
        (step) =>
          step.prompt.toLowerCase().includes(query) ||
          (step.response_text ?? "").toLowerCase().includes(query)
      )
    : steps;

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.cardTitle}>LLM Step Analysis</span>
      </div>

      <div className={styles.section}>
        <label className={styles.sectionLabel}>Session</label>
        <div className={styles.row}>
          <select
            className={styles.select}
            value={selectedSession}
            onChange={(e) => setSelectedSession(e.target.value)}
            disabled={sessionsLoading || sessions.length === 0}
          >
            {sessions.length === 0 && (
              <option value="">{sessionsLoading ? "로딩 중..." : "세션 없음"}</option>
            )}
            {sessions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void loadSessions()}
            disabled={sessionsLoading}
          >
            새로고침
          </button>
        </div>
      </div>

      <div className={styles.section}>
        <label className={styles.sectionLabel}>Search</label>
        <div className={styles.row}>
          <input
            type="text"
            className={styles.searchInput}
            placeholder="Filter by prompt or output..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => setSearchQuery("")}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {loading && (
        <div className={styles.loading}>
          <span className={styles.spinner} />
          Step 데이터 로딩 중...
        </div>
      )}

      {error && <div className={styles.errorBox}>{error}</div>}

      {!loading && !error && steps.length === 0 && (
        <div className={styles.emptyState}>No debug data available</div>
      )}

      {!loading && steps.length > 0 && filteredSteps.length === 0 && (
        <div className={styles.emptyState}>No steps match "{searchQuery}"</div>
      )}

      {!loading && filteredSteps.length > 0 && (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <colgroup>
              <col style={{ width: "5%" }} />
              <col style={{ width: "15%" }} />
              <col style={{ width: "28%" }} />
              <col style={{ width: "12%" }} />
              <col style={{ width: "20%" }} />
              <col style={{ width: "20%" }} />
            </colgroup>
            <thead className={styles.tableHeader}>
              <tr>
                <th className={styles.tableHeaderCell}>#</th>
                <th className={styles.tableHeaderCell}>Task ID</th>
                <th className={styles.tableHeaderCell}>Model</th>
                <th className={styles.tableHeaderCell}>Cache Hit</th>
                <th className={styles.tableHeaderCell}>Tokens</th>
                <th className={styles.tableHeaderCell}>Latency</th>
              </tr>
            </thead>
            <tbody>
              {filteredSteps.map((step) => {
                const isExpanded = expandedRows.has(step.llm_call_index);
                const hasError = step.error !== null;

                return [
                  <tr
                    key={`row-${step.llm_call_index}`}
                    className={`${styles.tableRow} ${hasError ? styles.rowError : ""}`}
                    onClick={() => toggleRow(step.llm_call_index)}
                  >
                    <td className={styles.tableCell}>
                      <span className={styles.expandIcon}>
                        {isExpanded ? "▾" : "▸"}
                      </span>
                      {step.llm_call_index}
                    </td>
                    <td className={styles.tableCell}>
                      {getTaskIdDisplay(step.task_id)}
                    </td>
                    <td className={styles.tableCell}>
                      {step.model.length > 30 ? step.model.substring(0, 27) + "..." : step.model}
                    </td>
                    <td className={`${styles.tableCell} ${getCacheHitClass(step.usage, step.cache_source)}`}>
                      {getCacheHitDisplay(step.usage, step.cache_source)}
                    </td>
                    <td className={styles.tableCell}>
                      {formatTokens(step.usage.prompt_tokens)}/
                      {formatTokens(step.usage.completion_tokens)}
                    </td>
                    <td className={styles.tableCell}>
                      {formatLatency(step.latency_ms)}
                    </td>
                  </tr>,
                  isExpanded && (
                    <tr
                      key={`expanded-${step.llm_call_index}`}
                      className={`${styles.expandedRow} ${styles.expandedRowActive}`}
                    >
                      <td colSpan={6} className={styles.expandedContent}>
                          <div className={styles.expandedContentInner}>
                            {step.prompt && (
                              <div className={styles.textBlockSection}>
                                <div className={styles.textBlockHeader}>
                                  <span className={styles.textBlockLabel}>
                                    Prompt ({step.usage.prompt_tokens} tokens)
                                  </span>
                                  <button
                                    type="button"
                                    className={styles.copyBtn}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void copyToClipboard(step.prompt);
                                    }}
                                  >
                                    Copy
                                  </button>
                                </div>
                                <div className={styles.textContent}>
                                  {step.prompt}
                                </div>
                              </div>
                            )}

                            {step.system_prompt && (
                              <div className={styles.textBlockSection}>
                                <div className={styles.textBlockHeader}>
                                  <span className={styles.textBlockLabel}>System Prompt</span>
                                  <button
                                    type="button"
                                    className={styles.copyBtn}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void copyToClipboard(step.system_prompt);
                                    }}
                                  >
                                    Copy
                                  </button>
                                </div>
                                <div className={styles.textContent}>
                                  {step.system_prompt}
                                </div>
                              </div>
                            )}

                            {step.response_text && (
                              <div className={styles.textBlockSection}>
                                <div className={styles.textBlockHeader}>
                                  <span className={styles.textBlockLabel}>
                                    Response ({step.usage.completion_tokens} tokens)
                                  </span>
                                  <button
                                    type="button"
                                    className={styles.copyBtn}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void copyToClipboard(step.response_text ?? "");
                                    }}
                                  >
                                    Copy
                                  </button>
                                </div>
                                <div className={`${styles.textContent} ${styles.responseContent}`}>
                                  {step.response_text}
                                </div>
                              </div>
                            )}

                            <div className={styles.metadataSection}>
                              <div className={styles.metadataLabel}>Metadata</div>
                              <ul className={styles.metadataList}>
                                <li className={styles.metadataItem}>
                                  <span className={styles.metadataKey}>Timestamp:</span>
                                  {step.timestamp}
                                </li>
                                <li className={styles.metadataItem}>
                                  <span className={styles.metadataKey}>Trace Method:</span>
                                  {step.trace_method}
                                </li>
                                {step.cache_source && (
                                  <li className={styles.metadataItem}>
                                    <span className={styles.metadataKey}>Cache Source:</span>
                                    {step.cache_source}
                                  </li>
                                )}
                                {step.response_mime_type && (
                                  <li className={styles.metadataItem}>
                                    <span className={styles.metadataKey}>Response Type:</span>
                                    {step.response_mime_type}
                                  </li>
                                )}
                                {step.error && (
                                  <li className={`${styles.metadataItem} ${styles.errorMetadata}`}>
                                    <span className={styles.metadataKey}>Error:</span>
                                    {step.error}
                                  </li>
                                )}
                              </ul>
                            </div>
                          </div>
                        </td>
                      </tr>
                    ),
                ];
              }).flat()}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
