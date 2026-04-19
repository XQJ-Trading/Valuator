const STORAGE_KEY = "sessionviewer.agentConfig";
const DEFAULT_MODEL = "gemini-3-flash-preview";

export type SavedWebSearchProvider = "" | "perplexity" | "tavily";
export type SavedLlmBackend = "google_genai" | "openrouter";

export interface AgentConfig {
  authKey: string;
  authSecret: string;
  webSearchProvider: SavedWebSearchProvider;
  llmBackend: SavedLlmBackend;
  model: string;
  /** 모델 추가(입력칸) UI를 켠 상태. 저장되어 Save 이후에도 유지된다. */
  customModelUiOpen: boolean;
}

const DEFAULTS: AgentConfig = {
  authKey: "",
  authSecret: "",
  webSearchProvider: "",
  llmBackend: "google_genai",
  model: DEFAULT_MODEL,
  customModelUiOpen: false,
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
    const customModelUiOpen = o.customModelUiOpen === true;
    return {
      authKey: typeof o.authKey === "string" ? o.authKey : "",
      authSecret: typeof o.authSecret === "string" ? o.authSecret : "",
      webSearchProvider,
      llmBackend,
      model,
      customModelUiOpen,
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
    const model = config.model.trim() || DEFAULTS.model;
    const llmBackend =
      config.llmBackend === "openrouter" ? "openrouter" : DEFAULTS.llmBackend;
    const isPresetModel =
      (llmBackend === "google_genai" && model === DEFAULT_MODEL) ||
      (llmBackend === "openrouter" && model === "openrouter/auto");
    const customModelUiOpen =
      !isPresetModel && config.customModelUiOpen === true ? true : false;
    const payload: AgentConfig = {
      authKey: config.authKey,
      authSecret: config.authSecret,
      webSearchProvider:
        config.webSearchProvider === "perplexity" ||
        config.webSearchProvider === "tavily"
          ? config.webSearchProvider
          : DEFAULTS.webSearchProvider,
      llmBackend,
      model,
      customModelUiOpen,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* ignore quota / private mode */
  }
}
