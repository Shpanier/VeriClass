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
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}

const LEAVE_KINDS = new Set(["focus_lost", "minimized", "fullscreen_exited"]);

export function isLeaveKind(kind: string | null): boolean {
  return kind != null && LEAVE_KINDS.has(kind);
}

export function formatAway(ms: number | null): string {
  if (ms == null) return "";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}
