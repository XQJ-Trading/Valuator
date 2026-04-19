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

type ModelPick =
  | "gemini-3-flash-preview"
  | "openrouter"
  | "saved_custom"
  | "add_model";

function hasNonPresetModel(c: AgentConfig): boolean {
  return (
    (c.llmBackend === "google_genai" && c.model !== "gemini-3-flash-preview") ||
    (c.llmBackend === "openrouter" && c.model !== "openrouter/auto")
  );
}

function deriveModelPick(c: AgentConfig): ModelPick {
  if (c.customModelUiOpen === true) {
    return "add_model";
  }
  if (hasNonPresetModel(c)) {
    return "saved_custom";
  }
  return c.llmBackend === "openrouter" ? "openrouter" : "gemini-3-flash-preview";
}

export default function ConfigView() {
  const keyId = useId();
  const secretId = useId();
  const webSearchId = useId();
  const backendId = useId();
  const modelId = useId();
  const [draft, setDraft] = useState<AgentConfig>(() => loadAgentConfig());
  const [saved, setSaved] = useState<AgentConfig>(() => loadAgentConfig());
  const [webSearchProviders, setWebSearchProviders] = useState<WebSearchProvider[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [modelPick, setModelPick] = useState<ModelPick>(() =>
    deriveModelPick(loadAgentConfig()),
  );

  useEffect(() => {
    let cancelled = false;
    const c = loadAgentConfig();
    setDraft(c);
    setSaved(c);
    setModelPick(deriveModelPick(c));
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
    draft.customModelUiOpen !== saved.customModelUiOpen;

  const selectedProvider = draft.webSearchProvider || webSearchProviders[0] || "";
  const providerUnavailable =
    selectedProvider.length > 0 &&
    !webSearchProviders.some((provider) => provider === selectedProvider);
  const persist = () => {
    const nonPreset = hasNonPresetModel(draft);
    const toSave =
      nonPreset && draft.customModelUiOpen
        ? { ...draft, customModelUiOpen: false }
        : draft;
    saveAgentConfig(toSave);
    const next = loadAgentConfig();
    setDraft(next);
    setSaved(next);
    setModelPick(deriveModelPick(next));
    setStatus("Saved.");
    window.setTimeout(() => setStatus(null), 2000);
  };

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
                <div className={styles.label}>Select model</div>
                <div className={styles.modelBlock}>
                  <select
                    id={backendId}
                    className={styles.select}
                    value={modelPick}
                    aria-label="LLM backend and model mode"
                    onChange={(e) => {
                      const nextOption = e.target.value;
                      if (nextOption === "add_model") {
                        setModelPick("add_model");
                        setDraft((d) => ({ ...d, customModelUiOpen: true }));
                        return;
                      }
                      if (nextOption === "saved_custom") {
                        setModelPick("saved_custom");
                        setDraft((d) => ({ ...d, customModelUiOpen: false }));
                        return;
                      }
                      setModelPick(nextOption as "gemini-3-flash-preview" | "openrouter");
                      setDraft((current) => {
                        if (nextOption === "gemini-3-flash-preview") {
                          return {
                            ...current,
                            llmBackend: "google_genai",
                            model: "gemini-3-flash-preview",
                            customModelUiOpen: false,
                          };
                        }
                        let nextModel = current.model;
                        if (!nextModel.includes("/")) {
                          nextModel = "openrouter/auto";
                        }
                        return {
                          ...current,
                          llmBackend: "openrouter",
                          model: nextModel,
                          customModelUiOpen: false,
                        };
                      });
                    }}
                  >
                    <option value="gemini-3-flash-preview">
                      gemini-3-flash-preview
                    </option>
                    <option value="openrouter">OpenRouter</option>
                    {hasNonPresetModel(draft) ? (
                      <option value="saved_custom">{draft.model}</option>
                    ) : null}
                    <option value="add_model">모델 추가</option>
                  </select>
                  {modelPick === "add_model" ? (
                    <input
                      id={modelId}
                      className={styles.input}
                      type="text"
                      value={draft.model}
                      aria-label="Custom model ID"
                      onChange={(e) =>
                        setDraft((current) => ({
                          ...current,
                          model: e.target.value,
                          customModelUiOpen: true,
                        }))
                      }
                      placeholder={
                        draft.llmBackend === "openrouter"
                          ? "provider/model"
                          : "gemini-3-flash-preview"
                      }
                      autoComplete="off"
                    />
                  ) : null}
                </div>
                <div className={styles.hint}>
                  저장한 비프리셋 모델은 셀렉트에 그대로 뜹니다. <code>모델 추가</code>는 입력칸을
                  켭니다. OpenRouter는 <code>provider/model</code>, Google GenAI는 모델 이름만.
                  OpenRouter API 키·base URL은 서버 환경 변수(
                  <code>OPENROUTER_API_KEY</code>, <code>OPENROUTER_BASE_URL</code>)로 둡니다. Save
                  시 모델·UI 상태가 함께 저장됩니다.
                </div>
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
