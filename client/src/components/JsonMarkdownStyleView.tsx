import MarkdownView from "./MarkdownView";
import { parseJsonContent, type JsonExt } from "./jsonParse";

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function headingText(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized || "(empty key)";
}

function formatPrimitive(value: unknown): string {
  if (typeof value === "string") {
    return value.length > 0 ? value : "_(empty string)_";
  }
  if (value === null) return "`null`";
  if (typeof value === "number" || typeof value === "boolean") {
    return `\`${String(value)}\``;
  }
  return `\`${JSON.stringify(value)}\``;
}

function appendSection(
  lines: string[],
  title: string,
  value: unknown,
  level: number,
): void {
  const depth = Math.max(1, Math.min(level, 6));
  lines.push(`${"#".repeat(depth)} ${headingText(title)}`);
  lines.push("");

  if (isJsonObject(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) {
      lines.push("_Empty object_");
      lines.push("");
      return;
    }
    for (const [key, child] of entries) {
      appendSection(lines, key, child, depth + 1);
    }
    return;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      lines.push("_Empty array_");
      lines.push("");
      return;
    }
    value.forEach((item, index) => {
      appendSection(lines, `Item ${index + 1}`, item, depth + 1);
    });
    return;
  }

  lines.push(formatPrimitive(value));
  lines.push("");
}

function buildMarkdown(content: string, ext: JsonExt): {
  markdown: string;
  parseError: string | null;
} {
  const { data, parseError } = parseJsonContent(content, ext);
  if (parseError) {
    return { markdown: "", parseError };
  }

  const lines: string[] = [];
  if (ext === ".jsonl" && Array.isArray(data)) {
    if (data.length === 0) {
      lines.push("_No JSONL records_");
      return { markdown: lines.join("\n"), parseError: null };
    }
    data.forEach((record, index) => {
      appendSection(lines, `Record ${index + 1}`, record, 2);
    });
    return { markdown: lines.join("\n"), parseError: null };
  }

  if (isJsonObject(data)) {
    const entries = Object.entries(data);
    if (entries.length === 0) {
      lines.push("_Empty object_");
    } else {
      for (const [key, value] of entries) {
        appendSection(lines, key, value, 1);
      }
    }
  } else if (Array.isArray(data)) {
    if (data.length === 0) {
      lines.push("_Empty array_");
    } else {
      data.forEach((item, index) => {
        appendSection(lines, `Item ${index + 1}`, item, 1);
      });
    }
  } else {
    lines.push(formatPrimitive(data));
  }

  return { markdown: lines.join("\n"), parseError: null };
}

export default function JsonMarkdownStyleView({
  content,
  ext,
}: {
  content: string;
  ext: JsonExt;
}) {
  const { markdown, parseError } = buildMarkdown(content, ext);

  if (parseError) {
    return <div className="error-msg">JSON parse error: {parseError}</div>;
  }

  return <MarkdownView content={markdown} />;
}
