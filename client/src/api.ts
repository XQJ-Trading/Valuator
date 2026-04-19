import { loadAgentConfig } from "./agentConfigStorage";

export type DataSource = "session" | "guide";

export type ActivityView = DataSource | "config" | "developer";

export interface TreeEntry {
  name: string;
  path: string;
  type: "directory" | "file";
  ext: string | null;
}

export interface TreeResponse {
  path: string;
  children: TreeEntry[];
}

export interface FileResponse {
  path: string;
  ext: string;
  size: number;
  content: string;
}

export interface FsMutationResult {
  path: string;
  finalPath: string;
  name: string;
}

export interface SearchResultEntry {
  name: string;
  path: string;
  source: DataSource;
  type: "directory" | "file";
}

export interface SearchResponse {
  results: SearchResultEntry[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  ts: string;
}

export interface ChatResetEvent {
  type: "reset";
  ts: string;
}

export type WebSearchProvider = "perplexity" | "tavily";

export interface WebSearchProviderResponse {
  available: WebSearchProvider[];
}

const CHAT_SESSION_STORAGE_KEY = "chat_session_id";

export function getOrCreateChatSessionId(): string {
  const existing = window.sessionStorage.getItem(CHAT_SESSION_STORAGE_KEY)?.trim();
  if (existing) return existing;
  const sessionId = window.crypto.randomUUID();
  window.sessionStorage.setItem(CHAT_SESSION_STORAGE_KEY, sessionId);
  return sessionId;
}

function authHeaders(): Record<string, string> {
  const cfg = loadAgentConfig();
  return {
    "X-Auth-Key": encodeURIComponent(cfg.authKey),
    "X-Auth-Secret": encodeURIComponent(cfg.authSecret),
  };
}

function chatApiPath(path: string, sessionId: string): string {
  const q = new URLSearchParams({ session_id: sessionId });
  return `${path}?${q.toString()}`;
}

export function chatStreamPath(sessionId: string): string {
  const q = new URLSearchParams({ session_id: sessionId });
  return `/api/chat/stream?${q.toString()}`;
}

export async function authenticateSession(sessionId: string): Promise<void> {
  const q = new URLSearchParams({ session_id: sessionId });
  const res = await fetch(`/api/chat/authenticate?${q}`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
}

export async function fetchChatMessages(sessionId: string): Promise<ChatMessage[]> {
  const res = await fetch(chatApiPath("/api/chat/messages", sessionId), {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  const data = (await res.json()) as { messages: ChatMessage[] };
  return data.messages;
}

export async function postChatMessage(
  sessionId: string,
  text: string,
  webSearchProvider: WebSearchProvider | "",
): Promise<ChatMessage> {
  const res = await fetch(chatApiPath("/api/chat/messages", sessionId), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(
      webSearchProvider
        ? { text, web_search_provider: webSearchProvider }
        : { text },
    ),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  return res.json() as Promise<ChatMessage>;
}

export async function fetchWebSearchProviders(): Promise<WebSearchProviderResponse> {
  const res = await fetch("/api/chat/web-search-providers", {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  return res.json() as Promise<WebSearchProviderResponse>;
}

export async function clearChatMessages(sessionId: string): Promise<void> {
  const res = await fetch(chatApiPath("/api/chat/messages", sessionId), {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
}

export async function postChatStop(
  sessionId: string,
): Promise<{ ok: boolean; stopped: boolean }> {
  const res = await fetch(chatApiPath("/api/chat/stop", sessionId), {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  return res.json() as Promise<{ ok: boolean; stopped: boolean }>;
}

export async function fetchAgentRunning(sessionId: string): Promise<boolean> {
  const res = await fetch(chatApiPath("/api/chat/agent-status", sessionId), {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  const data = (await res.json()) as { running?: boolean };
  return Boolean(data.running);
}

export async function fetchSessionDefaultExplore(): Promise<{
  sessionFolder: string | null;
  browsePath: string | null;
}> {
  const res = await fetch("/api/session/default-explore", {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  return res.json() as Promise<{
    sessionFolder: string | null;
    browsePath: string | null;
  }>;
}

export interface BrowseOutlineRow {
  depth: number;
  relPath: string;
  title: string;
}

/** Returns browse outline; optional rebuild from tasks when ensureBrowse is true (can be slow). */
export async function fetchBrowseOutline(
  source: DataSource,
  sessionFolder?: string | null,
  options?: { ensureBrowse?: boolean },
): Promise<{
  sessionFolder: string | null;
  browseRootPath: string | null;
  browseBuilt: boolean;
  rows: BrowseOutlineRow[];
}> {
  const q = new URLSearchParams({ source });
  const s = sessionFolder?.trim();
  if (s) q.set("session", s);
  if (options?.ensureBrowse) q.set("ensure_browse", "true");
  const res = await fetch(`/api/session/browse-outline?${q}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  return res.json() as Promise<{
    sessionFolder: string | null;
    browseRootPath: string | null;
    browseBuilt: boolean;
    rows: BrowseOutlineRow[];
  }>;
}

function sourceParam(source: DataSource): string {
  return `source=${encodeURIComponent(source)}`;
}

async function parseErrorBody(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as {
      error?: string;
      detail?: string | Array<{ msg?: string }>;
    };
    if (body.error) {
      return body.error;
    }
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail)) {
      const first = body.detail.find((entry) => typeof entry?.msg === "string");
      if (first?.msg) {
        return first.msg;
      }
    }
    return `request ${res.status}`;
  } catch {
    return `request ${res.status}`;
  }
}

export async function searchFiles(query: string, limit = 5): Promise<SearchResponse> {
  const q = encodeURIComponent(query);
  const res = await fetch(`/api/search?q=${q}&limit=${limit}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  return res.json();
}

export async function fetchTree(relPath: string, source: DataSource): Promise<TreeResponse> {
  const res = await fetch(
    `/api/tree?${sourceParam(source)}&path=${encodeURIComponent(relPath)}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(await parseErrorBody(res));
  return res.json();
}

export async function fetchFile(relPath: string, source: DataSource): Promise<FileResponse> {
  const res = await fetch(
    `/api/file?${sourceParam(source)}&path=${encodeURIComponent(relPath)}`,
    { headers: authHeaders() },
  );
  if (!res.ok) {
    throw new Error(await parseErrorBody(res));
  }
  return res.json();
}

export async function saveFile(
  relPath: string,
  source: DataSource,
  content: string,
): Promise<FileResponse> {
  const res = await fetch("/api/file", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ source, path: relPath, content }),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  return res.json();
}

async function postFs(
  path: string,
  source: DataSource,
  body: Record<string, unknown>,
): Promise<FsMutationResult> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ source, ...body }),
  });
  if (!res.ok) throw new Error(await parseErrorBody(res));
  return res.json();
}

export function createEntry(
  source: DataSource,
  parentPath: string,
  name: string,
  kind: "file" | "directory",
): Promise<FsMutationResult> {
  return postFs("/api/fs/create", source, { parentPath, name, kind });
}

export function renameEntry(
  source: DataSource,
  path: string,
  newName: string,
): Promise<FsMutationResult> {
  return postFs("/api/fs/rename", source, { path, newName });
}

export function deleteEntry(source: DataSource, path: string): Promise<FsMutationResult> {
  return postFs("/api/fs/delete", source, { path });
}

export function moveEntry(
  source: DataSource,
  path: string,
  targetDirPath: string,
): Promise<FsMutationResult> {
  return postFs("/api/fs/move", source, { path, targetDirPath });
}

export function copyEntry(
  source: DataSource,
  path: string,
  targetDirPath: string,
): Promise<FsMutationResult> {
  return postFs("/api/fs/copy", source, { path, targetDirPath });
}
