import { JSONTree } from "react-json-tree";
import { parseJsonContent, type JsonExt } from "./jsonParse";

/** VS Code Light+ / base16 — readable on white backgrounds */
const theme = {
  scheme: "vscode-light",
  base00: "transparent",
  base01: "#f3f3f3",
  base02: "#e5e5e5",
  base03: "#6e6e6e",
  base04: "#6e6e6e",
  base05: "#1a1a1a",
  base06: "#1a1a1a",
  base07: "#1a1a1a",
  base08: "#a31515",
  base09: "#098658",
  base0A: "#795e26",
  base0B: "#a31515",
  base0C: "#0070c1",
  base0D: "#0451a5",
  base0E: "#811f3f",
  base0F: "#795e26",
};

export default function JsonTreeView({
  content,
  ext,
}: {
  content: string;
  ext: JsonExt;
}) {
  const { data, parseError } = parseJsonContent(content, ext);

  if (parseError) {
    return <div className="error-msg">JSON parse error: {parseError}</div>;
  }

  return (
    <div className="json-tree-container">
      <JSONTree
        data={data}
        theme={theme}
        invertTheme={false}
        hideRoot
        shouldExpandNodeInitially={(_keyPath, _data, level) => level < 2}
      />
    </div>
  );
}
