"""Variant-parameter helpers shared by the exercise routes and the tutor prompt.

The brief (`brief_md`) may contain @-references to a variant parameter, which are
expanded to "Label: value" for the student who has that variant:

    @max_number          -> Maximum result: 500
    @{Maximum result}    -> Maximum result: 500   (braces allow multi-word labels)

A reference resolves against the exercise's `param_labels` (by key or by label
text, case-insensitive). Unresolved references are left untouched, so stray '@'
in prose (e.g. an email) is never mangled.
"""
import re
from typing import Any

# @{multi word ref}  OR  @single_token
_REF_RE = re.compile(r"@\{([^}]+)\}|@([A-Za-z0-9_]+)")


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(x) for x in value)
    return str(value)


def prettify_key(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip().capitalize()


def _label_index(labels: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (key -> label, lowercased-label -> key) from param_labels."""
    key_label: dict[str, str] = {}
    label_key: dict[str, str] = {}
    for pl in labels or []:
        key = pl.get("key")
        if not key:
            continue
        label = pl.get("label") or prettify_key(key)
        key_label[key] = label
        label_key[label.lower()] = key
    return key_label, label_key


def substitute_brief(brief_md: str, params: dict, labels: list[dict]) -> str:
    """Expand @-references in the brief to "Label: value" using this variant's
    params. Unresolved references are left exactly as written."""
    key_label, label_key = _label_index(labels)

    def repl(m: re.Match) -> str:
        ref = m.group(1) or m.group(2)
        key = ref if ref in params else label_key.get(ref.lower())
        if key is None or key not in params:
            return m.group(0)  # not a known param for this variant — leave as-is
        label = key_label.get(key) or prettify_key(key)
        return f"{label}: {format_value(params[key])}"

    return _REF_RE.sub(repl, brief_md or "")
