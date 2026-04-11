import { useEffect, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { fetchSessionDefaultExplore, type ActivityView } from "./api";
import { ChatSessionProvider } from "./ChatSessionContext";
import { ToastProvider } from "./ToastContext";
import ActivitySidebar from "./components/ActivitySidebar";
import FileTree from "./components/FileTree";
import ContentView from "./components/ContentView";
import ConfigView from "./components/ConfigView";
import AgentChatPanel from "./components/AgentChatPanel";
import CenterSessionBar from "./components/CenterSessionBar";
import TaskTreeOutline from "./components/TaskTreeOutline";
import "./App.css";

export default function App() {
  const [activityView, setActivityView] = useState<ActivityView>("session");
  const [activePath, setActivePath] = useState<string | null>(null);
  const [selectedDirectoryPath, setSelectedDirectoryPath] = useState<string | null>(null);
  const [chatSyncVersion, setChatSyncVersion] = useState(0);
  const [outlineChatTick, setOutlineChatTick] = useState(0);
  const [outlineFolderEnsureTick, setOutlineFolderEnsureTick] = useState(0);
  const [sessionExploreTarget, setSessionExploreTarget] = useState<string | null>(null);

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
        </div>

        <div className="main-row">
          <ActivitySidebar activityView={activityView} onSelect={handleActivityView} />

          <div className="main-content">
            {activityView === "config" ? (
              <ConfigView />
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
                    ) : (
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

          <div className="reserved-layout">
            <AgentChatPanel />
          </div>
        </div>

        <div className="bottom-bar">
          <CenterSessionBar />
        </div>
      </div>
    </ChatSessionProvider>
    </ToastProvider>
  );
}
