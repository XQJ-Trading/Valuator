import { useEffect } from "react";
import styles from "./ConfirmCloseDialog.module.css";

interface Props {
  fileName: string;
  onSave: () => void;
  onDiscard: () => void;
  onCancel: () => void;
}

export default function ConfirmCloseDialog({
  fileName,
  onSave,
  onDiscard,
  onCancel,
}: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel]);

  return (
    <div
      className={styles.overlay}
      onClick={onCancel}
      role="presentation"
    >
      <div
        className={styles.dialog}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-close-title"
      >
        <div className={styles.header}>
          <h2 id="confirm-close-title" className={styles.title}>
            저장하지 않은 변경사항
          </h2>
        </div>
        <div className={styles.body}>
          <span className={styles.fileName}>{fileName}</span> 파일에 저장되지 않은 변경사항이 있습니다.
        </div>
        <div className={styles.footer}>
          <button
            type="button"
            className={styles.btn}
            onClick={onCancel}
            autoFocus
          >
            취소
          </button>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnDanger}`}
            onClick={onDiscard}
          >
            저장 안 함
          </button>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={onSave}
          >
            저장
          </button>
        </div>
      </div>
    </div>
  );
}
