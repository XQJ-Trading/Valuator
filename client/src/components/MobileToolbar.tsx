import styles from "./MobileToolbar.module.css";

interface Props {
  onOpenSidebar: () => void;
  onOpenChat: () => void;
  sidebarActive?: boolean;
  chatActive?: boolean;
}

export default function MobileToolbar({ onOpenSidebar, onOpenChat, sidebarActive, chatActive }: Props) {
  return (
    <div className={styles.toolbar}>
      <span className={styles.title}>Research UI</span>
      <div className={styles.actions}>
        <button
          className={`${styles.iconBtn}${sidebarActive ? ` ${styles.active}` : ""}`}
          onClick={onOpenSidebar}
          title="파일 탐색기"
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor">
            <path d="M1 3.5A1.5 1.5 0 0 1 2.5 2h2.764c.958 0 1.76.56 2.311 1.184C7.985 3.648 8.48 4 9 4h4.5A1.5 1.5 0 0 1 15 5.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 12.5v-9z"/>
          </svg>
        </button>
        <button
          className={`${styles.iconBtn}${chatActive ? ` ${styles.active}` : ""}`}
          onClick={onOpenChat}
          title="채팅"
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor">
            <path d="M2 2h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H9l-3 2v-2H2a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/>
          </svg>
        </button>
      </div>
    </div>
  );
}
