import styles from "./DeveloperView.module.css";
import UploadSessionCard from "./UploadSessionCard";
import StepAnalysisCard from "./StepAnalysisCard";

export default function DeveloperView() {
  return (
    <div className={styles.root}>
      <div className={styles.header}>Developer Tools</div>
      <div className={styles.scroll}>
        <UploadSessionCard />
        <StepAnalysisCard />
      </div>
    </div>
  );
}
