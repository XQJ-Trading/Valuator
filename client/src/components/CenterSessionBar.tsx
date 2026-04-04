import { useChatSession, type StepFlowSnapshot } from "../ChatSessionContext";
import styles from "./CenterSessionBar.module.css";


function humanTaskLabel(
  taskId: string,
  flowTaskName: string | undefined,
  taskDisplayNames: Map<string, string>,
): string {
  const fromEvent = flowTaskName?.trim();
  if (fromEvent) return fromEvent;
  const fromMap = taskDisplayNames.get(taskId)?.trim();
  if (fromMap) return fromMap;
  return taskId.trim();
}

function formatStepLine(
  flow: Pick<StepFlowSnapshot, "globalSeq" | "description">,
  taskLabel: string,
): string {
  const g = flow.globalSeq != null ? `${flow.globalSeq}` : "?";
  const rest = flow.description.trim();
  return rest ? `steps ${g} [${taskLabel}]: ${rest}` : `steps ${g} [${taskLabel}]`;
}

export default function CenterSessionBar() {
  const {
    activeTaskIds,
    taskDisplayNames,
    taskDescriptions,
    agentRunning,
    stopAgent,
    lastStepFlow,
  } = useChatSession();

  const showProgress = activeTaskIds.length > 0;
  const flow = agentRunning ? lastStepFlow : null;

  return (
    <div className={styles.centerBar} role="status" aria-live="polite">
      <div className={styles.centerBarInner}>
        <div className={styles.barRow}>
          <div className={styles.statusArea}>
            {flow ? (
              <div className={styles.flowLine}>
                {formatStepLine(
                  flow,
                  humanTaskLabel(flow.taskId, flow.taskName, taskDisplayNames),
                )}
              </div>
            ) : showProgress ? (
              activeTaskIds.map((id) => (
                <div key={id} className={styles.progressItem}>
                  <span className={styles.progressSpinner} aria-hidden="true" />
                  <span className={styles.progressName}>
                    {taskDisplayNames.get(id) ?? taskDescriptions.get(id) ?? id}
                  </span>
                </div>
              ))
            ) : agentRunning ? (
              <div className={styles.progressItem}>
                <span className={styles.progressSpinner} aria-hidden="true" />
                <span className={styles.runningLabel}>에이전트 실행 중…</span>
              </div>
            ) : (
              <span className={styles.idle}>에이전트 대기 중</span>
            )}
          </div>
          <button
            type="button"
            className={styles.stopBtn}
            disabled={!agentRunning}
            onClick={() => void stopAgent()}
            title={agentRunning ? "실행 중인 에이전트 프로세스를 중지합니다" : "실행 중인 세션이 없습니다"}
          >
            세션 중지
          </button>
        </div>
      </div>
    </div>
  );
}
