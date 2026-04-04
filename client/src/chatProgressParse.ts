export interface ProgressItem {
  kind: "step" | "done" | "failed" | "other";
  taskId: string;
  description: string;
  /** Short slug from agent (e.g. segment_financial_analysis); optional. */
  taskName?: string;
  /** Session-wide step index from agent (gN in stdout). */
  globalSeq?: number;
  /** Per-task step index (lN in stdout). */
  localStep?: number;
}

export function parseProgressLine(line: string): ProgressItem {
  const parts = line.split(" ");
  const raw = parts[0] ?? "";
  const kind = (
    raw.startsWith("[") && raw.endsWith("]") ? raw.slice(1, -1) : "other"
  ) as ProgressItem["kind"];
  const taskId = parts[1] ?? "";
  let descStart = 2;
  let taskName: string | undefined;
  let globalSeq: number | undefined;
  let localStep: number | undefined;
  if (kind === "step") {
    if (parts[descStart] && !/^[gl]\d+$/.test(parts[descStart] ?? "")) {
      taskName = parts[descStart];
      descStart += 1;
    }
    while (descStart < parts.length && /^[gl]\d+$/.test(parts[descStart] ?? "")) {
      const tok = parts[descStart] ?? "";
      if (tok.startsWith("g")) {
        const n = Number.parseInt(tok.slice(1), 10);
        if (!Number.isNaN(n)) globalSeq = n;
      }
      if (tok.startsWith("l")) {
        const n = Number.parseInt(tok.slice(1), 10);
        if (!Number.isNaN(n)) localStep = n;
      }
      descStart++;
    }
  } else if (kind === "done") {
    if (parts[2]) {
      taskName = parts[2];
    }
  }
  const description = parts.slice(descStart).join(" ").trim();
  return {
    kind,
    taskId,
    description,
    taskName,
    globalSeq,
    localStep,
  };
}
