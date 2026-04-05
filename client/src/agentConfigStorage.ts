const STORAGE_KEY = "sessionviewer.agentConfig";

export interface AgentConnectionConfig {
  authKey: string;
  authSecret: string;
}

const DEFAULTS: AgentConnectionConfig = {
  authKey: "",
  authSecret: "",
};

function parseStored(raw: string | null): AgentConnectionConfig {
  if (!raw) return { ...DEFAULTS };
  try {
    const v = JSON.parse(raw) as unknown;
    if (!v || typeof v !== "object") return { ...DEFAULTS };
    const o = v as Record<string, unknown>;
    return {
      authKey: typeof o.authKey === "string" ? o.authKey : "",
      authSecret: typeof o.authSecret === "string" ? o.authSecret : "",
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
