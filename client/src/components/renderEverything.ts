import { parseJsonContent, type JsonExt } from "./jsonParse";

export type RenderEverythingExt = ".md" | JsonExt;

type RenderResult = {
  markdown: string;
  parseError: string | null;
};

type CalloutType = "transition" | "json-section";

function headingText(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized || "(empty key)";
}

function stringifyPrimitive(value: unknown): string {
  if (typeof value === "string") {
    return value.length > 0 ? value : "_(empty string)_";
  }
  if (value === null) return "`null`";
  if (typeof value === "number" || typeof value === "boolean") {
    return `\`${String(value)}\``;
  }
  return `\`${JSON.stringify(value)}\``;
}

function looksLikeMarkdown(text: string): boolean {
  const value = text.trim();
  if (!value) return false;
  if (/^#{1,6}\s+\S/m.test(value)) return true;
  if (/^\s*[-*+]\s+\S/m.test(value)) return true;
  if (/^\s*\d+\.\s+\S/m.test(value)) return true;
  if (/```/.test(value)) return true;
  if (/^\s*>\s+\S/m.test(value)) return true;
  if (/\[.+\]\(.+\)/.test(value)) return true;

  const hasPipeRows = /\|.+\|/.test(value);
  const hasTableRule = /\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+/.test(value);
  return hasPipeRows && hasTableRule;
}

/** CommonMark nested blockquotes: `>`, `> >`, … */
function quotePrefix(level: number): string {
  if (level <= 0) return "";
  return `${">".repeat(level)} `;
}

/** innerLines: content without leading `>`; marker uses depth in text for MarkdownView. */
function pushDepthCallout(lines: string[], depth: number, type: CalloutType, innerLines: string[]): void {
  const p = quotePrefix(depth);
  lines.push(`${p}depth:${depth}:${type}`);
  lines.push(p);
  for (const line of innerLines) {
    lines.push(p + line);
  }
}

/**
 * Title lines get depth prefix. Body: lines already starting with `>` (JSON subtree) are appended as-is;
 * otherwise each line is prefixed (unprefixed prose from nested markdown).
 */
function pushTransitionCallout(
  lines: string[],
  depth: number,
  title: string,
  bodyLines: string[],
): void {
  const p = quotePrefix(depth);
  lines.push(`${p}depth:${depth}:transition`);
  lines.push(p);
  lines.push(p + `**${title}**`);
  lines.push(p);
  if (bodyLines.length === 0) {
    lines.push(p + "_(empty)_");
    return;
  }
  for (const line of bodyLines) {
    if (line.startsWith(">")) {
      lines.push(line);
    } else {
      lines.push(p + line);
    }
  }
}

function appendJsonValue(lines: string[], label: string, value: unknown, depth: number): void {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) {
      pushDepthCallout(lines, depth, "json-section", [
        `### ${headingText(label)}`,
        "",
        "_Empty object_",
      ]);
      return;
    }
    pushDepthCallout(lines, depth, "json-section", [`### ${headingText(label)}`, ""]);
    entries.forEach(([key, child]) => {
      appendJsonValue(lines, key, child, depth + 1);
    });
    return;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      pushDepthCallout(lines, depth, "json-section", [
        `### ${headingText(label)}`,
        "",
        "_Empty array_",
      ]);
      return;
    }
    pushDepthCallout(lines, depth, "json-section", [`### ${headingText(label)}`, ""]);
    value.forEach((item, index) => {
      appendJsonValue(lines, `Item ${index + 1}`, item, depth + 1);
    });
    return;
  }

  if (typeof value === "string" && looksLikeMarkdown(value)) {
    pushDepthCallout(lines, depth, "json-section", [`### ${headingText(label)}`, ""]);
    const nestedMd = renderMarkdownWithEmbeddedJson(value, depth);
    pushTransitionCallout(lines, depth + 1, "JSON -> Markdown", nestedMd.split("\n"));
    return;
  }

  pushDepthCallout(lines, depth, "json-section", [
    `### ${headingText(label)}`,
    "",
    stringifyPrimitive(value),
  ]);
}

function renderJsonAsMarkdown(data: unknown, rootLabel: string, startDepth: number): string[] {
  const lines: string[] = [];
  if (Array.isArray(data)) {
    if (data.length === 0) {
      pushDepthCallout(lines, startDepth, "json-section", ["Value", "", "_Empty array_"]);
      return lines;
    }
    data.forEach((item, index) => {
      if (index > 0) lines.push("");
      appendJsonValue(lines, `${rootLabel} ${index + 1}`, item, startDepth);
    });
    return lines;
  }

  if (data !== null && typeof data === "object") {
    const entries = Object.entries(data);
    if (entries.length === 0) {
      pushDepthCallout(lines, startDepth, "json-section", ["Value", "", "_Empty object_"]);
      return lines;
    }
    entries.forEach(([key, value], i) => {
      if (i > 0) lines.push("");
      appendJsonValue(lines, key, value, startDepth);
    });
    return lines;
  }

  pushDepthCallout(lines, startDepth, "json-section", ["Value", "", stringifyPrimitive(data)]);
  return lines;
}

function readBalancedJsonBlock(
  lines: string[],
  startLine: number,
): { endLine: number; raw: string; parsed: unknown } | null {
  const first = lines[startLine] ?? "";
  const trimmed = first.trimStart();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
    return null;
  }

  const stack: string[] = [];
  let inString = false;
  let escaped = false;
  let started = false;
  const collected: string[] = [];

  for (let i = startLine; i < lines.length; i += 1) {
    const line = lines[i] ?? "";
    collected.push(line);
    for (let j = 0; j < line.length; j += 1) {
      const ch = line[j];

      if (!started) {
        if (/\s/.test(ch)) {
          continue;
        }
        if (ch !== "{" && ch !== "[") {
          return null;
        }
        started = true;
        stack.push(ch);
        continue;
      }

      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (ch === "\\") {
          escaped = true;
        } else if (ch === '"') {
          inString = false;
        }
        continue;
      }

      if (ch === '"') {
        inString = true;
        continue;
      }

      if (ch === "{" || ch === "[") {
        stack.push(ch);
      } else if (ch === "}" || ch === "]") {
        const top = stack.pop();
        const expected = ch === "}" ? "{" : "[";
        if (top !== expected) return null;
        if (stack.length === 0) {
          let trailingOnlyWhitespace = true;
          for (let k = j + 1; k < line.length; k += 1) {
            if (!/\s/.test(line[k])) {
              trailingOnlyWhitespace = false;
              break;
            }
          }
          if (!trailingOnlyWhitespace) return null;
          const raw = collected.join("\n");
          try {
            return { endLine: i, raw, parsed: JSON.parse(raw) as unknown };
          } catch {
            return null;
          }
        }
      }
    }
  }

  return null;
}

function renderMarkdownWithEmbeddedJson(content: string, baseDepth: number): string {
  const sourceLines = content.split("\n");
  const outputLines: string[] = [];
  let cursor = 0;

  while (cursor < sourceLines.length) {
    const match = readBalancedJsonBlock(sourceLines, cursor);
    if (!match) {
      outputLines.push(sourceLines[cursor] ?? "");
      cursor += 1;
      continue;
    }

    const jsonLines = renderJsonAsMarkdown(match.parsed, "Item", baseDepth + 1);
    pushTransitionCallout(outputLines, baseDepth + 1, "Markdown -> JSON", jsonLines);
    cursor = match.endLine + 1;
  }

  return outputLines.join("\n");
}

function renderJsonOrJsonl(content: string, ext: JsonExt): RenderResult {
  const { data, parseError } = parseJsonContent(content, ext);
  if (parseError) {
    return {
      parseError,
      markdown: [
        "## Render fallback",
        "",
        "JSON 파싱에 실패해 원문을 그대로 표시합니다.",
        "",
        "```text",
        content,
        "```",
      ].join("\n"),
    };
  }

  if (ext === ".jsonl" && Array.isArray(data)) {
    const lines: string[] = [];
    if (data.length === 0) {
      lines.push("_No JSONL records_");
    } else {
      data.forEach((record, index) => {
        if (index > 0) lines.push("");
        const recordBody = renderJsonAsMarkdown(record, `Record ${index + 1}`, 1);
        pushTransitionCallout(lines, 1, "JSON -> Markdown", recordBody);
      });
    }
    return { parseError: null, markdown: lines.join("\n") };
  }

  const body = renderJsonAsMarkdown(data, "Item", 1);
  return { parseError: null, markdown: body.join("\n") };
}

export function renderEverything(content: string, ext: RenderEverythingExt): RenderResult {
  if (ext === ".md") {
    return { parseError: null, markdown: renderMarkdownWithEmbeddedJson(content, 0) };
  }
  return renderJsonOrJsonl(content, ext);
}
