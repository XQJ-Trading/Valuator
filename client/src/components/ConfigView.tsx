import { useEffect, useId, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import {
  loadAgentConfig,
  saveAgentConfig,
  type AgentConnectionConfig,
} from "../agentConfigStorage";
import styles from "./ConfigView.module.css";

export default function ConfigView() {
  const keyId = useId();
  const secretId = useId();
  const [draft, setDraft] = useState<AgentConnectionConfig>(() => loadAgentConfig());
  const [saved, setSaved] = useState<AgentConnectionConfig>(() => loadAgentConfig());
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    const c = loadAgentConfig();
    setDraft(c);
    setSaved(c);
  }, []);

  const dirty =
    draft.authKey !== saved.authKey || draft.authSecret !== saved.authSecret;

  const persist = () => {
    saveAgentConfig(draft);
    setSaved({ ...draft });
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
