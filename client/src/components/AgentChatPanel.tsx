import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
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

type Role = "user" | "assistant";

type ChatMessage = {
  id: string;
  role: Role;
  text: string;
};

type Tab = { id: string; title: string };

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

const WELCOME: ChatMessage = {
  id: "welcome",
  role: "assistant",
  text: "Ask anything. Replies are mocked for this preview.",
};

export default function AgentChatPanel() {
  const baseId = useId();
  const [tabs, setTabs] = useState<Tab[]>([{ id: "t1", title: "Chat" }]);
  const [activeTabId, setActiveTabId] = useState("t1");
  const [messagesByTab, setMessagesByTab] = useState<Record<string, ChatMessage[]>>({
    t1: [WELCOME],
  });
  const [draftText, setDraftText] = useState("");
  const [pending, setPending] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatEditorRef = useRef<ChatEditorHandle>(null);

  const messages = useMemo(
    () => messagesByTab[activeTabId] ?? [],
    [messagesByTab, activeTabId],
  );

  const scrollToBottom = useCallback(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const addTab = () => {
    const id = `t-${uid()}`;
    setTabs((prev) => [...prev, { id, title: `Chat ${prev.length + 1}` }]);
    setMessagesByTab((prev) => ({ ...prev, [id]: [WELCOME] }));
    setActiveTabId(id);
  };

  const closeTab = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setTabs((prev) => {
      if (prev.length <= 1) return prev;
      const next = prev.filter((t) => t.id !== id);
      if (id === activeTabId) {
        const idx = prev.findIndex((t) => t.id === id);
        const fallback = next[Math.max(0, idx - 1)] ?? next[0];
        setActiveTabId(fallback.id);
      }
      return next;
    });
    setMessagesByTab((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const sendMessage = useCallback(
    (textOverride?: string) => {
      const text = (textOverride ?? draftText).trim();
      if (!text || pending) return;

      const userMsg: ChatMessage = { id: uid(), role: "user", text };
      setMessagesByTab((prev) => ({
        ...prev,
        [activeTabId]: [...(prev[activeTabId] ?? []), userMsg],
      }));
      chatEditorRef.current?.clear();
      setPending(true);

      window.setTimeout(() => {
        const mock: ChatMessage = {
          id: uid(),
          role: "assistant",
          text: `[mock] Received: ${text.slice(0, 200)}${text.length > 200 ? "…" : ""}`,
        };
        setMessagesByTab((prev) => ({
          ...prev,
          [activeTabId]: [...(prev[activeTabId] ?? []), mock],
        }));
        setPending(false);
      }, 450);
    },
    [activeTabId, draftText, pending],
  );

  return (
    <div className={styles.root}>
      <div className={styles.tabBar} role="tablist" aria-label="Agent chats">
        <div className={styles.tabScroll}>
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`${baseId}-tab-${t.id}`}
              aria-selected={activeTabId === t.id}
              aria-controls={`${baseId}-panel-${t.id}`}
              className={`${styles.tab} ${activeTabId === t.id ? styles.tabActive : ""}`}
              onClick={() => setActiveTabId(t.id)}
            >
              <span className={styles.tabTitle}>{t.title}</span>
              {tabs.length > 1 && (
                <button
                  type="button"
                  className={styles.tabClose}
                  onClick={(e) => closeTab(e, t.id)}
                  aria-label={`Close ${t.title}`}
                >
                  ×
                </button>
              )}
            </button>
          ))}
        </div>
        <button type="button" className={styles.addTab} onClick={addTab} aria-label="New chat tab">
          +
        </button>
      </div>

      <div
        className={styles.chat}
        role="tabpanel"
        id={`${baseId}-panel-${activeTabId}`}
        aria-labelledby={`${baseId}-tab-${activeTabId}`}
      >
        {messages.length === 0 ? (
          <div className={styles.empty}>No messages yet.</div>
        ) : (
          messages.map((m) => (
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
        )}
        <div ref={chatEndRef} />
      </div>

      <div className={styles.inputBar}>
        <div className={styles.inputRow}>
          <ChatEditor
            ref={chatEditorRef}
            disabled={pending}
            onSubmit={sendMessage}
            onDraftChange={setDraftText}
          />
          <button
            type="button"
            className={styles.send}
            onClick={() => sendMessage()}
            disabled={pending || !draftText.trim()}
          >
            Send
          </button>
        </div>
        <span className={styles.hint}>⌘↵ or Ctrl+↵ to send</span>
      </div>
    </div>
  );
}
