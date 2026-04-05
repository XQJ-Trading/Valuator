import type { JSX } from "react";
import type { ActivityView } from "../api";

function IconSession() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M3 6.5A2.5 2.5 0 0 1 5.5 4h5A2.5 2.5 0 0 1 13 6.5v11A2.5 2.5 0 0 1 10.5 20h-5A2.5 2.5 0 0 1 3 17.5v-11Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M13 8h5.5A2.5 2.5 0 0 1 21 10.5V18a2 2 0 0 1-2 2h-4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconGuide() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <path
        d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path d="M8 7h8M8 11h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function IconConfig() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.09A1.65 1.65 0 0 0 9 4.6V4a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const items: { id: ActivityView; label: string; Icon: () => JSX.Element }[] = [
  { id: "session", label: "session-data", Icon: IconSession },
  { id: "config", label: "config", Icon: IconConfig },
];

export default function ActivitySidebar({
  activityView,
  onSelect,
}: {
  activityView: ActivityView;
  onSelect: (s: ActivityView) => void;
}) {
  return (
    <nav className="activity-bar" aria-label="Primary navigation">
      {items.map(({ id, label, Icon }) => {
        const selected = activityView === id;
        return (
          <button
            key={id}
            type="button"
            className={`activity-btn${selected ? " selected" : ""}`}
            onClick={() => onSelect(id)}
            aria-pressed={selected}
            aria-current={selected ? "true" : undefined}
            title={label}
          >
            <Icon />
            <span className="activity-btn-label">{label}</span>
          </button>
        );
      })}
    </nav>
  );
}
