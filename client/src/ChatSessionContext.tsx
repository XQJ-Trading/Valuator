import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  chatStreamPath,
  clearChatMessages,
  fetchAgentRunning,
  fetchChatMessages,
  fetchFile,
  getOrCreateChatSessionId,
  postChatMessage,
  postChatStop,
  type ChatMessage,
  type ChatResetEvent,
  type DataSource,
} from "./api";
import { parseProgressLine } from "./chatProgressParse";

export type StepFlowSnapshot = {
  taskId: string;
  taskName?: string;
  globalSeq?: number;
  localStep?: number;
  description: string;
};

function isChatResetEvent(payload: ChatMessage | ChatResetEvent): payload is ChatResetEvent {
  return (payload as ChatResetEvent).type === "reset";
}

export type ChatSessionContextValue = {
  messages: ChatMessage[];
  loadingList: boolean;
  loadError: string | null;
  pending: boolean;
  agentRunning: boolean;
  activeTaskIds: string[];
  taskDisplayNames: Map<string, string>;
  taskDescriptions: Map<string, string>;
  sendMessage: (textOverride?: string) => Promise<void>;
  clearMessages: () => Promise<void>;
  stopAgent: () => Promise<void>;
  draftText: string;
  setDraftText: (s: string) => void;
  /** Latest agent step line (gN/lN + task) for the center status bar. */
  lastStepFlow: StepFlowSnapshot | null;
};

const ChatSessionContext = createContext<ChatSessionContextValue | null>(null);

export function ChatSessionProvider({
  children,
  onMessagesUpdated,
  onBrowseOutlineRefresh,
}: {
  children: ReactNode;
  onMessagesUpdated?: () => void;
  /** When browse/ may have changed (agent finished or chat reset); not every message tick. */
  onBrowseOutlineRefresh?: () => void;
}) {
  const onMessagesUpdatedRef = useRef(onMessagesUpdated);
  onMessagesUpdatedRef.current = onMessagesUpdated;
  const onBrowseOutlineRefreshRef = useRef(onBrowseOutlineRefresh);
  onBrowseOutlineRefreshRef.current = onBrowseOutlineRefresh;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draftText, setDraftText] = useState("");
  const [pending, setPending] = useState(false);
  const [agentRunning, setAgentRunning] = useState(false);
  const [taskDescriptions, setTaskDescriptions] = useState<Map<string, string>>(new Map());
  const [taskDisplayNames, setTaskDisplayNames] = useState<Map<string, string>>(new Map());
  const [activeTaskIds, setActiveTaskIds] = useState<string[]>([]);
  const [lastStepFlow, setLastStepFlow] = useState<StepFlowSnapshot | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const messageIdsRef = useRef<Set<string>>(new Set());
  const chatSessionIdRef = useRef<string>(getOrCreateChatSessionId());

  useEffect(() => {
    messageIdsRef.current = new Set(messages.map((m) => m.id));
  }, [messages]);

  useEffect(() => {
    let cancelled = false;
    const chatSessionId = chatSessionIdRef.current;
    setLoadingList(true);
    fetchChatMessages(chatSessionId)
      .then((msgs) => {
        if (cancelled) return;
        const uniqueMessages = msgs.reduce(
          (acc, msg) => {
            if (!messageIdsRef.current.has(msg.id)) {
              acc.push(msg);
              messageIdsRef.current.add(msg.id);
            }
            return acc;
          },
          [] as ChatMessage[],
        );
        setMessages((prev) => [...prev, ...uniqueMessages]);
        setLoadError(null);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setLoadError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false);
      });

    void fetchAgentRunning(chatSessionId)
      .then((running) => {
        if (!cancelled) setAgentRunning(running);
      })
      .catch(() => {
        /* ignore */
      });

    const es = new EventSource(chatStreamPath(chatSessionId));
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data) as ChatMessage | ChatResetEvent | Record<string, unknown>;
        if (isChatResetEvent(payload as ChatMessage | ChatResetEvent)) {
          messageIdsRef.current = new Set();
          setMessages([]);
          setActiveTaskIds([]);
          setTaskDisplayNames(new Map());
          setTaskDescriptions(new Map());
          setAgentRunning(false);
          setLastStepFlow(null);
          onMessagesUpdatedRef.current?.();
          onBrowseOutlineRefreshRef.current?.();
          return;
        }
        const typed = payload as { type?: string };
        if (typed.type === "agent_started") {
          setAgentRunning(true);
          setLastStepFlow(null);
          return;
        }
        if (typed.type === "agent_finished") {
          setAgentRunning(false);
          setLastStepFlow(null);
          onBrowseOutlineRefreshRef.current?.();
          return;
        }
        if (typed.type === "task_progress") {
          const raw = (payload as { line: string }).line;
          const item = parseProgressLine(raw);
          if (item.kind === "step") {
            if (item.description) {
              setTaskDescriptions((prev) => new Map(prev).set(item.taskId, item.description));
            }
            const displayName = item.taskName;
            if (displayName) {
              setTaskDisplayNames((prev) => new Map(prev).set(item.taskId, displayName));
            }
            setLastStepFlow({
              taskId: item.taskId,
              taskName: item.taskName,
              globalSeq: item.globalSeq,
              localStep: item.localStep,
              description: item.description,
            });
            setActiveTaskIds((prev) =>
              prev.includes(item.taskId) ? prev : [...prev, item.taskId],
            );
          } else if (item.kind === "done" || item.kind === "failed") {
            setActiveTaskIds((prev) => prev.filter((id) => id !== item.taskId));
            onMessagesUpdatedRef.current?.();
          }
          return;
        }
        const msg = payload as ChatMessage;
        if (typeof msg.id !== "string" || !msg.id || (msg.role !== "user" && msg.role !== "assistant")) {
          return;
        }
        if (messageIdsRef.current.has(msg.id)) return;
        messageIdsRef.current.add(msg.id);
        setMessages((prev) => [...prev, msg]);
        if (msg.role === "assistant") {
          setActiveTaskIds([]);
          setTaskDisplayNames(new Map());
        }
        onMessagesUpdatedRef.current?.();
      } catch {
        /* ignore malformed SSE */
      }
    };

    return () => {
      cancelled = true;
      es.close();
    };
  }, []);

  const expandMentions = async (text: string): Promise<string> => {
    const TOKEN = /@\[(session|guide):([^\]]+)\]/g;
    const matches = [...text.matchAll(TOKEN)];
    if (matches.length === 0) return text;

    // Deduplicate by "source:path" key
    const seen = new Set<string>();
    const refs: { source: DataSource; path: string }[] = [];
    for (const [, source, path] of matches) {
      const key = `${source}:${path}`;
      if (!seen.has(key)) {
        seen.add(key);
        refs.push({ source: source as DataSource, path });
      }
    }

    const blocks = await Promise.all(
      refs.map(async ({ source, path }) => {
        const file = await fetchFile(path, source);
        return `* ${source}:${path}\n\`\`\`md\n${file.content}\n\`\`\``;
      }),
    );

    return `# REFERENCE\n${blocks.join("\n\n")}\n\n# QUERY\n${text}`;
  };

  const sendMessage = useCallback(
    async (textOverride?: string) => {
      const chatSessionId = chatSessionIdRef.current;
      const text = (textOverride ?? draftText).trim();
      if (!text || pending) return;

      setPending(true);
      try {
        const expanded = await expandMentions(text);
        const msg = await postChatMessage(chatSessionId, expanded);
        if (!messageIdsRef.current.has(msg.id)) {
          messageIdsRef.current.add(msg.id);
          setMessages((prev) => [...prev, msg]);
          onMessagesUpdatedRef.current?.();
        }
        setDraftText("");
      } catch (e) {
        console.error(e);
        alert(e instanceof Error ? e.message : "Send failed");
      } finally {
        setPending(false);
      }
    },
    [draftText, pending],
  );

  const clearMessages = useCallback(async () => {
    if (pending || loadingList) return;
    const confirmed = window.confirm("채팅 세션을 초기화할까요? 기존 메시지는 삭제됩니다.");
    if (!confirmed) return;
    try {
      await clearChatMessages(chatSessionIdRef.current);
      messageIdsRef.current = new Set();
      setMessages([]);
      onMessagesUpdatedRef.current?.();
    } catch (e) {
      console.error(e);
      alert(e instanceof Error ? e.message : "Clear failed");
    }
  }, [loadingList, pending]);

  const stopAgent = useCallback(async () => {
    if (!agentRunning) return;
    try {
      await postChatStop(chatSessionIdRef.current);
    } catch (e) {
      console.error(e);
      alert(e instanceof Error ? e.message : "Stop failed");
    }
  }, [agentRunning]);

  const value = useMemo<ChatSessionContextValue>(
    () => ({
      messages,
      loadingList,
      loadError,
      pending,
      agentRunning,
      activeTaskIds,
      taskDisplayNames,
      taskDescriptions,
      sendMessage,
      clearMessages,
      stopAgent,
      draftText,
      setDraftText,
      lastStepFlow,
    }),
    [
      messages,
      loadingList,
      loadError,
      pending,
      agentRunning,
      activeTaskIds,
      taskDisplayNames,
      taskDescriptions,
      sendMessage,
      clearMessages,
      stopAgent,
      draftText,
      lastStepFlow,
    ],
  );

  return <ChatSessionContext.Provider value={value}>{children}</ChatSessionContext.Provider>;
}

export function useChatSession(): ChatSessionContextValue {
  const c = useContext(ChatSessionContext);
  if (!c) {
    throw new Error("useChatSession must be used within ChatSessionProvider");
  }
  return c;
}
