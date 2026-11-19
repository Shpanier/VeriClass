const HEBREW = /[֐-׿]/;

/** The direction of a piece of content (a question, an answer, a title, a
 *  name): right to left as soon as it has Hebrew in it, so it is aligned to the
 *  right and its words stay in order. dir="auto" looks only at the first letter,
 *  so a Hebrew sentence that opens with `make`, a file name or a Latin word was
 *  laid out left to right and came out mixed. Without Hebrew the browser decides
 *  (code and English stay left to right).
 *
 *  For content only: the dashboard's own sentences follow the dashboard's
 *  language (the page's dir), even when a Hebrew title is quoted in them. */
export function textDir(...parts: unknown[]): "rtl" | "auto" {
  return parts.some((p) => typeof p === "string" && HEBREW.test(p)) ? "rtl" : "auto";
}
