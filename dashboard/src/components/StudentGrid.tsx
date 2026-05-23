import type { Student } from "../types";

interface Props {
  students: Student[];
  onModeChange: (sessionId: string, mode: "mentor" | "coding_partner") => void;
  onAskThem: (sessionId: string) => void;
  onViewChat: (sessionId: string) => void;
}

export function StudentGrid({ students, onModeChange, onAskThem, onViewChat }: Props) {
  if (students.length === 0) return null;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: 16,
      }}
    >
      {students.map((s) => (
        <StudentCard
          key={s.session_id}
          s={s}
          onModeChange={onModeChange}
          onAskThem={onAskThem}
          onViewChat={onViewChat}
        />
      ))}
    </div>
  );
}

function StudentCard({
  s,
  onModeChange,
  onAskThem,
  onViewChat,
}: {
  s: Student;
  onModeChange: Props["onModeChange"];
  onAskThem: Props["onAskThem"];
  onViewChat: Props["onViewChat"];
}) {
  const initials = s.username
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: "50%",
            background: "#3b82f6",
            color: "white",
            display: "grid",
            placeItems: "center",
            fontWeight: 600,
          }}
        >
          {initials}
        </div>
        <strong>{s.username}</strong>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "8px 0" }}>
        <Chip>{s.exercise}</Chip>
        <Chip>{s.variant}</Chip>
        <Chip color={s.mode === "mentor" ? "#10b981" : "#f59e0b"}>{s.mode}</Chip>
        <Chip>🔎 {s.probe_count}</Chip>
      </div>
      <div style={{ fontSize: 12, color: "#666" }}>last active: {s.last_active_at}</div>
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <select
          value={s.mode}
          onChange={(e) => onModeChange(s.session_id, e.target.value as "mentor" | "coding_partner")}
        >
          <option value="mentor">Mentor</option>
          <option value="coding_partner">Coding Partner</option>
        </select>
        <button
          onClick={() => onViewChat(s.session_id)}
          style={{
            background: "#3b82f6",
            color: "white",
            border: "none",
            borderRadius: 6,
            padding: "6px 12px",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          💬 View chat
        </button>
        <button
          onClick={() => onAskThem(s.session_id)}
          style={{
            background: "#f97316",
            color: "white",
            border: "none",
            borderRadius: 6,
            padding: "6px 12px",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          🔎 Ask them
        </button>
      </div>
    </div>
  );
}

function Chip({ children, color = "#e5e7eb" }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      style={{
        background: color,
        color: color === "#e5e7eb" ? "#111" : "white",
        padding: "2px 8px",
        borderRadius: 12,
        fontSize: 12,
      }}
    >
      {children}
    </span>
  );
}
