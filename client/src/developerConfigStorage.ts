const STORAGE_KEY = "sessionviewer.developerConfig";

export interface DeveloperConfig {
  remoteUrl: string;
  remoteAuthKey: string;
  remoteAuthSecret: string;
}

const DEFAULTS: DeveloperConfig = {
  remoteUrl: "",
  remoteAuthKey: "",
  remoteAuthSecret: "",
};

function parseStored(raw: string | null): DeveloperConfig {
  if (!raw) return { ...DEFAULTS };
  try {
    const v = JSON.parse(raw) as unknown;
    if (!v || typeof v !== "object") return { ...DEFAULTS };
    const o = v as Record<string, unknown>;
    return {
      remoteUrl: typeof o.remoteUrl === "string" ? o.remoteUrl : "",
      remoteAuthKey: typeof o.remoteAuthKey === "string" ? o.remoteAuthKey : "",
      remoteAuthSecret: typeof o.remoteAuthSecret === "string" ? o.remoteAuthSecret : "",
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function loadDeveloperConfig(): DeveloperConfig {
  try {
    return parseStored(localStorage.getItem(STORAGE_KEY));
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveDeveloperConfig(config: DeveloperConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    /* ignore quota / private mode */
  }
}
