import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { useChatSession } from "../ChatSessionContext";
import type { ChatMessage } from "../api";
import ChatEditor, { type ChatEditorHandle } from "./ChatEditor";
import styles from "./AgentChatPanel.module.css";

const MENTION_TOKEN = /@\[(session|guide):([^\]]+)\]/g;

function MessageContent({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  let mi = 0;
  for (const m of text.matchAll(MENTION_TOKEN)) {
    const start = m.index ?? 0;
    if (start > last) {
      parts.push(text.slice(last, start));
    }
    parts.push(
      <span key={`m-${mi++}`} className={styles.mentionToken}>
        {m[0]}
      </span>,
    );
    last = start + m[0].length;
  }
  if (last < text.length) {
    parts.push(text.slice(last));
  }
  return <>{parts.length ? parts : text}</>;
}

function sortByTs(a: ChatMessage, b: ChatMessage): number {
  return a.ts.localeCompare(b.ts);
}

export default function AgentChatPanel() {
  const baseId = useId();
  const {
    messages,
    loadingList,
    loadError,
    pending,
    sendMessage: sendSessionMessage,
    clearMessages,
    draftText,
    setDraftText,
  } = useChatSession();

  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatEditorRef = useRef<ChatEditorHandle>(null);

  const handleSubmit = useCallback(
    async (textOverride?: string) => {
      await sendSessionMessage(textOverride);
      chatEditorRef.current?.clear();
    },
    [sendSessionMessage],
  );

  const sortedMessages = useMemo(
    () => [...messages].sort(sortByTs),
    [messages],
  );

  const scrollToBottom = useCallback(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [sortedMessages, scrollToBottom]);

  return (
    <div className={styles.root}>
      <div className={styles.chatHeader} id={`${baseId}-heading`}>
        <span>Chat</span>
        <button
          type="button"
          className={styles.clear}
          onClick={() => void clearMessages()}
          disabled={pending || loadingList}
        >
          초기화
        </button>
      </div>

      <div
        className={styles.chat}
        role="region"
        aria-labelledby={`${baseId}-heading`}
      >
        {loadingList ? <div className={styles.empty}>Loading…</div> : null}
        {!loadingList && loadError ? (
          <div className={styles.loadError} title={loadError}>
            {loadError}
          </div>
        ) : null}
        {!loadingList && !loadError && sortedMessages.length === 0 ? (
          <div className={styles.empty}>메시지를 입력하면 서버에 동기화되고, 이 브라우저와 다른 탭에서도 실시간으로 보입니다.</div>
        ) : null}
        {!loadingList && !loadError
          ? sortedMessages.map((m) => (
              <div
                key={m.id}
                className={`${styles.msg} ${m.role === "user" ? styles.msgUser : styles.msgAssistant}`}
              >
                <span className={styles.msgLabel}>{m.role === "user" ? "You" : "Agent"}</span>
                <div className={styles.msgBubble}>
                  <MessageContent text={m.text} />
                </div>
              </div>
            ))
          : null}
        <div ref={chatEndRef} />
      </div>

      <div className={styles.inputBar}>
        <div className={styles.inputRow}>
          <ChatEditor
            ref={chatEditorRef}
            disabled={pending || loadingList}
            onSubmit={handleSubmit}
            onDraftChange={setDraftText}
          />
          <button
            type="button"
            className={styles.send}
            onClick={() => void handleSubmit()}
            disabled={pending || loadingList || !draftText.trim()}
          >
            Send
          </button>
        </div>
        <span className={styles.hint}>⌘↵ or Ctrl+↵ to send</span>
      </div>
    </div>
  );
}
