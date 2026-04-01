import { Children, isValidElement, type CSSProperties, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function flattenText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(flattenText).join("");
  }
  if (node && typeof node === "object" && "props" in node) {
    const child = (node as { props?: { children?: ReactNode } }).props?.children;
    return flattenText(child ?? "");
  }
  return "";
}

/** GFM parses `[depth:...]` as a link/reference; use bracketless `depth:n:type` in source. */
function parseDepthMarker(text: string): { depth: number; type: string } | null {
  const t = text.trim();
  const bare = t.match(/^depth:(\d+):(transition|json-section)$/);
  if (bare) return { depth: Number(bare[1]), type: bare[2] };
  const bracketed = t.match(/^\[depth:(\d+):(transition|json-section)\]$/);
  if (bracketed) return { depth: Number(bracketed[1]), type: bracketed[2] };
  return null;
}

function isParagraphElement(node: unknown): boolean {
  return isValidElement(node) && String(node.type) === "p";
}

function tryExtractDepthFromBlockquoteChildren(children: ReactNode): {
  depth: number;
  calloutType: string;
  rest: ReactNode[];
} | null {
  const arr = Children.toArray(children);
  for (let i = 0; i < Math.min(arr.length, 4); i += 1) {
    const el = arr[i];
    if (!isParagraphElement(el)) continue;
    const text = flattenText(
      (el as { props?: { children?: ReactNode } }).props?.children,
    ).trim();
    const parsed = parseDepthMarker(text);
    if (parsed) {
      return {
        depth: parsed.depth,
        calloutType: parsed.type,
        rest: [...arr.slice(0, i), ...arr.slice(i + 1)],
      };
    }
  }
  return null;
}

export default function MarkdownView({ content }: { content: string }) {
  return (
    <div className="md-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          blockquote: ({ children }) => {
            const extracted = tryExtractDepthFromBlockquoteChildren(children);
            if (!extracted) {
              return <blockquote>{children}</blockquote>;
            }
            const { depth, calloutType, rest } = extracted;
            const style: CSSProperties = {
              "--depth": depth,
            } as CSSProperties;
            return (
              <blockquote
                className="md-depth-callout"
                data-depth={depth}
                data-callout-type={calloutType}
                style={style}
              >
                {rest}
              </blockquote>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
