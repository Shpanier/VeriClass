import type { ExamState, Student } from "./types";

// Shared helpers for the exam/proctor UI: an alert tone (generated with Web
// Audio, no asset needed) and human labels for proctor event kinds.

let audioCtx: AudioContext | null = null;

function ctxOrNull(): AudioContext | null {
  try {
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctor) return null;
    audioCtx ??= new Ctor();
    return audioCtx;
  } catch {
    return null;
  }
}

/**
 * Create/resume the AudioContext from a real user gesture. Browsers block audio
 * until the user has interacted with the page, so App calls this on the first
 * click/keypress to "unlock" later alert beeps.
 */
export function primeAudio(): void {
  const ctx = ctxOrNull();
  if (ctx && ctx.state === "suspended") void ctx.resume();
}

/** Two quick descending blips = "a student just left the IDE". Best-effort. */
export function alertBeep(): void {
  const ctx = ctxOrNull();
  if (!ctx) return;
  if (ctx.state === "suspended") void ctx.resume();
  const now = ctx.currentTime;
  [880, 660].forEach((freq, i) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "square";
    osc.frequency.value = freq;
    const t = now + i * 0.18;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.2, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + 0.18);
  });
}

const KIND_LABEL: Record<string, string> = {
  exam_started: "started the exam",
  focus_lost: "switched away from CLion",
  minimized: "minimized CLion",
  fullscreen_exited: "left full screen",
  focus_regained: "returned (refocused)",
  window_restored: "returned (restored)",
  blocked_command: "ran a command that isn't allowed",
  stock_terminal_opened: "tried to open the IDE's own Terminal",
  fullscreen_restored: "back in full screen",
  tool_window_opened: "opened a panel that isn't allowed",
  other_window_opened: "opened another window",
  other_window_closed: "closed the other window",
  file_opened: "opened an editor tab",
  paste_external: "pasted text from outside the IDE",
  paste_internal: "pasted text copied inside the IDE",
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}

const LEAVE_KINDS = new Set(["focus_lost", "minimized", "fullscreen_exited"]);

export function isLeaveKind(kind: string | null): boolean {
  return kind != null && LEAVE_KINDS.has(kind);
}

const TERMINAL_ALERT_KINDS = new Set(["blocked_command", "stock_terminal_opened"]);

/** A VeriExam-terminal violation: an alert, but not "outside the IDE". */
export function isTerminalAlertKind(kind: string | null): boolean {
  return kind != null && TERMINAL_ALERT_KINDS.has(kind);
}

const IDE_ALERT_KINDS = new Set(["tool_window_opened", "other_window_opened", "paste_external"]);

/** Inside the IDE but not allowed: another panel or window, or a paste from outside. */
export function isIdeAlertKind(kind: string | null): boolean {
  return kind != null && IDE_ALERT_KINDS.has(kind);
}

/** Every alert this student raised (leaving, terminal, panels/windows/pastes). */
export function alertTotal(s: Student): number {
  return s.focus_alerts + (s.terminal_alerts ?? 0) + (s.ide_alerts ?? 0);
}

/** A live state that needs the teacher's attention right now. */
export function needsAttention(s: Student): boolean {
  return s.exam_state != null && s.exam_state !== "ok";
}

export const STATE_STYLE: Record<ExamState, { icon: string; color: string; bg: string }> = {
  ok: { icon: "🟢", color: "#047857", bg: "#ecfdf5" },
  away: { icon: "🔴", color: "#b91c1c", bg: "#fef2f2" },
  other_window: { icon: "🟠", color: "#c2410c", bg: "#fff7ed" },
  not_fullscreen: { icon: "🟡", color: "#a16207", bg: "#fefce8" },
  no_signal: { icon: "⚫", color: "#374151", bg: "#f3f4f6" },
};

/** The time it happened on the student's machine when known, else when it arrived. */
export function eventTime(e: { client_at?: string | null; created_at: string }): string {
  return e.client_at ?? e.created_at;
}

/** True when a report reached the server more than a minute after it happened. */
export function arrivedLate(e: { client_at?: string | null; created_at: string }): boolean {
  if (!e.client_at) return false;
  const a = Date.parse(e.client_at.replace(" ", "T") + "Z");
  const b = Date.parse(e.created_at.replace(" ", "T") + "Z");
  return !Number.isNaN(a) && !Number.isNaN(b) && b - a > 60_000;
}

export function formatAway(ms: number | null): string {
  if (ms == null) return "";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}
