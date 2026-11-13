/** Is the server answering? The API wrapper reports every call here; the
 *  banner at the top of the page listens. Three failures in a row (about ten
 *  seconds of polling) count as "connection lost"; one success clears it. */
type Listener = (lost: boolean) => void;

let failures = 0;
let lost = false;
const listeners = new Set<Listener>();

function set(next: boolean) {
  if (next === lost) return;
  lost = next;
  listeners.forEach((fn) => fn(lost));
}

export const connection = {
  ok() { failures = 0; set(false); },
  fail() { failures += 1; if (failures >= 3) set(true); },
  isLost: () => lost,
  subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
};
