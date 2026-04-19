import { useEffect, useState } from "react";
import { fetchTree, fetchFile } from "../api";
import {
  loadDeveloperConfig,
  saveDeveloperConfig,
  type DeveloperConfig,
} from "../developerConfigStorage";
import { useToast } from "../ToastContext";
import styles from "./UploadSessionCard.module.css";

// nginx default client_max_body_size is 1MB. JSON wrapper + escaping adds overhead,
// so cap raw file size at 800KB to stay safely under the 1MB request body limit.
const MAX_UPLOAD_BYTES = 800 * 1024;

async function remoteFetch(url: string, init: RequestInit): Promise<Response> {
  const res = await fetch(url, init);
  // 409 Conflict = already exists, treat as success for idempotent creates
  if (!res.ok && res.status !== 409) {
    const msg = await res
      .json()
      .then((b: { detail?: string; error?: string }) => b?.detail ?? b?.error ?? String(res.status))
      .catch(() => String(res.status));
    throw new Error(msg);
  }
  return res;
}

function remoteHeaders(key: string, secret: string): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "X-Auth-Key": encodeURIComponent(key),
    "X-Auth-Secret": encodeURIComponent(secret),
  };
}

export default function UploadSessionCard() {
  const pushToast = useToast();

  const [savedConfig, setSavedConfig] = useState<DeveloperConfig>(loadDeveloperConfig);
  const [remoteUrl, setRemoteUrl] = useState(savedConfig.remoteUrl);
  const [remoteAuthKey, setRemoteAuthKey] = useState(savedConfig.remoteAuthKey);
  const [remoteAuthSecret, setRemoteAuthSecret] = useState(savedConfig.remoteAuthSecret);
  const [savedMsg, setSavedMsg] = useState(false);

  const [configOpen, setConfigOpen] = useState(false);

  const [sessions, setSessions] = useState<string[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [selectedSession, setSelectedSession] = useState("");

  const [uploadState, setUploadState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [resultUrl, setResultUrl] = useState<string | null>(null);

  const configDirty =
    remoteUrl !== savedConfig.remoteUrl ||
    remoteAuthKey !== savedConfig.remoteAuthKey ||
    remoteAuthSecret !== savedConfig.remoteAuthSecret;

  useEffect(() => {
    void loadSessions();
  }, []);

  async function loadSessions() {
    setSessionsLoading(true);
    try {
      const tree = await fetchTree("", "session");
      const dirs = tree.children
        .filter((e) => e.type === "directory")
        .map((e) => e.name)
        .reverse();
      setSessions(dirs);
      setSelectedSession((prev) => prev || dirs[0] || "");
    } catch (err) {
      pushToast({ type: "error", title: "세션 목록 로드 실패", message: String(err) });
    } finally {
      setSessionsLoading(false);
    }
  }

  function persistConfig() {
    const cfg: DeveloperConfig = { remoteUrl, remoteAuthKey, remoteAuthSecret };
    saveDeveloperConfig(cfg);
    setSavedConfig(cfg);
    setSavedMsg(true);
    setTimeout(() => setSavedMsg(false), 2000);
  }

  async function upload() {
    const base = remoteUrl.replace(/\/$/, "");
    const headers = remoteHeaders(remoteAuthKey, remoteAuthSecret);

    setUploadState("running");
    setUploadError(null);
    setResultUrl(null);
    setProgress({ done: 0, total: 0 });

    try {
      // BFS 트리 탐색
      const allDirs: string[] = [];
      const allFiles: string[] = [];
      const queue: string[] = [selectedSession];

      while (queue.length > 0) {
        const cur = queue.shift()!;
        const tree = await fetchTree(cur, "session");
        for (const entry of tree.children) {
          if (entry.name === "trace") continue;
          const fullPath = `${cur}/${entry.name}`;
          if (entry.type === "directory") {
            allDirs.push(fullPath);
            queue.push(fullPath);
          } else {
            allFiles.push(fullPath);
          }
        }
      }

      setProgress({ done: 0, total: allDirs.length + allFiles.length });

      // 루트 세션 디렉터리 생성 (이미 존재해도 무시)
      await remoteFetch(`${base}/api/fs/create`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          source: "session",
          parentPath: "",
          name: selectedSession,
          kind: "directory",
        }),
      });

      // 서브 디렉터리 생성 (BFS 순서 = 부모 우선)
      for (const dir of allDirs) {
        const slash = dir.lastIndexOf("/");
        const parentPath = dir.substring(0, slash);
        const name = dir.substring(slash + 1);
        await remoteFetch(`${base}/api/fs/create`, {
          method: "POST",
          headers,
          body: JSON.stringify({ source: "session", parentPath, name, kind: "directory" }),
        });
        setProgress((p) => ({ ...p, done: p.done + 1 }));
      }

      // 파일 업로드
      for (const filePath of allFiles) {
        let fileData;
        try {
          fileData = await fetchFile(filePath, "session");
        } catch {
          // local server rejects files > 2MB (413); skip silently
          setProgress((p) => ({ ...p, done: p.done + 1 }));
          continue;
        }

        if (fileData.size > MAX_UPLOAD_BYTES) {
          setProgress((p) => ({ ...p, done: p.done + 1 }));
          continue;
        }

        const slash = filePath.lastIndexOf("/");
        const parentPath = filePath.substring(0, slash);
        const name = filePath.substring(slash + 1);

        await remoteFetch(`${base}/api/fs/create`, {
          method: "POST",
          headers,
          body: JSON.stringify({ source: "session", parentPath, name, kind: "file" }),
        });

        await remoteFetch(`${base}/api/file`, {
          method: "PUT",
          headers,
          body: JSON.stringify({ source: "session", path: filePath, content: fileData.content }),
        });

        setProgress((p) => ({ ...p, done: p.done + 1 }));
      }

      setResultUrl(`${base}?session=${encodeURIComponent(selectedSession)}`);
      setUploadState("done");
    } catch (err) {
      const msg = String(err);
      setUploadError(msg);
      setUploadState("error");
      pushToast({ type: "error", title: "업로드 실패", message: msg });
    }
  }

  const canUpload =
    uploadState !== "running" && selectedSession !== "" && remoteUrl.trim() !== "";
  const progressPct =
    progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.cardTitle}>로컬 세션 결과 서버로 전송</span>
        <button
          type="button"
          className={styles.secondaryBtn}
          onClick={() => setConfigOpen((v) => !v)}
        >
          {configOpen ? "닫기" : "설정"}
        </button>
      </div>

      <p className={styles.cardDesc}>
        로컬에서 실행한 세션 분석 결과를 배포 서버로 업로드합니다.{" "}
        <code>trace/</code> 디렉터리와 1.5MB 초과 파일은 제외됩니다.
      </p>

      {configOpen && (
        <div className={styles.configSection}>
          <div className={styles.section}>
            <label className={styles.sectionLabel}>Remote Server URL</label>
            <input
              className={styles.input}
              type="url"
              placeholder="https://your-server.example.com"
              value={remoteUrl}
              onChange={(e) => setRemoteUrl(e.target.value)}
            />
          </div>
          <div className={styles.section}>
            <label className={styles.sectionLabel}>Auth Key</label>
            <input
              className={styles.input}
              type="text"
              value={remoteAuthKey}
              onChange={(e) => setRemoteAuthKey(e.target.value)}
            />
          </div>
          <div className={styles.section}>
            <label className={styles.sectionLabel}>Auth Secret</label>
            <input
              className={styles.input}
              type="password"
              value={remoteAuthSecret}
              onChange={(e) => setRemoteAuthSecret(e.target.value)}
            />
          </div>
          <div className={styles.row}>
            <button
              type="button"
              className={styles.primaryBtn}
              onClick={persistConfig}
              disabled={!configDirty}
            >
              저장
            </button>
            {savedMsg && <span className={styles.savedMsg}>저장됨.</span>}
          </div>
        </div>
      )}

      <div className={styles.section}>
        <label className={styles.sectionLabel}>세션 선택</label>
        <div className={styles.row}>
          <select
            className={styles.select}
            value={selectedSession}
            onChange={(e) => setSelectedSession(e.target.value)}
            disabled={sessionsLoading || sessions.length === 0}
          >
            {sessions.length === 0 && (
              <option value="">{sessionsLoading ? "로딩 중..." : "세션 없음"}</option>
            )}
            {sessions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void loadSessions()}
            disabled={sessionsLoading}
          >
            새로고침
          </button>
        </div>
      </div>

      <div>
        <button
          type="button"
          className={styles.primaryBtn}
          onClick={() => void upload()}
          disabled={!canUpload}
        >
          {uploadState === "running" ? "업로드 중..." : "업로드"}
        </button>
      </div>

      {uploadState !== "idle" && (
        <div className={styles.progressArea}>
          <div className={styles.progressBar}>
            <div className={styles.progressFill} style={{ width: `${progressPct}%` }} />
          </div>
          <span>
            {progress.total === 0
              ? "준비 중..."
              : `${progress.done} / ${progress.total} 파일`}
          </span>
          {uploadState === "error" && (
            <span className={styles.errorText}>{uploadError}</span>
          )}
          {uploadState === "done" && resultUrl && (
            <a
              className={styles.successLink}
              href={resultUrl}
              target="_blank"
              rel="noreferrer"
            >
              원격 서버에서 보기 →
            </a>
          )}
        </div>
      )}
    </div>
  );
}
