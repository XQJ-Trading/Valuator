import type { ReactNode } from "react";
import styles from "./MobileModal.module.css";

interface Props {
  title: string;
  onClose: () => void;
  onConfirm?: () => void;
  children: ReactNode;
}

export default function MobileModal({ title, onClose, onConfirm, children }: Props) {
  return (
    <div className={styles.overlay}>
      <div className={styles.header}>
        <span className={styles.headerTitle}>{title}</span>
        <button className={styles.closeBtn} onClick={onClose} title="닫기">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
            <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        </button>
      </div>
      <div className={styles.body}>{children}</div>
      <div className={styles.footer}>
        {onConfirm && (
          <button className={`${styles.btn} ${styles.btnOkay}`} onClick={onConfirm}>
            확인
          </button>
        )}
        <button className={`${styles.btn} ${styles.btnCancel}`} onClick={onClose}>
          닫기
        </button>
      </div>
    </div>
  );
}
