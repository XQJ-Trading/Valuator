import { useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import type { ActivityView } from "./api";
import ActivitySidebar from "./components/ActivitySidebar";
import FileTree from "./components/FileTree";
import ContentView from "./components/ContentView";
import ConfigView from "./components/ConfigView";
import AgentChatPanel from "./components/AgentChatPanel";
import "./App.css";

export default function App() {
  const [activityView, setActivityView] = useState<ActivityView>("session");
  const [activePath, setActivePath] = useState<string | null>(null);

  const handleActivityView = (v: ActivityView) => {
    setActivityView(v);
    setActivePath(null);
  };

  const titleSuffix =
    activityView === "config" ? (
      <span>— Configuration</span>
    ) : activePath ? (
      <span>— {activePath}</span>
    ) : null;

  return (
    <div className="app">
      <div className="titlebar">
        <span className="titlebar-label">Research UI</span>
        {titleSuffix}
      </div>

      <div className="main-row">
        <ActivitySidebar activityView={activityView} onSelect={handleActivityView} />

        <div className="main-content">
          {activityView === "config" ? (
            <ConfigView />
          ) : (
            <Group orientation="horizontal" className="panels">
              <Panel defaultSize="300px" minSize="150px" maxSize="40%">
                <FileTree
                  key={activityView}
                  dataSource={activityView}
                  activePath={activePath}
                  onSelect={setActivePath}
                />
              </Panel>

              <Separator className="resize-handle" />

              <Panel minSize="30%">
                <ContentView dataSource={activityView} filePath={activePath} />
              </Panel>
            </Group>
          )}
        </div>

        <div className="reserved-layout">
          <AgentChatPanel />
        </div>
      </div>
    </div>
  );
}
