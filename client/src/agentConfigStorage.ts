const STORAGE_KEY = "sessionviewer.agentConfig";
const DEFAULT_MODEL = "gemini-3-flash-preview";
const DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";

export type SavedWebSearchProvider = "" | "perplexity" | "tavily";
export type SavedLlmBackend = "google_genai" | "openrouter";

export interface AgentConfig {
  authKey: string;
  authSecret: string;
  webSearchProvider: SavedWebSearchProvider;
  llmBackend: SavedLlmBackend;
  model: string;
  openrouterApiKey: string;
  openrouterBaseUrl: string;
}

const DEFAULTS: AgentConfig = {
  authKey: "",
  authSecret: "",
  webSearchProvider: "",
  llmBackend: "google_genai",
  model: DEFAULT_MODEL,
  openrouterApiKey: "",
  openrouterBaseUrl: DEFAULT_OPENROUTER_BASE_URL,
};

function parseStored(raw: string | null): AgentConfig {
  if (!raw) return { ...DEFAULTS };
  try {
    const v = JSON.parse(raw) as unknown;
    if (!v || typeof v !== "object") return { ...DEFAULTS };
    const o = v as Record<string, unknown>;
    const webSearchProvider =
      o.webSearchProvider === "perplexity" || o.webSearchProvider === "tavily"
        ? o.webSearchProvider
        : DEFAULTS.webSearchProvider;
    const llmBackend =
      o.llmBackend === "openrouter" ? "openrouter" : DEFAULTS.llmBackend;
    const model =
      typeof o.model === "string" && o.model.trim()
        ? o.model.trim()
        : DEFAULTS.model;
    const openrouterApiKey =
      typeof o.openrouterApiKey === "string" ? o.openrouterApiKey.trim() : "";
    const openrouterBaseUrl =
      typeof o.openrouterBaseUrl === "string" && o.openrouterBaseUrl.trim()
        ? o.openrouterBaseUrl.trim()
        : DEFAULTS.openrouterBaseUrl;
    return {
      authKey: typeof o.authKey === "string" ? o.authKey : "",
      authSecret: typeof o.authSecret === "string" ? o.authSecret : "",
      webSearchProvider,
      llmBackend,
      model,
      openrouterApiKey,
      openrouterBaseUrl,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function loadAgentConfig(): AgentConfig {
  try {
    return parseStored(localStorage.getItem(STORAGE_KEY));
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveAgentConfig(config: AgentConfig): void {
  try {
    const payload: AgentConfig = {
      authKey: config.authKey,
      authSecret: config.authSecret,
      webSearchProvider:
        config.webSearchProvider === "perplexity" ||
        config.webSearchProvider === "tavily"
          ? config.webSearchProvider
          : DEFAULTS.webSearchProvider,
      llmBackend:
        config.llmBackend === "openrouter" ? "openrouter" : DEFAULTS.llmBackend,
      model: config.model.trim() || DEFAULTS.model,
      openrouterApiKey: config.openrouterApiKey.trim(),
      openrouterBaseUrl:
        config.openrouterBaseUrl.trim() || DEFAULTS.openrouterBaseUrl,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* ignore quota / private mode */
  }
}
