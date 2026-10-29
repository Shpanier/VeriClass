import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Message, ParamLabel, Probe, SessionDetail, Student, TranscriptEntry, TranscriptResponse } from "../types";
import { renderParams } from "../params";
import { useLang } from "../i18n";

export function ChatViewModal({
  student,
  paramLabels,
  onClose,
}: {
  student: Student;
  paramLabels?: ParamLabel[];
  onClose: () => void;
}) {
  const { t } = useLang();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  // The chat as the student saw it (steps, pasted outputs, quiz, notes): for
  // exercises that keep a transcript; the tutor's messages and probes otherwise.
  const [chat, setChat] = useState<TranscriptResponse | null>(null);
  const [view, setView] = useState<"chat" | "messages" | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const params = renderParams(detail?.session.variant_params ?? student.variant_params, paramLabels);

  useEffect(() => {
    const tick = () => {
      api.sessionDetail(student.session_id).then(setDetail).catch(console.error);
      api.transcript(student.session_id).then(setChat).catch(console.error);
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, [student.session_id]);

  const hasChat = !!chat?.enabled && chat.entries.length > 0;
  const shown = view ?? (hasChat ? "chat" : "messages");

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail, chat, shown, autoScroll]);

  const items = interleave(detail?.messages ?? [], detail?.probes ?? []);
  const tab = (key: "chat" | "messages", label: string) => (
    <button
      onClick={() => setView(key)}
      style={{
        border: "1px solid #d1d5db", borderRadius: 4, padding: "3px 10px", cursor: "pointer",
        background: shown === key ? "#111827" : "white", color: shown === key ? "white" : "#111827",
      }}
    >
      {label}
    </button>
  );

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
              {t("autoScroll")}
            </label>
            <button onClick={onClose}>{t("close")}</button>
          </div>
        </header>

        {params.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 12, color: "#4b5563", display: "flex", gap: 8, flexWrap: "wrap" }}>
            {params.map((p, i) => (
              <span key={i} title={p.note ?? undefined} style={{ background: "#f3f4f6", borderRadius: 6, padding: "2px 8px" }}>
                <span style={{ color: "#6b7280" }}>{p.label}:</span>{" "}
                <span style={{ fontWeight: 600 }} dir="auto">{p.value}</span>
              </span>
            ))}
          </div>
        )}

        {chat?.enabled && (
          <div style={{ marginTop: 10, display: "flex", gap: 6 }}>
            {tab("chat", t("chatViewTranscript", { n: chat.entries.length }))}
            {tab("messages", t("chatViewMessages", { m: detail?.messages.length ?? 0, p: detail?.probes.length ?? 0 }))}
          </div>
        )}

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
          {shown === "chat" ? (
            <>
              {chat?.truncated && <p style={{ color: "#888", fontSize: 12 }}>{t("chatViewTruncated")}</p>}
              {(chat?.entries.length ?? 0) === 0 && <p style={{ color: "#888" }}>{t("noMessages")}</p>}
              {chat?.entries.map((e) => <TranscriptBubble key={`t${e.id}`} e={e} />)}
            </>
          ) : (
            <>
              {items.length === 0 && (
                <p style={{ color: "#888" }}>{t("noMessages")}</p>
              )}
              {items.map((item) =>
                item.kind === "message" ? (
                  <MessageBubble key={`m${item.data.id}`} m={item.data} />
                ) : (
                  <ProbeBubble key={`p${item.data.id}`} p={item.data} />
                )
              )}
            </>
          )}
          <div ref={bottomRef} />
        </div>

        <footer style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
          {detail
            ? t("chatFooter", { m: detail.messages.length, p: detail.probes.length })
            : t("loading")}
        </footer>
      </div>
    </div>
  );
}

/** One transcript entry: the student's on the right, the chat's and the
server's notes on the left (notes tinted). */
function TranscriptBubble({ e }: { e: TranscriptEntry }) {
  const isStudent = e.author === "student";
  const isNote = e.author === "system" || e.origin === "server";
  return (
    <div style={{ display: "flex", justifyContent: isStudent ? "flex-end" : "flex-start", margin: "8px 0" }}>
      <div
        dir="auto"
        style={{
          background: isStudent ? "#dbeafe" : isNote ? "#fef3c7" : "white",
          border: "1px solid #ddd",
          borderRadius: 8,
          padding: "8px 12px",
          maxWidth: "78%",
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
          fontSize: 13,
        }}
      >
        <div style={{ fontSize: 10, color: "#666", marginBottom: 4 }} dir="ltr">
          {e.author} · {e.kind}{e.step != null ? ` · step ${e.step}` : ""} · {e.created_at}
        </div>
        {e.content}
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
          {m.model && <> · {m.model}{m.cached ? " (cached)" : ""}</>}
        </div>
        {m.body}
      </div>
    </div>
  );
}

function ProbeBubble({ p }: { p: Probe }) {
  const { t } = useLang();
  const grade = p.override_grade ?? p.auto_grade;
  return (
    <div style={{ margin: "10px 0", padding: 10, background: "#fff7ed", border: "1px solid #fdba74", borderRadius: 8 }}>
      <div style={{ fontSize: 11, color: "#9a3412", marginBottom: 4 }}>
        🔎 {t("instructorProbe")} · {p.status} · {p.sent_at}
        {p.source !== "manual" ? ` · ${p.source}` : ""}
      </div>
      <div style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{p.body}</div>
      {p.answer && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px dashed #fdba74" }}>
          <div style={{ fontSize: 11, color: "#666", marginBottom: 4 }}>
            {t("answerGrade", { g: grade ?? "?" })}
            {p.override_grade != null ? ` ${t("overridden")}` : ""}
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
