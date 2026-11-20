// Counts in the browser tab's title, e.g. "(2 ✍️) (3 🔔) VeriClass", from
// several parts of the page at once: each sets its own badge by name.

const badges = new Map<string, string>();
let base: string | null = null;

/** Show `text` in front of the page title under `name`, or remove it (null). */
export function setTitleBadge(name: string, text: string | null): void {
  if (base === null) base = document.title;
  if (text) badges.set(name, text);
  else badges.delete(name);
  const prefix = [...badges.values()].join(" ");
  document.title = prefix ? `${prefix} ${base}` : base;
}
