import { useEffect, useState } from "react";
import { fetchSessionDefaultExplore, type ActivityView } from "./api";
import { ChatSessionProvider } from "./ChatSessionContext";
import { ToastProvider } from "./ToastContext";
import ActivitySidebar from "./components/ActivitySidebar";
import FileTree from "./components/FileTree";
import ContentView from "./components/ContentView";
import ConfigView from "./components/ConfigView";
import AgentChatPanel from "./components/AgentChatPanel";
import TaskTreeOutline from "./components/TaskTreeOutline";
import MobileToolbar from "./components/MobileToolbar";
import MobileModal from "./components/MobileModal";
import "./App.css";

type ActiveModal = null | "sidebar" | "chat";

export default function AppMobile() {
  const [activityView, setActivityView] = useState<ActivityView>("session");
  const [activePath, setActivePath] = useState<string | null>(null);
  const [selectedDirectoryPath, setSelectedDirectoryPath] = useState<string | null>(null);
  const [chatSyncVersion, setChatSyncVersion] = useState(0);
  const [outlineChatTick, setOutlineChatTick] = useState(0);
  const [outlineFolderEnsureTick, setOutlineFolderEnsureTick] = useState(0);
  const [sessionExploreTarget, setSessionExploreTarget] = useState<string | null>(null);
  const [activeModal, setActiveModal] = useState<ActiveModal>(null);

  useEffect(() => {
    if (activityView !== "session") {
      setSessionExploreTarget(null);
      return;
    }
    let cancelled = false;
    void fetchSessionDefaultExplore()
      .then((r) => {
        if (cancelled) return;
        const dir = (r.browsePath ?? r.sessionFolder)?.trim() || null;
        setSessionExploreTarget(dir);
        if (dir) setSelectedDirectoryPath(dir);
      })
      .catch(() => {
        if (!cancelled) setSessionExploreTarget(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activityView]);

  const handleActivityView = (v: ActivityView) => {
    setActivityView(v);
    setActivePath(null);
    setSelectedDirectoryPath(null);
  };

  const handleSelectFile = (path: string | null) => {
    if (path) {
      setActivePath(path);
      setActiveModal(null);
    }
  };

  const sidebarTitle =
    activityView === "config" ? "설정" : activityView === "guide" ? "가이드" : "파일 탐색기";

  return (
    <ToastProvider>
      <ChatSessionProvider
        onMessagesUpdated={() => setChatSyncVersion((v) => v + 1)}
        onBrowseOutlineRefresh={() => setOutlineChatTick((v) => v + 1)}
      >
        <div className="app" style={{ paddingTop: 48 }}>
          <MobileToolbar
            onOpenSidebar={() => setActiveModal("sidebar")}
            onOpenChat={() => setActiveModal("chat")}
            sidebarActive={activeModal === "sidebar"}
            chatActive={activeModal === "chat"}
          />

          <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
            <ContentView
              dataSource={activityView === "config" ? "session" : activityView}
              filePath={activePath}
              mobileLayout
            />
          </div>

          {activeModal === "sidebar" && (
            <MobileModal title={sidebarTitle} onClose={() => setActiveModal(null)}>
              <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
                <ActivitySidebar activityView={activityView} onSelect={handleActivityView} />
                <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
                  {activityView === "config" ? (
                    <ConfigView />
                  ) : activityView === "guide" ? (
                    <FileTree
                      key={activityView}
                      dataSource={activityView}
                      activePath={activePath}
                      onSelect={handleSelectFile}
                      onSelectDirectory={setSelectedDirectoryPath}
                      onUserSelectDirectory={() => setOutlineFolderEnsureTick((v) => v + 1)}
                      refreshToken={chatSyncVersion}
                      initialExpandDirectory={null}
                    />
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
                      <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
                        <FileTree
                          key={activityView}
                          dataSource={activityView}
                          activePath={activePath}
                          onSelect={handleSelectFile}
                          onSelectDirectory={setSelectedDirectoryPath}
                          onUserSelectDirectory={() => setOutlineFolderEnsureTick((v) => v + 1)}
                          refreshToken={chatSyncVersion}
                          initialExpandDirectory={
                            activityView === "session" ? sessionExploreTarget : null
                          }
                        />
                      </div>
                      <div style={{ flex: 1, overflow: "auto", minHeight: 0, borderTop: "1px solid var(--border)" }}>
                        <TaskTreeOutline
                          dataSource={activityView}
                          enabled={true}
                          selectedDirectoryPath={selectedDirectoryPath}
                          outlineChatTick={outlineChatTick}
                          outlineFolderEnsureTick={outlineFolderEnsureTick}
                          onOpenTaskFile={(path) => {
                            if (path) {
                              setActivePath(path);
                              setActiveModal(null);
                            }
                          }}
                        />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </MobileModal>
          )}

          {activeModal === "chat" && (
            <MobileModal title="채팅" onClose={() => setActiveModal(null)}>
              <div className="reserved-layout" style={{ flex: 1 }}>
                <AgentChatPanel />
              </div>
            </MobileModal>
          )}
        </div>
      </ChatSessionProvider>
    </ToastProvider>
  );
}
