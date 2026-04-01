export type JsonExt = ".json" | ".jsonl";

function parseJsonl(content: string): unknown[] {
  return content
    .split("\n")
    .filter((line) => line.trim())
    .map((line, index) => {
      try {
        return JSON.parse(line);
      } catch {
        return { __parse_error: true, line: index + 1, raw: line };
      }
    });
}

export function parseJsonContent(
  content: string,
  ext: JsonExt,
): { data: unknown; parseError: string | null } {
  if (ext === ".jsonl") {
    return { data: parseJsonl(content), parseError: null };
  }

  try {
    return { data: JSON.parse(content), parseError: null };
  } catch (error) {
    return {
      data: null,
      parseError: error instanceof Error ? error.message : "Invalid JSON",
    };
  }
}
