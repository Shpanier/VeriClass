import type { ParamLabel } from "./types";

// Turn a variant's raw params + the exercise's param_labels into an ordered,
// human-readable list. Mirrors the same rule used in the student clients:
//   1. param_labels order first (label or prettified key + optional note),
//   2. then any remaining params keys, prettified.
export interface RenderedParam {
  label: string;
  value: string;
  note?: string;
}

export function prettifyKey(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatParamValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.map((x) => String(x)).join(", ");
  if (value == null) return "";
  return String(value);
}

export function renderParams(
  params: Record<string, unknown> | undefined,
  labels: ParamLabel[] | undefined
): RenderedParam[] {
  if (!params) return [];
  const out: RenderedParam[] = [];
  const covered = new Set<string>();
  for (const pl of labels ?? []) {
    if (!pl.key || !(pl.key in params)) continue;
    covered.add(pl.key);
    out.push({
      label: pl.label || prettifyKey(pl.key),
      value: formatParamValue(params[pl.key]),
      note: pl.note ?? undefined,
    });
  }
  for (const [key, value] of Object.entries(params)) {
    if (covered.has(key)) continue;
    out.push({ label: prettifyKey(key), value: formatParamValue(value) });
  }
  return out;
}

// --- brief @-references ------------------------------------------------------
// @{multi word ref} or @single_token, mirroring backend/params.py.
const REF_RE = /@\{([^}]+)\}|@([A-Za-z0-9_]+)/g;

export interface BriefRef {
  ref: string; // the text after @ (e.g. "max_number" or "Maximum result")
  key: string | null; // the param key it resolves to, or null if unknown
  label: string | null; // that key's label
  ok: boolean;
}

function labelMaps(labels: ParamLabel[] | undefined) {
  const keyLabel = new Map<string, string>();
  const labelKey = new Map<string, string>();
  for (const pl of labels ?? []) {
    if (!pl.key) continue;
    const label = pl.label || prettifyKey(pl.key);
    keyLabel.set(pl.key, label);
    labelKey.set(label.toLowerCase(), pl.key);
  }
  return { keyLabel, labelKey };
}

// Every distinct @-ref in the brief, flagged ok if it matches a param label.
export function scanBriefRefs(brief: string, labels: ParamLabel[] | undefined): BriefRef[] {
  const { keyLabel, labelKey } = labelMaps(labels);
  const seen = new Set<string>();
  const out: BriefRef[] = [];
  for (const m of brief.matchAll(REF_RE)) {
    const ref = m[1] ?? m[2];
    if (seen.has(ref)) continue;
    seen.add(ref);
    const key = keyLabel.has(ref) ? ref : labelKey.get(ref.toLowerCase()) ?? null;
    out.push({ ref, key, label: key ? keyLabel.get(key) ?? null : null, ok: key != null });
  }
  return out;
}

// Expand @-refs to "Label: value" using a variant's params (for the preview).
export function substituteBrief(
  brief: string,
  params: Record<string, unknown> | undefined,
  labels: ParamLabel[] | undefined
): string {
  const { keyLabel, labelKey } = labelMaps(labels);
  const p = params ?? {};
  return brief.replace(REF_RE, (whole, braced, token) => {
    const ref: string = braced ?? token;
    const key = ref in p ? ref : labelKey.get(ref.toLowerCase()) ?? null;
    if (key == null || !(key in p)) return whole; // unknown for this variant — leave as-is
    const label = keyLabel.get(key) || prettifyKey(key);
    return `${label}: ${formatParamValue(p[key])}`;
  });
}
