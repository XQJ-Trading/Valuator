import { useEffect, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { fetchSessionDefaultExplore, type ActivityView } from "./api";
import { ChatSessionProvider } from "./ChatSessionContext";
import { ToastProvider } from "./ToastContext";
import ActivitySidebar from "./components/ActivitySidebar";
import FileTree from "./components/FileTree";
import UserSessionView from "./components/UserSessionView";
import ContentView from "./components/ContentView";
import ConfigView from "./components/ConfigView";
import DeveloperView from "./components/DeveloperView";
import AgentChatPanel from "./components/AgentChatPanel";
import CenterSessionBar from "./components/CenterSessionBar";
import TaskTreeOutline from "./components/TaskTreeOutline";
import "./App.css";

export default function AppDesktop() {
  const [activityView, setActivityView] = useState<ActivityView>("session");
  const [activePath, setActivePath] = useState<string | null>(null);
  const [selectedDirectoryPath, setSelectedDirectoryPath] = useState<string | null>(null);
  const [chatSyncVersion, setChatSyncVersion] = useState(0);
  const [outlineChatTick, setOutlineChatTick] = useState(0);
  const [outlineFolderEnsureTick, setOutlineFolderEnsureTick] = useState(0);
  const [sessionExploreTarget, setSessionExploreTarget] = useState<string | null>(null);
  const [chatVisible, setChatVisible] = useState(true);
  const [devMode, setDevMode] = useState(false);

  /** Latest session browse path for the tree — only when switching to Session view, not on every chat tick. */
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
        if (dir) {
          setSelectedDirectoryPath(dir);
        }
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

  return (
    <ToastProvider>
    <ChatSessionProvider
      onMessagesUpdated={() => setChatSyncVersion((v) => v + 1)}
      onBrowseOutlineRefresh={() => setOutlineChatTick((v) => v + 1)}
    >
      <div className="app">
        <div className="titlebar">
          <span className="titlebar-label">Research UI</span>
          {activityView === "session" && (
            <button
              type="button"
              className={`titlebar-devtoggle${devMode ? " titlebar-devtoggle-on" : ""}`}
              onClick={() => setDevMode((v) => !v)}
              title={devMode ? "Switch to User Mode" : "Switch to Dev Mode"}
              aria-label="Toggle dev mode"
            >
              <span className="titlebar-devtoggle-thumb" />
            </button>
          )}
          <button
            className={`titlebar-icon-btn${chatVisible ? " active" : ""}`}
            onClick={() => setChatVisible((v) => !v)}
            title="Toggle Chat"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M2 2h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H9l-3 2v-2H2a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/>
            </svg>
          </button>
        </div>

        <div className="main-row">
          <ActivitySidebar activityView={activityView} onSelect={handleActivityView} />

          <Group orientation="horizontal" className="content-row">
            <Panel minSize="30%">
              <div className="main-content">
                {activityView === "config" ? (
                  <ConfigView />
                ) : activityView === "developer" ? (
                  <DeveloperView />
                ) : (
                  <>
                    <Group orientation="horizontal" className="panels">
                      <Panel defaultSize="300px" minSize="150px" maxSize="40%">
                        {activityView === "guide" ? (
                          <FileTree
                            key={activityView}
                            dataSource={activityView}
                            activePath={activePath}
                            onSelect={setActivePath}
                            onSelectDirectory={setSelectedDirectoryPath}
                            onUserSelectDirectory={() =>
                              setOutlineFolderEnsureTick((v) => v + 1)
                            }
                            refreshToken={chatSyncVersion}
                            initialExpandDirectory={null}
                          />
                        ) : devMode ? (
                          <Group orientation="vertical" style={{ height: "100%" }}>
                            <Panel defaultSize="50%" minSize="15%">
                              <FileTree
                                key={activityView}
                                dataSource={activityView}
                                activePath={activePath}
                                onSelect={setActivePath}
                                onSelectDirectory={setSelectedDirectoryPath}
                                onUserSelectDirectory={() =>
                                  setOutlineFolderEnsureTick((v) => v + 1)
                                }
                                refreshToken={chatSyncVersion}
                                initialExpandDirectory={
                                  activityView === "session" ? sessionExploreTarget : null
                                }
                              />
                            </Panel>
                            <Separator className="resize-handle resize-handle-row" />
                            <Panel defaultSize="50%" minSize="15%">
                              <TaskTreeOutline
                                dataSource={activityView}
                                enabled={true}
                                selectedDirectoryPath={selectedDirectoryPath}
                                outlineChatTick={outlineChatTick}
                                outlineFolderEnsureTick={outlineFolderEnsureTick}
                                onOpenTaskFile={setActivePath}
                              />
                            </Panel>
                          </Group>
                        ) : (
                          <Group orientation="vertical" style={{ height: "100%" }}>
                            <Panel defaultSize="40%" minSize="120px">
                              <UserSessionView
                                dataSource={activityView as "session" | "guide"}
                                onSelectDirectory={setSelectedDirectoryPath}
                                onUserSelectDirectory={() =>
                                  setOutlineFolderEnsureTick((v) => v + 1)
                                }
                                onSelect={setActivePath}
                              />
                            </Panel>
                            <Separator className="resize-handle resize-handle-row" />
                            <Panel defaultSize="60%" minSize="15%">
                              <TaskTreeOutline
                                dataSource={activityView}
                                enabled={true}
                                selectedDirectoryPath={selectedDirectoryPath}
                                outlineChatTick={outlineChatTick}
                                outlineFolderEnsureTick={outlineFolderEnsureTick}
                                onOpenTaskFile={setActivePath}
                                variant="user"
                              />
                            </Panel>
                          </Group>
                        )}
                      </Panel>

                      <Separator className="resize-handle" />

                      <Panel minSize="30%">
                        <ContentView dataSource={activityView} filePath={activePath} />
                      </Panel>
                    </Group>
                  </>
                )}
              </div>
            </Panel>

            {chatVisible && (
              <>
                <Separator className="resize-handle" />
                <Panel defaultSize="300px" minSize="200px" maxSize="40%">
                  <div className="reserved-layout">
                    <AgentChatPanel />
                  </div>
                </Panel>
              </>
            )}
          </Group>
        </div>

        <div className="bottom-bar">
          <CenterSessionBar />
        </div>
      </div>
    </ChatSessionProvider>
    </ToastProvider>
  );
}
