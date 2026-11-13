# The dashboard's design system

The lecturer's dashboard is used live, in front of a class, by people who did
not build it. Every screen follows the same few rules so that it reads as one
product and nothing has to be learned twice.

## Rules

1. **No inline colours, sizes or fonts.** Style with the classes in
   `src/styles/` and the components in `src/components/ui/`. `style={{…}}` is
   for values computed at run time only (a width from data, a grid position).
   A hex colour in a `.tsx` file is a bug; add a token to `tokens.css` if one
   is missing.
2. **One primary action per screen or dialog** (`variant="primary"`). Every
   other button is `secondary` (the default) or `quiet`. Red is for actions
   that delete or disconnect.
3. **Every action ends in something the lecturer sees**: the screen changes,
   or a toast says it worked (`toast.success`) or why it didn't
   (`toast.error`). Nothing fails only in the console.
4. **Confirm what reaches the whole class or can't be undone** with
   `useConfirm()`. The confirming button names the action ("Delete the
   meeting"), never "OK".
5. **Say what an empty list is for** with `<EmptyState>`: what belongs here
   and the button that adds it. Show `<Loading>` while the first request is
   out, so "nothing yet" and "still loading" never look the same.
6. **Plain words.** Lecturer, student, tutor (the AI). No file names,
   environment variables, "slug", "probe" or "variant" without a few words
   that say what it is. Sentence case, no exclamation marks.
7. **Both languages, always.** Every string goes through `t()`. Add new
   strings to your area's file in `src/i18n/` (English and Hebrew side by
   side; a missing half doesn't compile). Use logical CSS properties
   (`margin-inline-start`, not `margin-left`) so Hebrew flips by itself, and
   `dir="auto"` on anything a person typed.
8. **Times** come from the server in UTC: show them with `<Time>`, never raw.
9. **Keyboard and screen readers**: real `<button>`s, a `<label>` (or
   `aria-label`) on every control, dialogs through `<Modal>`.

## Building blocks

All exported from `src/components/ui` (`import { Button, Modal, … } from "./ui"`).

| Component | Use it for |
|---|---|
| `Button` | Every button. `variant`: `primary`, `secondary`, `quiet`, `link`, `success`, `warn`, `danger`, `danger-soft`, `brand-soft`. `size`: `sm`, `md`, `lg`. `icon={<Icon />}`, `busy`, `block`, `iconOnly` (+ `aria-label`). |
| `Input`, `Select`, `Textarea` | Bare controls (`small`, `inline`, `mono`). |
| `FormField` | Label + control + hint or error. `Field` is the one-line version for a text input or textarea. |
| `Check`, `Switch` | A checkbox with its text; an on/off switch. |
| `Modal` | Every dialog: `title`, `subtitle`, `footer`, `size` (`sm` `md` `lg` `xl`), `dirty` (asks before discarding changes). Escape, focus trap and scroll lock are built in. |
| `Notice` | A message in the page: `tone` = `info`, `success`, `warning`, `danger`; optional `title` and `action`. |
| `EmptyState`, `Loading`, `Spinner` | Nothing here yet; still loading. |
| `useToast()` | `toast.success(text)`, `toast.info(text)`, `toast.error(err)` or `toast.error("Couldn't save the course", err)`. |
| `useConfirm()` | `if (!(await confirm({ title, body, confirmLabel, danger }))) return;` |
| `Time` | `<Time value={serverString} />` (relative), `mode="clock"`, `mode="full"`. |
| `CopyButton` | Copies text and says so. |

Icons: `lucide-react` (`import { Trash2 } from "lucide-react"`), 16 px inside
buttons. Use an icon where it helps recognition, not as decoration; emoji are
not used as icons.

## Classes

Components (`components.css`): `vc-card` (+ `--success` `--warning` `--danger`
`--info` `--brand` `--muted` `--tight` `--pad-lg` `--flat`), `vc-section`
(`__head`, `__title`, `__hint`, `__actions`), `vc-badge` (+ `--success`
`--warning` `--danger` `--info` `--brand`, `--solid-*`, `--count`), `vc-dot`,
`vc-table` inside `vc-table-wrap`, `vc-pre` (+ `--light`), `vc-quote`, `vc-kv`,
`vc-grid` (+ `--wide`), `vc-segmented`, `vc-tabs` / `vc-tab`, `vc-divider`.

Helpers: `u-row`, `u-col`, `u-wrap`, `u-between`, `u-grow`, `u-push`,
`u-gap-4…24`, `u-mt-4…24`, `u-mb-0…24`, `u-muted`, `u-soft`, `u-danger`,
`u-success`, `u-warning`, `u-xs` `u-sm` `u-md` `u-lg`, `u-bold`, `u-nowrap`,
`u-prewrap`, `u-truncate`, `u-sr` (screen readers only).

Something an area needs that isn't here goes in that area's own stylesheet
(`src/styles/<area>.css`, imported by the component), built from the tokens.

## Layout of the code

```
src/
  App.tsx            which screen comes first; the class page
  app/               the frame: top bar, first run, settings, share, checklist
  components/        the screens and dialogs
  components/ui/     the building blocks above
  i18n.tsx, i18n/    strings (one file per area)
  lib/               time, errors, connection state
  styles/            tokens.css, base.css, components.css, shell.css, <area>.css
  api.ts, types.ts   the server's API
```

The IDE plugin's screens (exam monitoring, terminal log, submissions, log
verification) show only when `useFeatures().plugin` is true.

`npm run build` type-checks and writes the dashboard into `../backend/web`,
which the server serves at `/`; that folder is committed, so running a class
needs no Node. Rebuild and commit it with every dashboard change.
