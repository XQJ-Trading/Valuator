import styles from "./ContentView.module.css";

export default function RawTextView({
  value,
  onChange,
  readOnly,
  ariaLabel,
}: {
  value: string;
  onChange: (next: string) => void;
  readOnly?: boolean;
  ariaLabel: string;
}) {
  return (
    <textarea
      className={styles.rawTextarea}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      readOnly={readOnly}
      spellCheck={false}
      aria-label={ariaLabel}
    />
  );
}
