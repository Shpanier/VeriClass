import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Message, Probe, SessionDetail, Student } from "../types";

export function ChatViewModal({ student, onClose }: { student: Student; onClose: () => void }) {
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const tick = () =>
      api.sessionDetail(student.session_id).then(setDetail).catch(console.error);
    tick();
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, [student.session_id]);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail, autoScroll]);

  const items = interleave(detail?.messages ?? [], detail?.probes ?? []);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "grid",
        placeItems: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "white",
          padding: 20,
          borderRadius: 8,
          width: 820,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>
            💬 {student.username} · {student.variant} · {student.mode}
          </h3>
          <div>
            <label style={{ fontSize: 12, marginRight: 12 }}>
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />{" "}
              auto-scroll
            </label>
            <button onClick={onClose}>Close</button>
          </div>
        </header>

        <div
          style={{
            marginTop: 12,
            flex: 1,
            overflowY: "auto",
            border: "1px solid #eee",
            borderRadius: 6,
            padding: 12,
            background: "#fafafa",
          }}
        >
          {items.length === 0 && (
            <p style={{ color: "#888" }}>No messages yet. The student hasn't sent anything.</p>
          )}
          {items.map((item) =>
            item.kind === "message" ? (
              <MessageBubble key={`m${item.data.id}`} m={item.data} />
            ) : (
              <ProbeBubble key={`p${item.data.id}`} p={item.data} />
            )
          )}
          <div ref={bottomRef} />
        </div>

        <footer style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
          {detail
            ? `${detail.messages.length} chat message(s) · ${detail.probes.length} probe(s) · refreshing every 2s`
            : "Loading…"}
        </footer>
      </div>
    </div>
  );
}

function MessageBubble({ m }: { m: Message }) {
  const isUser = m.role === "user";
  return (
    <div style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start", margin: "8px 0" }}>
      <div
        style={{
          background: isUser ? "#dbeafe" : "white",
          border: "1px solid #ddd",
          borderRadius: 8,
          padding: "8px 12px",
          maxWidth: "78%",
          whiteSpace: "pre-wrap",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 13,
        }}
      >
        <div style={{ fontSize: 10, color: "#666", marginBottom: 4 }}>
          {m.role} · {m.created_at} · {m.mode_at_time}
        </div>
        {m.body}
      </div>
    </div>
  );
}

function ProbeBubble({ p }: { p: Probe }) {
  const grade = p.override_grade ?? p.auto_grade;
  return (
    <div style={{ margin: "10px 0", padding: 10, background: "#fff7ed", border: "1px solid #fdba74", borderRadius: 8 }}>
      <div style={{ fontSize: 11, color: "#9a3412", marginBottom: 4 }}>
        🔎 instructor probe · {p.status} · sent {p.sent_at}
        {p.source !== "manual" ? ` · ${p.source}` : ""}
      </div>
      <div style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{p.body}</div>
      {p.answer && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed #fdba74" }}>
          <div style={{ fontSize: 11, color: "#666", marginBottom: 4 }}>
            answer · grade {grade ?? "?"}/2
            {p.override_grade != null ? " (overridden)" : ""}
          </div>
          <div style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{p.answer}</div>
        </div>
      )}
    </div>
  );
}

type Item =
  | { kind: "message"; ts: string; data: Message }
  | { kind: "probe"; ts: string; data: Probe };

function interleave(messages: Message[], probes: Probe[]): Item[] {
  const items: Item[] = [
    ...messages.map<Item>((m) => ({ kind: "message", ts: m.created_at, data: m })),
    ...probes.map<Item>((p) => ({ kind: "probe", ts: p.sent_at, data: p })),
  ];
  items.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  return items;
}
