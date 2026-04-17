import { useEffect, useId, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import {
  fetchWebSearchProviders,
  type WebSearchProvider,
} from "../api";
import {
  loadAgentConfig,
  saveAgentConfig,
  type AgentConfig,
} from "../agentConfigStorage";
import styles from "./ConfigView.module.css";

const MODEL_PRESETS = {
  google_genai: ["gemini-3-flash-preview", "gemini-3-pro-preview"],
  openrouter: ["openrouter/auto", "google/gemini-2.5-flash"],
} as const;

export default function ConfigView() {
  const keyId = useId();
  const secretId = useId();
  const webSearchId = useId();
  const backendId = useId();
  const modelId = useId();
  const openrouterKeyId = useId();
  const openrouterBaseUrlId = useId();
  const [draft, setDraft] = useState<AgentConfig>(() => loadAgentConfig());
  const [saved, setSaved] = useState<AgentConfig>(() => loadAgentConfig());
  const [webSearchProviders, setWebSearchProviders] = useState<WebSearchProvider[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const c = loadAgentConfig();
    setDraft(c);
    setSaved(c);
    void fetchWebSearchProviders()
      .then((response) => {
        if (!cancelled) {
          setWebSearchProviders(response.available);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setWebSearchProviders([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setProvidersLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const dirty =
    draft.authKey !== saved.authKey ||
    draft.authSecret !== saved.authSecret ||
    draft.webSearchProvider !== saved.webSearchProvider ||
    draft.llmBackend !== saved.llmBackend ||
    draft.model !== saved.model ||
    draft.openrouterApiKey !== saved.openrouterApiKey ||
    draft.openrouterBaseUrl !== saved.openrouterBaseUrl;

  const selectedProvider = draft.webSearchProvider || webSearchProviders[0] || "";
  const providerUnavailable =
    selectedProvider.length > 0 &&
    !webSearchProviders.some((provider) => provider === selectedProvider);
  const selectedModelOption =
    draft.llmBackend === "openrouter" ? "openrouter" : "gemini-3-flash-preview";

  const persist = () => {
    saveAgentConfig(draft);
    const next = loadAgentConfig();
    setDraft(next);
    setSaved(next);
    setStatus("Saved.");
    window.setTimeout(() => setStatus(null), 2000);
  };

  const modelPresets = MODEL_PRESETS[draft.llmBackend];

  return (
    <Group orientation="horizontal" className="panels">
      <Panel defaultSize="300px" minSize="150px" maxSize="40%">
        <div className="sidebar">
          <div className="sidebar-header">Configuration</div>
          <div className="tree-scroll" aria-hidden="true" />
        </div>
      </Panel>

      <Separator className="resize-handle" />

      <Panel minSize="30%">
        <div className={styles.root}>
          <div className="content-area">
            <div className={styles.form}>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={keyId}>
                  Server auth key
                </label>
                <input
                  id={keyId}
                  className={styles.input}
                  type="text"
                  value={draft.authKey}
                  onChange={(e) => setDraft((d) => ({ ...d, authKey: e.target.value }))}
                  placeholder=""
                  autoComplete="off"
                />
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={secretId}>
                  Server auth secret
                </label>
                <input
                  id={secretId}
                  className={styles.input}
                  type="password"
                  value={draft.authSecret}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, authSecret: e.target.value }))
                  }
                  placeholder=""
                  autoComplete="off"
                />
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={webSearchId}>
                  Web search provider
                </label>
                <select
                  id={webSearchId}
                  className={styles.select}
                  value={selectedProvider}
                  disabled={providersLoading}
                  onChange={(e) =>
                    setDraft((current) => ({
                      ...current,
                      webSearchProvider: e.target.value as AgentConfig["webSearchProvider"],
                    }))
                  }
                >
                  {providersLoading ? (
                    <option value={selectedProvider}>Loading…</option>
                  ) : null}
                  {!providersLoading && webSearchProviders.length === 0 ? (
                    <option value={selectedProvider}>Unavailable</option>
                  ) : null}
                  {providerUnavailable ? (
                    <option value={selectedProvider}>
                      {selectedProvider} (Unavailable)
                    </option>
                  ) : null}
                  {webSearchProviders.includes("perplexity") ? (
                    <option value="perplexity">Perplexity</option>
                  ) : null}
                  {webSearchProviders.includes("tavily") ? (
                    <option value="tavily">Tavily</option>
                  ) : null}
                </select>
                <div className={styles.hint}>
                  저장하지 않으면 전송 시점에 첫 번째 사용 가능한 provider를 사용합니다.
                </div>
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={backendId}>
                  Select model
                </label>
                <select
                  id={backendId}
                  className={styles.select}
                  value={selectedModelOption}
                  onChange={(e) =>
                    setDraft((current) => {
                      const nextOption = e.target.value;
                      const nextBackend: AgentConfig["llmBackend"] =
                        nextOption === "openrouter" ? "openrouter" : "google_genai";
                      let nextModel = current.model;
                      if (nextBackend === "openrouter" && !nextModel.includes("/")) {
                        nextModel = "openrouter/auto";
                      }
                      if (
                        nextBackend === "google_genai" &&
                        nextModel !== "gemini-3-flash-preview"
                      ) {
                        nextModel = "gemini-3-flash-preview";
                      }
                      return {
                        ...current,
                        llmBackend: nextBackend,
                        model: nextModel,
                      };
                    })
                  }
                >
                  <option value="gemini-3-flash-preview">
                    gemini-3-flash-preview
                  </option>
                  <option value="openrouter">OpenRouter</option>
                </select>
                <div className={styles.hint}>
                  기본 선택지는 <code>gemini-3-flash-preview</code>와{" "}
                  <code>OpenRouter</code>입니다.
                </div>
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={modelId}>
                  Selected model
                </label>
                <input
                  id={modelId}
                  className={styles.input}
                  list={`${modelId}-options`}
                  type="text"
                  value={draft.model}
                  onChange={(e) => setDraft((current) => ({ ...current, model: e.target.value }))}
                  placeholder="gemini-3-flash-preview"
                  autoComplete="off"
                />
                <datalist id={`${modelId}-options`}>
                  {modelPresets.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
                <div className={styles.hint}>
                  {draft.llmBackend === "google_genai" ? (
                    <>
                      기본값은 <code>gemini-3-flash-preview</code>입니다.
                    </>
                  ) : (
                    <>
                      OpenRouter 모델은 <code>provider/model</code> 형식으로 입력하세요.
                    </>
                  )}
                </div>
              </div>
              <div
                className={styles.field}
                aria-disabled={draft.llmBackend !== "openrouter"}
              >
                <label className={styles.label} htmlFor={openrouterKeyId}>
                  OpenRouter API key
                </label>
                <input
                  id={openrouterKeyId}
                  className={styles.input}
                  type="password"
                  value={draft.openrouterApiKey}
                  disabled={draft.llmBackend !== "openrouter"}
                  onChange={(e) =>
                    setDraft((current) => ({
                      ...current,
                      openrouterApiKey: e.target.value,
                    }))
                  }
                  placeholder=""
                  autoComplete="off"
                />
                <div className={styles.hint}>
                  OpenRouter를 선택했을 때만 사용합니다.
                </div>
              </div>
              <div
                className={styles.field}
                aria-disabled={draft.llmBackend !== "openrouter"}
              >
                <label className={styles.label} htmlFor={openrouterBaseUrlId}>
                  OpenRouter base URL
                </label>
                <input
                  id={openrouterBaseUrlId}
                  className={styles.input}
                  type="text"
                  value={draft.openrouterBaseUrl}
                  disabled={draft.llmBackend !== "openrouter"}
                  onChange={(e) =>
                    setDraft((current) => ({
                      ...current,
                      openrouterBaseUrl: e.target.value,
                    }))
                  }
                  placeholder="https://openrouter.ai/api/v1"
                  autoComplete="off"
                />
              </div>
              <div className={styles.actions}>
                <button
                  type="button"
                  className={styles.save}
                  onClick={persist}
                  disabled={!dirty}
                >
                  Save
                </button>
                <span className={styles.status} aria-live="polite">
                  {status}
                </span>
              </div>
            </div>
          </div>
        </div>
      </Panel>
    </Group>
  );
}
