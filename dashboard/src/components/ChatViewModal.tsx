import "../styles/review.css";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Message, ParamLabel, Probe, SessionDetail, Student, TranscriptEntry, TranscriptResponse } from "../types";
import { renderParams } from "../params";
import { useLang } from "../i18n";
import { Button, Check, Loading, Modal, Time } from "./ui";
import { entryLabel, modelLabel } from "./ReviewQueue";
import { textDir } from "../lib/textDir";

/** A message's text: what is inside ``` fences looks like code, the rest is
 *  ordinary text in its own direction (Hebrew or English). */
function RichText({ text }: { text: string }) {
  const parts = text.split("```");
  return (
    <div className="vc-review-msg__body">
      {parts.map((part, i) => {
        if (i % 2 === 1) {
          // The fence's first line may name the language ("```python").
          const code = /^[\w+#.-]*\n/.test(part) ? part.slice(part.indexOf("\n") + 1) : part;
          return <pre key={i} className="vc-pre vc-pre--light" dir="ltr">{code.replace(/\n$/, "")}</pre>;
        }
        const prose = part.replace(/^\n+/, "").replace(/\n+$/, "");
        return prose ? <div key={i} className="u-prewrap" dir={textDir(prose)}>{prose}</div> : null;
      })}
    </div>
  );
}

/** A student's whole conversation, read only, refreshed every two seconds. */
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
  // exercises that keep a transcript; the tutor's messages and the lecturer's questions otherwise.
  const [chat, setChat] = useState<TranscriptResponse | null>(null);
  const [view, setView] = useState<"chat" | "messages" | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);
  // Was the lecturer at the end of the conversation (as of their last scroll)?
  const atBottom = useRef(true);
  // The newest item last shown, with its view: a different one means something new arrived.
  const lastShown = useRef<string | null>(null);
  const session = detail?.session ?? student;
  const params = renderParams(detail?.session.variant_params ?? student.variant_params, paramLabels);

  useEffect(() => {
    let alive = true;
    const tick = () => {
      api.sessionDetail(student.session_id).then((d) => { if (alive) setDetail(d); })
        .catch(() => { /* a background poll: the page's banner says when the server is unreachable */ });
      api.transcript(student.session_id).then((c) => { if (alive) setChat(c); })
        .catch(() => { /* as above */ });
    };
    tick();
    const id = window.setInterval(tick, 2000);
    return () => { alive = false; window.clearInterval(id); };
  }, [student.session_id]);

  const hasChat = !!chat?.enabled && chat.entries.length > 0;
  const shown = view ?? (hasChat ? "chat" : "messages");
  const items = interleave(detail?.messages ?? [], detail?.probes ?? []);
  const entries = chat?.entries ?? [];
  const newest = shown === "chat"
    ? `chat|${entries.length ? entries[entries.length - 1].id : ""}`
    : `messages|${items.length ? itemKey(items[items.length - 1]) : ""}`;

  const toEnd = (smooth: boolean) => {
    const el = scroller.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    atBottom.current = true;
  };

  // The polls replace the lists every two seconds; only a NEW item moves the
  // view, and only when the lecturer follows new messages and was already at the
  // end (one who scrolled up to read stays where they are). A view opens at its end.
  useEffect(() => {
    const before = lastShown.current;
    lastShown.current = newest;
    const nowIn = newest.split("|")[0];
    if (before === null || before.split("|")[0] !== nowIn) toEnd(false);
    else if (before !== newest && autoScroll && atBottom.current) toEnd(true);
  }, [newest, autoScroll]);

  const onScroll = () => {
    const el = scroller.current;
    if (el) atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  const modeName = session.mode === "coding_partner" ? t("codingPartner") : t("mentor");
  // "default" is the version of an exercise that has no versions: nothing to say.
  const subtitle = [modeName, session.variant && session.variant !== "default"
    ? t("chatVariant", { v: session.variant }) : null].filter(Boolean).join(" · ");

  const tab = (key: "chat" | "messages", label: string) => (
    <button type="button" role="tab" className="vc-tab" aria-selected={shown === key} onClick={() => setView(key)}>
      {label}
    </button>
  );

  return (
    <Modal
      title={t("chatViewTitle", { name: student.username })}
      subtitle={subtitle}
      size="lg"
      flush
      onClose={onClose}
      footer={
        <>
          <Check checked={autoScroll} onChange={(v) => { setAutoScroll(v); if (v) toEnd(true); }}>{t("autoScroll")}</Check>
          <span className="u-muted u-xs">
            {detail ? t("chatFooter", { m: detail.messages.length, p: detail.probes.length }) : t("loading")}
          </span>
          <span className="u-push" />
          <Button onClick={onClose}>{t("close")}</Button>
        </>
      }
    >
      {(params.length > 0 || chat?.enabled) && (
        <div className="vc-review-chat__top">
          {params.length > 0 && (
            <div className="vc-review-chat__params">
              {params.map((p, i) => (
                <span key={i} className="vc-badge" title={p.note ?? undefined}>
                  {p.label}: <strong dir={textDir(p.value)}>{p.value}</strong>
                </span>
              ))}
            </div>
          )}
          {chat?.enabled && (
            <div className="vc-tabs vc-review-chat__tabs" role="tablist">
              {tab("chat", t("chatViewTranscript", { n: chat.entries.length }))}
              {tab("messages", t("chatViewMessages", { m: detail?.messages.length ?? 0, p: detail?.probes.length ?? 0 }))}
            </div>
          )}
        </div>
      )}

      <div ref={scroller} className="vc-review-chat" onScroll={onScroll} tabIndex={0}
           role={chat?.enabled ? "tabpanel" : "region"} aria-label={t("chatViewLog")}>
        {!detail && !chat ? (
          <Loading />
        ) : shown === "chat" ? (
          <>
            {chat?.truncated && <p className="u-muted u-xs u-mt-8">{t("chatViewTruncated")}</p>}
            {entries.length === 0 && <p className="u-muted u-mt-8">{t("noMessages")}</p>}
            {entries.map((e) => <TranscriptBubble key={`t${e.id}`} e={e} />)}
          </>
        ) : (
          <>
            {items.length === 0 && <p className="u-muted u-mt-8">{t("noMessages")}</p>}
            {items.map((item) =>
              item.kind === "message"
                ? <MessageBubble key={itemKey(item)} m={item.data} />
                : <ProbeBubble key={itemKey(item)} p={item.data} />,
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

/** One transcript entry: the student's at the end side, the chat's and the
 *  server's notes at the start (notes tinted). */
function TranscriptBubble({ e }: { e: TranscriptEntry }) {
  const { t } = useLang();
  const isStudent = e.author === "student";
  const isNote = e.author === "system" || e.origin === "server";
  return (
    <div className="vc-review-msg" data-side={isStudent ? "end" : "start"}
         data-who={isStudent ? "student" : isNote ? "note" : "tutor"}>
      <div className="vc-review-msg__bubble">
        <div className="vc-review-msg__meta">
          <span className="vc-review-msg__who">
            {t(entryLabel(e))}{e.step != null && e.kind === "step" ? ` ${e.step}` : ""}
          </span>
          {e.step != null && e.kind !== "step" && <span>{t("chatStepN", { n: e.step })}</span>}
          <Time value={e.created_at} mode="clock" />
        </div>
        <RichText text={e.content} />
      </div>
    </div>
  );
}

/** A turn of the conversation with the tutor; who wrote it, and (small) the model behind it. */
function MessageBubble({ m }: { m: Message }) {
  const { t } = useLang();
  const isUser = m.role === "user";
  const mode = m.mode_at_time === "coding_partner" ? t("codingPartner") : m.mode_at_time === "mentor" ? t("mentor") : null;
  const by = m.model === "bank" ? t("chatFromBank") : m.model ? modelLabel(m.model) : null;
  return (
    <div className="vc-review-msg" data-side={isUser ? "end" : "start"} data-who={isUser ? "student" : "tutor"}>
      <div className="vc-review-msg__bubble">
        <div className="vc-review-msg__meta">
          <span className="vc-review-msg__who">{isUser ? t("reviewKindStudent") : t("reviewKindTutor")}</span>
          <Time value={m.created_at} mode="clock" />
          {mode && <span>{mode}</span>}
          {by && <span className="vc-review-msg__model">{by}{m.cached ? ` · ${t("chatCached")}` : ""}</span>}
        </div>
        <RichText text={m.body} />
      </div>
    </div>
  );
}

/** A question the lecturer sent the student ("Ask them"), and the student's graded answer. */
function ProbeBubble({ p }: { p: Probe }) {
  const { t } = useLang();
  const grade = p.override_grade ?? p.auto_grade;
  return (
    <div className="vc-review-probe">
      <div className="vc-review-msg__meta">
        <span className="vc-review-msg__who">{t("instructorProbe")}</span>
        <Time value={p.sent_at} mode="clock" />
        <span>{p.status === "answered" ? t("chatProbeAnswered") : t("chatProbeWaiting")}</span>
        {p.source === "suggested" && <span>{t("chatProbeSuggested")}</span>}
        {p.source === "edited" && <span>{t("chatProbeEdited")}</span>}
      </div>
      <RichText text={p.body} />
      {p.answer && (
        <div className="vc-review-probe__answer">
          <div className="vc-review-msg__meta">
            <span className="vc-review-msg__who">{t("answerGrade", { g: grade ?? "?" })}</span>
            {p.override_grade != null && <span>{t("overridden")}</span>}
          </div>
          <RichText text={p.answer} />
        </div>
      )}
    </div>
  );
}

type Item =
  | { kind: "message"; ts: string; data: Message }
  | { kind: "probe"; ts: string; data: Probe };

function itemKey(item: Item): string {
  return item.kind === "message" ? `m${item.data.id}` : `p${item.data.id}`;
}

function interleave(messages: Message[], probes: Probe[]): Item[] {
  const items: Item[] = [
    ...messages.map<Item>((m) => ({ kind: "message", ts: m.created_at, data: m })),
    ...probes.map<Item>((p) => ({ kind: "probe", ts: p.sent_at, data: p })),
  ];
  items.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  return items;
}
