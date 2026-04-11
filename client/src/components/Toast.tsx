import { useEffect } from "react";
import type { Toast } from "../ToastContext";
import styles from "./Toast.module.css";

const ICONS: Record<Toast["type"], string> = {
  warning: "⚠",
  error: "✕",
  info: "ℹ",
};

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: Toast;
  onDismiss: () => void;
}) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 5000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div className={`${styles.toast} ${styles[toast.type]}`} role="alert">
      <span className={styles.icon}>{ICONS[toast.type]}</span>
      <div className={styles.body}>
        <span className={styles.title}>{toast.title}</span>
        <span className={styles.message}>{toast.message}</span>
      </div>
      <button className={styles.close} onClick={onDismiss} aria-label="Dismiss">
        ✕
      </button>
    </div>
  );
}

export default function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className={styles.container}>
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  );
}
