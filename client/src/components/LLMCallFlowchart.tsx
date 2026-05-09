import { useEffect, useRef, useState } from "react";
import svgPanZoom from "svg-pan-zoom";
import { fetchTree, fetchFile } from "../api";
import { useToast } from "../ToastContext";
import styles from "./LLMCallFlowchart.module.css";

interface StepData {
  llm_call_index: number;
  task_id: string | null;
  started_at: string;
}

interface TaskTreeNode {
  task_id: string;
  description: string;
  state: string;
  path: string;
  children: TaskTreeNode[];
}

interface TaskInfo {
  description: string;
  deps: string[];
}

export default function LLMCallFlowchart({
  selectedSession,
}: {
  selectedSession: string;
}) {
  const pushToast = useToast();
  const [mermaidCode, setMermaidCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const svgContainerRef = useRef<HTMLDivElement>(null);
  const panZoomRef = useRef<SvgPanZoom.Instance | null>(null);

  useEffect(() => {
    if (selectedSession && selectedSession !== "_chat") {
      void loadAndGenerateFlowchart(selectedSession);
    }
  }, [selectedSession]);

  useEffect(() => {
    if (!mermaidCode || !svgContainerRef.current) return;

    let cancelled = false;
    setRenderError(null);

    (async () => {
      try {
        const mermaidModule = await import("mermaid");
        const mermaid = mermaidModule.default ?? mermaidModule;

        if (typeof mermaid.initialize === "function") {
          mermaid.initialize({
            startOnLoad: false,
            theme: "default",
            securityLevel: "loose",
            // htmlLabels must be false for svg-pan-zoom: HTML foreignObject labels
            // get clipped/misplaced when the SVG is transformed.
            flowchart: { htmlLabels: false, useMaxWidth: false },
          });
        }

        const id = `mmd-${Date.now()}`;
        const result = await mermaid.render(id, mermaidCode);
        if (cancelled) return;
        if (!svgContainerRef.current) return;

        // Tear down any prior panzoom instance
        if (panZoomRef.current) {
          panZoomRef.current.destroy();
          panZoomRef.current = null;
        }

        svgContainerRef.current.innerHTML = result.svg;
        if (typeof result.bindFunctions === "function") {
          result.bindFunctions(svgContainerRef.current);
        }

        const svgEl = svgContainerRef.current.querySelector("svg");
        if (svgEl) {
          // svg-pan-zoom needs the svg to fill the container
          svgEl.setAttribute("width", "100%");
          svgEl.setAttribute("height", "100%");
          svgEl.style.maxWidth = "none";
          svgEl.style.maxHeight = "none";

          panZoomRef.current = svgPanZoom(svgEl, {
            zoomEnabled: true,
            controlIconsEnabled: true,
            fit: true,
            center: true,
            minZoom: 0.2,
            maxZoom: 10,
            zoomScaleSensitivity: 0.3,
          });
        }
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        console.error("Mermaid render failed:", err);
        setRenderError(msg);
      }
    })();

    return () => {
      cancelled = true;
      if (panZoomRef.current) {
        panZoomRef.current.destroy();
        panZoomRef.current = null;
      }
    };
  }, [mermaidCode]);

  async function loadAndGenerateFlowchart(sessionId: string) {
    setLoading(true);
    setError(null);
    setRenderError(null);
    setMermaidCode("");

    try {
      let planTasks: Record<string, TaskInfo> = {};
      try {
        const taskTreeFile = await fetchFile(
          `${sessionId}/plan/active/task_tree.json`,
          "session"
        );
        const taskTreeRoot = JSON.parse(taskTreeFile.content) as TaskTreeNode;
        planTasks = flattenTaskTree(taskTreeRoot);
        if (Object.keys(planTasks).length === 0) {
          setError("Task tree is empty");
          return;
        }
      } catch (err) {
        setError(`Failed to load task tree: ${String(err)}`);
        return;
      }

      let stepFiles: Array<{ name: string; type: string }> = [];
      try {
        const stepsDir = await fetchTree(`${sessionId}/debug/steps`, "session");
        stepFiles = stepsDir.children
          .filter((e) => e.type === "file" && e.name.startsWith("step_"))
          .sort((a, b) => {
            const aNum = parseInt(a.name.match(/\d+/)?.[0] ?? "0");
            const bNum = parseInt(b.name.match(/\d+/)?.[0] ?? "0");
            return aNum - bNum;
          });
      } catch {
        setError("No debug steps found for this session");
        return;
      }

      const steps: StepData[] = [];
      for (let i = 0; i < stepFiles.length; i += 10) {
        const batch = stepFiles.slice(i, i + 10);
        const batchPromises = batch.map(async (file) => {
          try {
            const content = await fetchFile(
              `${sessionId}/debug/steps/${file.name}`,
              "session"
            );
            const step = JSON.parse(content.content);
            return {
              llm_call_index: step.llm_call_index,
              task_id: step.task_id,
              started_at: step.started_at,
            } as StepData;
          } catch {
            return null;
          }
        });

        const batchResults = await Promise.all(batchPromises);
        steps.push(...batchResults.filter((s): s is StepData => s !== null));
      }

      if (steps.length === 0) {
        setError("No LLM calls found in debug steps");
        return;
      }

      const mmd = buildMermaidFlowchart(planTasks, steps);
      setMermaidCode(mmd);
    } catch (err) {
      const msg = String(err);
      setError(msg);
      pushToast({
        type: "error",
        title: "Flowchart 생성 실패",
        message: msg,
      });
    } finally {
      setLoading(false);
    }
  }

  function sanitizeLabel(text: string, maxLen = 20): string {
    // Strip characters that break mermaid label parsing
    return text
      .replace(/["`]/g, "'")
      .replace(/[\[\]{}()<>|]/g, " ")
      .replace(/[\r\n]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .substring(0, maxLen);
  }

  function nodeId(taskId: string): string {
    // Mermaid node IDs must be alphanumeric/underscore; replace anything else
    return `task_${taskId.replace(/[^a-zA-Z0-9_]/g, "_")}`;
  }

  function flattenTaskTree(
    root: TaskTreeNode,
    out: Record<string, TaskInfo> = {}
  ): Record<string, TaskInfo> {
    const childIds = (root.children || []).map((c) => c.task_id);
    out[root.task_id] = {
      description: root.description || "",
      deps: childIds,
    };
    for (const child of root.children || []) {
      flattenTaskTree(child, out);
    }
    return out;
  }

  function buildMermaidFlowchart(
    planTasks: Record<string, TaskInfo>,
    steps: StepData[]
  ): string {
    const lines: string[] = ["graph TD"];
    const taskIds = Object.keys(planTasks);
    const stepsPerTask: Record<string, number[]> = {};

    for (const step of steps) {
      if (step.task_id) {
        if (!stepsPerTask[step.task_id]) stepsPerTask[step.task_id] = [];
        stepsPerTask[step.task_id].push(step.llm_call_index);
      }
    }

    for (const taskId of taskIds) {
      const task = planTasks[taskId];
      const desc = sanitizeLabel(task.description || "", 25);
      const taskLabel = sanitizeLabel(taskId, 30);
      const taskNodeId = nodeId(taskId);

      lines.push(`  subgraph ${taskNodeId} ["${taskLabel}: ${desc}"]`);

      const calls = stepsPerTask[taskId] || [];
      if (calls.length === 0) {
        lines.push(`    ${taskNodeId}_empty["(no LLM calls)"]`);
      } else {
        for (let i = 0; i < calls.length; i++) {
          const callIdx = calls[i];
          const callNodeId = `llm_${taskNodeId}_${i}`;
          lines.push(`    ${callNodeId}(["#${callIdx}"])`);

          if (i > 0) {
            const prevNodeId = `llm_${taskNodeId}_${i - 1}`;
            lines.push(`    ${prevNodeId} --> ${callNodeId}`);
          }
        }
      }

      lines.push(`  end`);
    }

    for (const [taskId, task] of Object.entries(planTasks)) {
      const taskNodeId = nodeId(taskId);
      for (const depId of task.deps || []) {
        const depNodeId = nodeId(depId);
        lines.push(`  ${depNodeId} --> ${taskNodeId}`);
      }
    }

    return lines.join("\n");
  }

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.cardTitle}>LLM Call Flowchart (Detailed)</span>
        {mermaidCode && (
          <button
            type="button"
            className={styles.toggleBtn}
            onClick={() => setShowRaw((v) => !v)}
          >
            {showRaw ? "Hide Code" : "Show Code"}
          </button>
        )}
      </div>

      {loading && (
        <div className={styles.loading}>
          <span className={styles.spinner} />
          Generating flowchart...
        </div>
      )}

      {error && <div className={styles.errorBox}>{error}</div>}

      {renderError && (
        <div className={styles.errorBox}>
          Mermaid render error: {renderError}
        </div>
      )}

      {!loading && !error && mermaidCode && showRaw && (
        <pre className={styles.codeBlock}>{mermaidCode}</pre>
      )}

      {!loading && !error && mermaidCode && (
        <div className={styles.mermaidContainer} ref={svgContainerRef} />
      )}
    </div>
  );
}
