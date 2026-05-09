import { useEffect, useState } from "react";
import { saveFile } from "../api";
import { loadAgentConfig } from "../agentConfigStorage";
import {
  loadDeveloperConfig,
  saveDeveloperConfig,
  type DeveloperConfig,
} from "../developerConfigStorage";
import { useToast } from "../ToastContext";
import styles from "./UploadSessionCard.module.css";

const MAX_FILE_BYTES = 800 * 1024;

function remoteGetHeaders(key: string, secret: string): Record<string, string> {
  return {
    "X-Auth-Key": encodeURIComponent(key),
    "X-Auth-Secret": encodeURIComponent(secret),
  };
}

async function remoteFetch(url: string, init: RequestInit): Promise<Response> {
  console.log("[Download] →", init.method ?? "GET", url);
  const res = await fetch(url, init);
  console.log("[Download] ←", res.status, url);
  if (!res.ok && res.status !== 409) {
    const msg = await res
      .json()
      .then((b: { detail?: string; error?: string }) => b?.detail ?? b?.error ?? String(res.status))
      .catch(() => String(res.status));
    throw new Error(msg);
  }
  return res;
}

// api.ts의 createEntry는 raw status를 노출하지 않아 409 판별이 불가능하므로 raw fetch 사용
async function localCreate(parentPath: string, name: string, kind: "file" | "directory"): Promise<void> {
  console.log("[Download] localCreate", { parentPath, name, kind });
  const { authKey, authSecret } = loadAgentConfig();
  const res = await fetch("/api/fs/create", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Auth-Key": encodeURIComponent(authKey),
      "X-Auth-Secret": encodeURIComponent(authSecret),
    },
    body: JSON.stringify({ source: "session", parentPath, name, kind }),
  });
  console.log("[Download] localCreate ←", res.status, { parentPath, name, kind });
  if (!res.ok && res.status !== 409) {
    const msg = await res
      .json()
      .then((b: { detail?: string; error?: string }) => b?.detail ?? b?.error ?? String(res.status))
      .catch(() => String(res.status));
    throw new Error(msg);
  }
}

export default function DownloadSessionCard() {
  const pushToast = useToast();

  const [savedConfig, setSavedConfig] = useState<DeveloperConfig>(loadDeveloperConfig);
  const [remoteUrl, setRemoteUrl] = useState(savedConfig.remoteUrl);
  const [remoteAuthKey, setRemoteAuthKey] = useState(savedConfig.remoteAuthKey);
  const [remoteAuthSecret, setRemoteAuthSecret] = useState(savedConfig.remoteAuthSecret);
  const [savedMsg, setSavedMsg] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);

  const [remoteSessions, setRemoteSessions] = useState<string[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [selectedSession, setSelectedSession] = useState("");

  const [downloadState, setDownloadState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const configDirty =
    remoteUrl !== savedConfig.remoteUrl ||
    remoteAuthKey !== savedConfig.remoteAuthKey ||
    remoteAuthSecret !== savedConfig.remoteAuthSecret;

  const canDownload =
    downloadState !== "running" && selectedSession !== "" && remoteUrl.trim() !== "";

  const progressPct =
    progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;

  // 원격 서버는 상시 온라인이 아닐 수 있으므로 auto-load하지 않음 — 새로고침 버튼으로만 호출

  async function loadRemoteSessions() {
    if (!remoteUrl.trim()) return;
    setSessionsLoading(true);
    try {
      const base = remoteUrl.replace(/\/$/, "");
      const res = await remoteFetch(
        `${base}/api/tree?path=&source=session`,
        { method: "GET", headers: remoteGetHeaders(remoteAuthKey, remoteAuthSecret) },
      );
      const tree = (await res.json()) as { children: Array<{ name: string; type: string }> };
      const dirs = tree.children
        .filter((e) => e.type === "directory")
        .map((e) => e.name)
        .reverse();
      setRemoteSessions(dirs);
      setSelectedSession((prev) => prev || dirs[0] || "");
    } catch (err) {
      pushToast({ type: "error", title: "원격 세션 목록 로드 실패", message: String(err) });
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

  async function download() {
    const base = remoteUrl.replace(/\/$/, "");
    const headers = remoteGetHeaders(remoteAuthKey, remoteAuthSecret);

    setDownloadState("running");
    setDownloadError(null);
    setProgress({ done: 0, total: 0 });

    try {
      const allDirs: string[] = [];
      const allFiles: string[] = [];
      const queue: string[] = [selectedSession];

      while (queue.length > 0) {
        const cur = queue.shift()!;
        const res = await remoteFetch(
          `${base}/api/tree?path=${encodeURIComponent(cur)}&source=session`,
          { method: "GET", headers },
        );
        const tree = (await res.json()) as { children: Array<{ name: string; type: string }> };
        for (const entry of tree.children) {
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

      await localCreate("", selectedSession, "directory");

      for (const dir of allDirs) {
        const slash = dir.lastIndexOf("/");
        const parentPath = dir.substring(0, slash);
        const name = dir.substring(slash + 1);
        await localCreate(parentPath, name, "directory");
        setProgress((p) => ({ ...p, done: p.done + 1 }));
      }

      for (const filePath of allFiles) {
        let fileData: { size: number; content: string } | undefined;
        try {
          const res = await remoteFetch(
            `${base}/api/file?path=${encodeURIComponent(filePath)}&source=session`,
            { method: "GET", headers },
          );
          fileData = (await res.json()) as { size: number; content: string };
        } catch {
          // remote server rejects oversized files (413); skip silently
          setProgress((p) => ({ ...p, done: p.done + 1 }));
          continue;
        }

        if (fileData.size > MAX_FILE_BYTES) {
          setProgress((p) => ({ ...p, done: p.done + 1 }));
          continue;
        }

        const slash = filePath.lastIndexOf("/");
        const parentPath = filePath.substring(0, slash);
        const name = filePath.substring(slash + 1);
        await localCreate(parentPath, name, "file");
        await saveFile(filePath, "session", fileData.content);
        setProgress((p) => ({ ...p, done: p.done + 1 }));
      }

      setDownloadState("done");
    } catch (err) {
      const msg = String(err);
      setDownloadError(msg);
      setDownloadState("error");
      pushToast({ type: "error", title: "다운로드 실패", message: msg });
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.cardTitle}>원격 세션 로컬로 다운로드</span>
        <button
          type="button"
          className={styles.secondaryBtn}
          onClick={() => setConfigOpen((v) => !v)}
        >
          {configOpen ? "닫기" : "설정"}
        </button>
      </div>

      <p className={styles.cardDesc}>
        원격 서버에서 세션 파일을 로컬로 가져옵니다. 800KB 이하 파일만 저장됩니다.
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
        <label className={styles.sectionLabel}>원격 세션 선택</label>
        <div className={styles.row}>
          <select
            className={styles.select}
            value={selectedSession}
            onChange={(e) => setSelectedSession(e.target.value)}
            disabled={sessionsLoading || remoteSessions.length === 0}
          >
            {remoteSessions.length === 0 && (
              <option value="">{sessionsLoading ? "로딩 중..." : "세션 없음"}</option>
            )}
            {remoteSessions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void loadRemoteSessions()}
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
          onClick={() => void download()}
          disabled={!canDownload}
        >
          {downloadState === "running" ? "다운로드 중..." : "다운로드"}
        </button>
      </div>

      {downloadState !== "idle" && (
        <div className={styles.progressArea}>
          <div className={styles.progressBar}>
            <div className={styles.progressFill} style={{ width: `${progressPct}%` }} />
          </div>
          <span>
            {progress.total === 0
              ? "준비 중..."
              : `${progress.done} / ${progress.total} 파일`}
          </span>
          {downloadState === "error" && (
            <span className={styles.errorText}>{downloadError}</span>
          )}
          {downloadState === "done" && <span>다운로드 완료.</span>}
        </div>
      )}
    </div>
  );
}
