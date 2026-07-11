import type { ReactNode } from "react";

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  fontWeight: 600,
  color: "#374151",
  marginBottom: 4,
};

const controlStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  fontSize: 13,
  fontFamily: "inherit",
  boxSizing: "border-box",
};

// A labeled input/textarea. Free text uses dir="auto" so Hebrew content orients
// itself regardless of the dashboard's UI language.
export function Field({
  label,
  value,
  onChange,
  textarea,
  monospace,
  placeholder,
  minHeight,
}: {
  label: ReactNode;
  value: string;
  onChange: (v: string) => void;
  textarea?: boolean;
  monospace?: boolean;
  placeholder?: string;
  minHeight?: number;
}) {
  const style: React.CSSProperties = {
    ...controlStyle,
    ...(monospace ? { fontFamily: "ui-monospace, monospace" } : {}),
    ...(textarea ? { minHeight: minHeight ?? 70, resize: "vertical" } : {}),
  };
  return (
    <label style={{ display: "block", marginBottom: 12 }}>
      <span style={labelStyle}>{label}</span>
      {textarea ? (
        <textarea
          value={value}
          dir="auto"
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          style={style}
        />
      ) : (
        <input
          value={value}
          dir="auto"
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          style={style}
        />
      )}
    </label>
  );
}

export { labelStyle, controlStyle };
