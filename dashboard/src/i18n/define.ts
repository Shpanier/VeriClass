/** One area's strings, English and Hebrew side by side. A key missing from the
 *  Hebrew half is a compile error, so the two never drift apart.
 *  {name} in a string is filled by t("key", { name: ... }). */
export function defineStrings<E extends Record<string, string>>(en: E, he: Record<keyof E, string>) {
  return { en, he };
}
