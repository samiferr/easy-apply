Outline icons from Lucide (ISC licence), drawn at Spectrum's sizes with a 2px stroke at 20px.

Use `Icon` to add meaning or speed up scanning next to a label, or on its own in an icon button. There are 56 icons, each mapped to a Lucide icon; `Lumen.iconNames` lists them.

## Props

`name` (required, one of `Lumen.iconNames`), `size` — `xs` (14), `s` (16), `m` (20, default), `l` (22), `xl` (26), or a number of pixels. `label` or `aria-label` — gives the icon an accessible name; without it the icon is hidden from assistive technology. `strokeWidth` — in Lucide's 24-unit grid; the default 2.4 is 2px at 20px, and the stroke scales with the size. Only set it for glyphs inside small controls (checkbox ticks use 3.6). `className`.

## Do

- Color icons with `currentColor`: set the text color of the parent, and the icon follows. Use `content-default` or `content-subdued` for most icons, `accent-content` for selected, and the `*-content` tokens for status.
- Pair an icon with a text label whenever the meaning is not universal. An icon-only control must carry `aria-label` on the button.
- Match the icon size to the control: 16 in small buttons, 20 in medium, 22 in large, 26 in extra large. Buttons and `ActionButton` do this for you when you pass `icon="name"`.
- Keep one icon style on a screen. Do not mix these with another icon set.

## Don't

- Don't use an icon as the only signal of status; add the word.
- Don't scale icons with CSS; choose a size.
- Don't add fills or strokes of your own color: icons are single-ink.

## Source and Spectrum fit

Icons are Lucide 1.50 (https://lucide.dev, ISC licence, which allows reuse with the licence notice kept; some shapes derive from Feather, MIT). Lucide draws on a 24px grid with a 2px stroke; Lumen draws them at Spectrum's workflow-icon sizes (14, 16, 20, 22, 26) with a 2.4 stroke (2px at 20px), round caps and joins, single ink in `currentColor`, so weight and sizing sit close to Spectrum's. They are not Spectrum's own glyphs, and at 20 and 22px a stroke can land between pixels, so edges look a little softer than Spectrum's pixel-aligned icons. The four filled status glyphs (info, positive, notice, negative) are filled circles and triangles with the Lucide glyph cut out, since Lucide has no filled set.

| Lumen name | Lucide icon |
| --- | --- |
| add, remove, close | plus, minus, x |
| home, delete, edit, filter, sort | house, trash, pencil, funnel, arrow-up-down |
| more, grid, chat, sliders | ellipsis, layout-grid, message-square, sliders-horizontal |
| alert, error, success, help | triangle-alert, circle-alert, circle-check, circle-question-mark |
| unlock, refresh | lock-open, refresh-cw |

Every other name matches its Lucide name.
