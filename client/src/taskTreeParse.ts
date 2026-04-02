export type TaskOutlineRow = {
  depth: number;
  taskId: string;
  /** Human-readable slug from task.json / LLM (optional). */
  taskName: string | null;
  label: string;
  status: string | null;
};

const TASK_LINE = /^(\s*)-\s+\*\*([^*]+)\*\*\s*(.*)$/;

/** `root`, `root.0`, `root.0.1`, … */
function isTaskId(token: string): boolean {
  return /^root(\.\d+)*$/.test(token.trim());
}

/** First hierarchical task line (`root.N…`), after which the real tree usually starts. */
function indexOfFirstNumberedRootTask(lines: readonly string[]): number {
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(TASK_LINE);
    if (m && /^root\.\d/.test(m[2].trim())) {
      return i;
    }
  }
  return -1;
}

function stripLeafSuffix(label: string): string {
  return label.replace(/\s*\(leaf:\s*[^)]+\)\s*$/i, "").trim();
}

function rowFromMatch(m: RegExpMatchArray, depthScale: number): TaskOutlineRow | null {
  const indent = m[1].length;
  const depth = Math.floor(indent / depthScale);
  const taskId = m[2].trim();
  if (!isTaskId(taskId)) return null;

  let rest = m[3].trim();
  let taskName: string | null = null;
  const nameMatch = rest.match(/^`([^`]+)`\s+(.*)$/s);
  if (nameMatch) {
    taskName = nameMatch[1].trim();
    rest = nameMatch[2].trim();
  }
  const sm = rest.match(/^\[([^\]]+)\]\s*/);
  const status = sm ? sm[1] : null;
  let label = sm ? rest.slice(sm[0].length).trim() : rest;
  label = stripLeafSuffix(label);
  label = label.replace(/\s+/g, " ").trim();
  if (label.length > 280) {
    label = `${label.slice(0, 277)}…`;
  }
  return {
    depth,
    taskId,
    taskName,
    label: label || taskId,
    status,
  };
}

function parseSlice(lines: readonly string[], skipBareRoot: boolean): TaskOutlineRow[] {
  const out: TaskOutlineRow[] = [];
  for (const line of lines) {
    const m = line.match(TASK_LINE);
    if (!m) continue;
    const taskId = m[2].trim();
    if (!isTaskId(taskId)) continue;
    if (skipBareRoot && taskId === "root") continue;
    const row = rowFromMatch(m, 2);
    if (row) out.push(row);
  }
  return out;
}

/**
 * Parses `plan/active/task_tree.md`: ignores QUERY / template prose before the first
 * `root.N` bullet, drops noisy bare `root` when numbered tasks exist, strips `(leaf: …)`.
 */
export function parseTaskTreeMd(content: string): TaskOutlineRow[] {
  const lines = content.split(/\r?\n/);
  const firstNum = indexOfFirstNumberedRootTask(lines);
  const skipBareRoot = firstNum >= 0;
  const slice = firstNum >= 0 ? lines.slice(firstNum) : lines;
  const primary = parseSlice(slice, skipBareRoot);
  if (primary.length > 0) {
    return primary;
  }
  const fallback = parseSlice(lines, false).filter((row) => {
    if (row.taskId !== "root") return true;
    return !/THINKING_LEVEL|Analysis:\s*\[/i.test(row.label);
  });
  return fallback;
}
