import "../styles/notify.css";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Bell, CircleHelp, FileUp, ListChecks, MessagesSquare, PenLine, Reply, Settings as SettingsIcon, X } from "lucide-react";
import { api } from "../api";
import type { NotificationConfig, NotificationItem, NotificationKind } from "../types";
import { useLang, type StringKey } from "../i18n";
import { Button, Check, Loading, Switch, Time, useToast } from "../components/ui";
import { textDir } from "../lib/textDir";
import type { Notifications } from "./useNotifications";

// What students send the lecturer, inside the page: pop-ups in the corner and
// the bell in the top bar (the feed: ./useNotifications.ts).

const ICON: Record<NotificationKind, ReactNode> = {
  question: <CircleHelp aria-hidden="true" />,
  step: <ListChecks aria-hidden="true" />,
  answer: <PenLine aria-hidden="true" />,
  reply: <Reply aria-hidden="true" />,
  submission: <FileUp aria-hidden="true" />,
  chat: <MessagesSquare aria-hidden="true" />,
};

const TITLE: Record<NotificationKind, StringKey> = {
  question: "nkQuestion",
  step: "nkStep",
  answer: "nkAnswer",
  reply: "nkReply",
  submission: "nkSubmission",
  chat: "nkChat",
};

/** One notification: what happened, who, in which exercise and when, and the words. */
function Line({ n, waiting, exerciseTitle }: {
  n: NotificationItem;
  waiting: boolean;
  exerciseTitle: (id: string) => string;
}) {
  const { t } = useLang();
  return (
    <>
      <span className="vc-notify__icon" data-kind={n.kind}>{ICON[n.kind]}</span>
      <span className="vc-notify__body">
        <span className="vc-notify__title">
          {t(TITLE[n.kind], { name: n.username, label: n.step_label ?? "" })}
        </span>
        <span className="vc-notify__meta">
          <bdi>{exerciseTitle(n.exercise_id)}</bdi> · <Time value={n.created_at} />
          {waiting && <span className="vc-badge vc-badge--warning vc-notify__waits">{t("notifyWaits")}</span>}
        </span>
        {n.text && <span className="vc-notify__text" dir={textDir(n.text)}>{n.text}</span>}
      </span>
    </>
  );
}

/** The bell in the top bar: how many are new, and the list (opening it marks them seen). */
export function NotificationBell({ feed, exerciseTitle, onOpen, onSettings }: {
  feed: Notifications;
  exerciseTitle: (id: string) => string;
  onOpen: (n: NotificationItem) => void;
  onSettings: () => void;
}) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  // Seen while the list is open: what arrives meanwhile counts as seen too.
  const { markSeen, unread } = feed;
  useEffect(() => { if (open && unread > 0) markSeen(); }, [open, unread, markSeen]);

  const waitingNow = feed.items.filter(feed.isWaiting).length;
  return (
    <div className="vc-menu vc-notify-bell" ref={box}>
      <button type="button" className="vc-notify-bell__btn" aria-haspopup="dialog" aria-expanded={open}
              aria-label={t("notifyBellAria", { n: feed.unread })} title={t("notifyTitle")}
              data-unread={feed.unread > 0 || undefined} onClick={() => setOpen((v) => !v)}>
        <Bell aria-hidden="true" />
        {feed.unread > 0 && <span className="vc-notify-bell__count">{feed.unread > 99 ? "99+" : feed.unread}</span>}
      </button>
      {open && (
        <div className="vc-menu__list vc-notify-panel" role="dialog" aria-label={t("notifyTitle")}>
          <div className="vc-notify-panel__head">
            <strong>{t("notifyTitle")}</strong>
            {waitingNow > 0 && <span className="vc-badge vc-badge--warning">{t("notifyWaitingN", { n: waitingNow })}</span>}
            <span className="u-push" />
            <Button variant="quiet" size="sm" icon={<SettingsIcon />} onClick={() => { setOpen(false); onSettings(); }}>
              {t("notifySettings")}
            </Button>
          </div>
          {!feed.loaded ? <Loading /> : feed.items.length === 0 ? (
            <p className="vc-notify-panel__empty">
              {feed.kinds.length === 0 ? t("notifyAllOff") : t("notifyEmpty")}
            </p>
          ) : (
            <ul className="vc-notify-panel__list">
              {feed.items.map((n) => (
                <li key={n.key}>
                  <button type="button" className="vc-notify vc-notify--row" data-waiting={feed.isWaiting(n) || undefined}
                          onClick={() => { setOpen(false); onOpen(n); }}>
                    <Line n={n} waiting={feed.isWaiting(n)} exerciseTitle={exerciseTitle} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// More than this many pop-ups: the rest wait in the bell's list.
const SHOWN = 4;

/** The pop-ups in the corner of the page. One that needs the lecturer stays
 *  until it is handled or closed; the others until closed. */
export function NotificationPopups({ feed, exerciseTitle, onOpen }: {
  feed: Notifications;
  exerciseTitle: (id: string) => string;
  onOpen: (n: NotificationItem) => void;
}) {
  const { t } = useLang();
  const { popups } = feed;
  if (popups.length === 0) return null;
  const more = popups.length - SHOWN;
  return (
    <section className="vc-notify-popups" aria-label={t("notifyTitle")} aria-live="polite">
      {popups.slice(0, SHOWN).map((n) => (
        <article key={n.key} className="vc-notify vc-notify--popup" data-waiting={feed.isWaiting(n) || undefined}>
          <Line n={n} waiting={feed.isWaiting(n)} exerciseTitle={exerciseTitle} />
          <span className="vc-notify__actions">
            <Button variant="primary" size="sm" onClick={() => { feed.dismiss(n.key); onOpen(n); }}>
              {t("notifyOpen")}
            </Button>
            <button type="button" className="vc-notify__close" aria-label={t("notifyClose")} title={t("notifyClose")}
                    onClick={() => feed.dismiss(n.key)}>
              <X aria-hidden="true" />
            </button>
          </span>
        </article>
      ))}
      {popups.length > 1 && (
        <div className="vc-notify-popups__foot">
          {more > 0 && <span>{t("notifyMore", { n: more })}</span>}
          <span className="u-push" />
          <Button variant="quiet" size="sm" onClick={feed.dismissAll}>{t("notifyCloseAll")}</Button>
        </div>
      )}
    </section>
  );
}

/** Settings: which kinds notify, and the sound (backend/notifications.py). */
export function NotificationSettings({ onChanged }: { onChanged: () => void }) {
  const { t } = useLang();
  const toast = useToast();
  const [cfg, setCfg] = useState<NotificationConfig | null>(null);
  useEffect(() => {
    api.notificationConfig().then(setCfg).catch((e) => toast.error(e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (!cfg) return <Loading />;

  const save = async (change: { kinds?: NotificationKind[]; sound?: boolean }) => {
    const before = cfg;
    setCfg({ ...cfg, ...change });
    try {
      setCfg(await api.setNotificationConfig(change));
      onChanged();
      toast.success(t("setSaved"));
    } catch (e) {
      setCfg(before);
      toast.error(e);
    }
  };
  const toggle = (k: NotificationKind, on: boolean) =>
    save({ kinds: cfg.all_kinds.filter((x) => (x === k ? on : cfg.kinds.includes(x))) });

  return (
    <>
      <h3 className="u-mb-8">{t("notifyTitle")}</h3>
      <p className="vc-hint u-mb-12">{t("notifySetHint")}</p>
      <div className="vc-notify-kinds">
        {cfg.all_kinds.map((k) => (
          <Check key={k} checked={cfg.kinds.includes(k)} onChange={(v) => void toggle(k, v)}>
            <span className="vc-notify-kinds__icon" data-kind={k}>{ICON[k]}</span>
            {t(`notifyKind_${k}` as StringKey)}
          </Check>
        ))}
      </div>
      <div className="u-mt-12">
        <Switch checked={cfg.sound} onChange={(v) => void save({ sound: v })}>{t("notifySound")}</Switch>
        <p className="vc-hint">{t("notifySoundHint")}</p>
      </div>
    </>
  );
}
