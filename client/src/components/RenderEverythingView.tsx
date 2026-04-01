import MarkdownView from "./MarkdownView";
import { renderEverything, type RenderEverythingExt } from "./renderEverything";

export default function RenderEverythingView({
  content,
  ext,
}: {
  content: string;
  ext: RenderEverythingExt;
}) {
  const { markdown, parseError } = renderEverything(content, ext);

  return (
    <>
      {parseError ? (
        <div className="status-msg" style={{ paddingBottom: 0 }}>
          Render-Everything fallback: {parseError}
        </div>
      ) : null}
      <MarkdownView content={markdown} />
    </>
  );
}
