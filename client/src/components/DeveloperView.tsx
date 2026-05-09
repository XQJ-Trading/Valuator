import { useState } from "react";
import styles from "./DeveloperView.module.css";
import UploadSessionCard from "./UploadSessionCard";
import DownloadSessionCard from "./DownloadSessionCard";
import StepAnalysisCard from "./StepAnalysisCard";
import LLMCallFlowchart from "./LLMCallFlowchart";

export default function DeveloperView() {
  const [selectedSession, setSelectedSession] = useState("");

  return (
    <div className={styles.root}>
      <div className={styles.header}>Developer Tools</div>
      <div className={styles.scroll}>
        <UploadSessionCard />
        <DownloadSessionCard />
        <StepAnalysisCard onSessionChange={setSelectedSession} />
        <LLMCallFlowchart selectedSession={selectedSession} />
      </div>
    </div>
  );
}
