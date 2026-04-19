import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { MentionsInput, Mention } from "react-mentions";
import type { SuggestionDataItem } from "react-mentions";
import { fetchMentionItems } from "./mentionSuggestionConfig";
import { renderMentionItem, type FileMentionItem } from "./MentionSuggestion";
import styles from "./ChatEditor.module.css";

export type ChatEditorHandle = {
  clear: () => void;
};

// react-mentions stores markup as @[display](id); convert to @[id] before sending
const toSendFormat = (v: string) =>
  v.replace(/@\[([^\]]*?)\]\(([^)]*?)\)/g, "@[$2]");

const ChatEditor = forwardRef<
  ChatEditorHandle,
  {
    disabled?: boolean;
    onSubmit: (plainText: string) => void;
    onDraftChange?: (plainText: string) => void;
  }
>(function ChatEditor({ disabled, onSubmit, onDraftChange }, ref) {
  const [value, setValue] = useState("");
  const valueRef = useRef("");
  const onSubmitRef = useRef(onSubmit);
  const onDraftChangeRef = useRef(onDraftChange);

  useEffect(() => { onSubmitRef.current = onSubmit; }, [onSubmit]);
  useEffect(() => { onDraftChangeRef.current = onDraftChange; }, [onDraftChange]);

  useImperativeHandle(ref, () => ({
    clear: () => {
      setValue("");
      valueRef.current = "";
      onDraftChangeRef.current?.("");
    },
  }));

  const handleChange = (
    _e: { target: { value: string } },
    newValue: string,
    newPlainTextValue: string,
  ) => {
    setValue(newValue);
    valueRef.current = newValue;
    // Pass send-format so AgentChatPanel draft state contains the final text
    onDraftChangeRef.current?.(
      newPlainTextValue.trim() ? toSendFormat(newValue) : "",
    );
  };

  const handleKeyDown = (
    e: React.KeyboardEvent<HTMLTextAreaElement> | React.KeyboardEvent<HTMLInputElement>,
  ) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const text = toSendFormat(valueRef.current).trim();
      if (text) onSubmitRef.current(text);
    }
  };

  const fetchSuggestions = async (
    query: string,
    callback: (data: SuggestionDataItem[]) => void,
  ) => {
    const items = await fetchMentionItems(query);
    callback(items.map((item) => ({ ...item, display: item.label })));
  };

  return (
    <div className={styles.wrap}>
      <MentionsInput
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="Message…"
        spellCheck={false}
        allowSuggestionsAboveCursor
        suggestionsPortalHost={document.body}
        className={`react-mentions ${styles.mentionsInput}`}
        style={{ highlighter: { border: 'none' } }}
        a11ySuggestionsListLabel="File mentions"
      >
        <Mention
          trigger="@"
          data={fetchSuggestions}
          markup="@[__display__](__id__)"
          displayTransform={(_id, display) => `@${display}`}
          renderSuggestion={(suggestion, _search, _highlightedDisplay, _index, focused) =>
            renderMentionItem(suggestion as unknown as FileMentionItem, focused)
          }
          className={styles.mention}
          appendSpaceOnAdd
        />
      </MentionsInput>
    </div>
  );
});

ChatEditor.displayName = "ChatEditor";

export default ChatEditor;
