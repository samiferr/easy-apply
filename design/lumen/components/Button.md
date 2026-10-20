Pill-shaped buttons in four variants, fill and outline.

Use `Button` for the main actions on a page. Pill-shaped, bold label, 32px tall at the default medium size.

## Props

`variant` — `accent` (default), `primary`, `secondary`, `negative`. `outline` — draws a 2px border instead of a fill. `size` — `s`, `m`, `l`, `xl` (24, 32, 40, 48px). `isDisabled`, `onPress`, `icon` (an `Icon` name such as `"add"`, or a node, placed before the label; sized to the button), `children` (the label).

## Do

- One `accent` button per view or dialog; it is the single most important action.
- Use `primary` or `secondary` for everything else, `negative` only for destructive actions that you also confirm.
- Write the label as a verb: "Save changes", "Delete project".
- Keep the focus ring: 2px `focus-ring`, 2px offset.

## Don't

- Don't set text on a fill by hand; the stylesheet pairs `on-accent`, `on-neutral` and `on-notice` for you.
- Don't use a button to navigate; use a link.

A button is never narrower than 2.25 times its height, so short labels like "OK" keep a comfortable target.
