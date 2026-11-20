import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { NotificationItem, NotificationKind } from "../types";
import { notifyChime } from "../proctor";
import { setTitleBadge } from "../lib/titleBadge";
import { parseServerTime } from "../lib/time";

// The lecturer's notifications (GET /api/notifications, backend/notifications.py):
// polled every few seconds; what arrives while the page is open pops up, and
// what still waits for the lecturer pops up again when the page is opened.

const POLL_MS = 4000;
// The bell's list keeps this many.
const KEEP = 150;
// Pop-ups closed in this browser stay closed after a reload.
const DISMISSED_KEY = "vc.notify.dismissed";
const DISMISSED_KEEP = 300;

/** The kinds the lecturer has to act on: their pop-up stays until handled. */
export const WAITING_KINDS: ReadonlySet<NotificationKind> = new Set(["question", "step", "answer"]);

function loadDismissed(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(DISMISSED_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function saveDismissed(keys: string[]): void {
  try { localStorage.setItem(DISMISSED_KEY, JSON.stringify(keys.slice(-DISMISSED_KEEP))); } catch { /* ignore */ }
}

/** The server's time a few seconds earlier, in its own format: the next call's
 *  `since`, so a row written in the same second isn't missed (keys dedupe). */
function before(serverTime: string, seconds: number): string {
  const d = parseServerTime(serverTime);
  if (!d) return serverTime;
  return new Date(d.getTime() - seconds * 1000).toISOString().slice(0, 19).replace("T", " ");
}

export interface Notifications {
  /** Newest first. */
  items: NotificationItem[];
  /** Keys of the items that still wait for the lecturer. */
  waiting: ReadonlySet<string>;
  /** The open pop-ups, newest first. */
  popups: NotificationItem[];
  unread: number;
  kinds: NotificationKind[];
  sound: boolean;
  loaded: boolean;
  isWaiting: (n: NotificationItem) => boolean;
  dismiss: (key: string) => void;
  dismissAll: () => void;
  markSeen: () => void;
  /** Read the settings again (after they were changed). */
  refresh: () => void;
}

export function useNotifications(): Notifications {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [waiting, setWaiting] = useState<ReadonlySet<string>>(new Set());
  const [popups, setPopups] = useState<NotificationItem[]>([]);
  const [seenAt, setSeenAt] = useState<string | null>(null);
  const [kinds, setKinds] = useState<NotificationKind[]>([]);
  const [sound, setSound] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const cursor = useRef<string | null>(null);
  const known = useRef(new Set<string>());
  const dismissed = useRef<string[]>(loadDismissed());
  const busy = useRef(false);

  const poll = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const firstLoad = cursor.current === null;
      const feed = await api.notifications(cursor.current ? before(cursor.current, 10) : undefined);
      const fresh = feed.items.filter((n) => !known.current.has(n.key));
      for (const n of fresh) known.current.add(n.key);
      const on = new Set(feed.kinds);
      setItems((prev) => [...fresh, ...prev.filter((n) => on.has(n.kind))]
        .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id)
        .slice(0, KEEP));
      const still = new Set(feed.waiting);
      setWaiting(still);
      setSeenAt(feed.seen_at);
      setKinds(feed.kinds);
      setSound(feed.sound);
      setLoaded(true);
      // At load, what still waits and wasn't seen yet; later, everything new.
      const closed = new Set(dismissed.current);
      const pop = fresh.filter((n) => !closed.has(n.key) && (!firstLoad
        || (n.waiting && (!feed.seen_at || n.created_at > feed.seen_at))));
      setPopups((prev) => {
        // A pop-up the lecturer has acted on (answered, checked, decided) closes by itself.
        const kept = prev.filter((n) => on.has(n.kind) && (!WAITING_KINDS.has(n.kind) || still.has(n.key)));
        return [...pop, ...kept];
      });
      if (!firstLoad && pop.length > 0 && feed.sound) notifyChime();
      cursor.current = feed.now;
    } catch {
      // The connection banner reports a lost server.
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    void poll();
    const id = window.setInterval(() => void poll(), POLL_MS);
    return () => window.clearInterval(id);
  }, [poll]);

  const unread = useMemo(
    () => items.filter((n) => !seenAt || n.created_at > seenAt).length, [items, seenAt]);

  // "(3 🔔) VeriClass": unread notifications show in the browser tab too.
  useEffect(() => {
    setTitleBadge("notifications", unread > 0 ? `(${unread} 🔔)` : null);
    return () => setTitleBadge("notifications", null);
  }, [unread]);

  const dismiss = useCallback((key: string) => {
    setPopups((prev) => prev.filter((n) => n.key !== key));
    dismissed.current = [...dismissed.current.filter((k) => k !== key), key];
    saveDismissed(dismissed.current);
  }, []);

  const dismissAll = useCallback(() => {
    dismissed.current = [...dismissed.current, ...popups.map((n) => n.key)];
    saveDismissed(dismissed.current);
    setPopups([]);
  }, [popups]);

  const markSeen = useCallback(() => {
    const at = cursor.current ?? undefined;
    api.notificationsSeen(at).then((r) => setSeenAt(r.seen_at)).catch(() => { /* next poll tries again */ });
  }, []);

  const isWaiting = useCallback(
    (n: NotificationItem) => WAITING_KINDS.has(n.kind) && waiting.has(n.key), [waiting]);

  return {
    items, waiting, popups, unread, kinds, sound, loaded, isWaiting, dismiss, dismissAll, markSeen,
    // From the start again: kinds just turned on show what they have.
    refresh: () => { cursor.current = null; void poll(); },
  };
}
