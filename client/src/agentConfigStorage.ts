const STORAGE_KEY = "sessionviewer.agentConfig";

export interface AgentConnectionConfig {
  serverIp: string;
  serverSecret: string;
}

const DEFAULTS: AgentConnectionConfig = {
  serverIp: "",
  serverSecret: "",
};

function parseStored(raw: string | null): AgentConnectionConfig {
  if (!raw) return { ...DEFAULTS };
  try {
    const v = JSON.parse(raw) as unknown;
    if (!v || typeof v !== "object") return { ...DEFAULTS };
    const o = v as Record<string, unknown>;
    return {
      serverIp: typeof o.serverIp === "string" ? o.serverIp : "",
      serverSecret: typeof o.serverSecret === "string" ? o.serverSecret : "",
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function loadAgentConfig(): AgentConnectionConfig {
  try {
    return parseStored(localStorage.getItem(STORAGE_KEY));
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveAgentConfig(config: AgentConnectionConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    /* ignore quota / private mode */
  }
}
