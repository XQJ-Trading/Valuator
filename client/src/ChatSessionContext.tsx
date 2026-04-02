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
  clearChatMessages,
  fetchAgentRunning,
  fetchChatMessages,
  postChatMessage,
  postChatStop,
  type ChatMessage,
  type ChatResetEvent,
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
}: {
  children: ReactNode;
  onMessagesUpdated?: () => void;
}) {
  const onMessagesUpdatedRef = useRef(onMessagesUpdated);
  onMessagesUpdatedRef.current = onMessagesUpdated;

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

  useEffect(() => {
    messageIdsRef.current = new Set(messages.map((m) => m.id));
  }, [messages]);

  useEffect(() => {
    let cancelled = false;
    setLoadingList(true);
    fetchChatMessages()
      .then((msgs) => {
        if (cancelled) return;
        setMessages(msgs);
        setLoadError(null);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setLoadError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false);
      });

    void fetchAgentRunning()
      .then((running) => {
        if (!cancelled) setAgentRunning(running);
      })
      .catch(() => {
        /* ignore */
      });

    const es = new EventSource("/api/chat/stream");
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

  const sendMessage = useCallback(
    async (textOverride?: string) => {
      const text = (textOverride ?? draftText).trim();
      if (!text || pending) return;

      setPending(true);
      try {
        const msg = await postChatMessage(text);
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
      await clearChatMessages();
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
      await postChatStop();
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
