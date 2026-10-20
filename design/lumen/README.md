Lumen is a calm, neutral-first design system for dense productivity software. Its structure follows Adobe Spectrum's: a small set of palette steps, semantic tokens that reference them, a size scale tied to component heights, and pill-and-rounded-rectangle controls. Build every surface from the tokens below; never hard-code a color, size or radius.

## Content fundamentals

- Write in plain, direct sentences. Address the person as "you"; refer to the product as "we" only when it speaks for the company.
- Use sentence case everywhere: "Save changes", "Project settings". Capitalize only proper nouns.
- Buttons are verbs, one to three words: "Save", "Add member", "Delete project". Never "OK" or "Submit".
- Say what happened and what to do next. Error: "Enter a complete email address." Not "Invalid input."
- No emoji, no exclamation marks, no decorative punctuation. Status is always a word ("Approved"), never a color or icon alone.
- Numbers use digits and tabular figures: "12 files", "64%".

## Visual foundations

**Color.** The page is `background-base`; raised panels are `background-layer-1`, cards and fields are `background-layer-2`, floating surfaces are `background-elevated`. Set text in `content-default`, headings in `content-heading`, secondary text in `content-subdued`; disabled text is `content-disabled` and is never used for live content. The one accent hue is blue: `accent-background` fills the single main action, `accent-content` colors links. Text on any filled control is `on-accent` (`on-neutral` on `neutral-background`, `on-notice` on `notice-background`). Status uses four semantic families (`informative`, `positive`, `notice`, `negative`), each paired with an icon and a word; alerts add a matching `*-subtle` tint behind the text. Use palette steps like `blue-900` only for charts and illustration.

**Themes.** `light` and `dark` are the same names with different values; write components once. In dark, filled accent controls step one shade lighter (`blue-800` instead of `blue-900`) and the notice label turns black.

**Type.** The face is Source Sans 3 (code: Source Code Pro). Set body copy in `body-m` (16px, 1.5), controls in `detail-m` or `title-s` (14px), page headings in `heading-l` and `heading-xl` (800 weight), section titles in `title-l`. Spectrum's scale runs 11 to 73px on desktop; add about 20% on touch.

**Spacing.** Use the spacing tokens only: `spacing-75` (4px) inside a control, `spacing-100` (8px) between related controls, `spacing-200` (12px) between a label and its field, `spacing-300` (16px) card padding, `spacing-400` (24px) between sections, `spacing-600` (40px) from the window edge.

**Shape.** Buttons, badges, switches, status dots and progress tracks are fully round (`corner-radius-full`). Fields, pickers, cards and alerts use `corner-radius-500` (8px). Checkboxes use `corner-radius-100` (4px); dialogs `corner-radius-800` (16px).

**Size.** Controls come in five heights: `component-height-50` (20), `-75` (24), `-100` (32, default), `-200` (40), `-300` (48).

**Borders and shadow.** Text fields, text areas and search fields have a 2px light gray `border-field` (#dadada in light; hover `border-field-hover`). It is a soft outline, about 1.4:1 on white, so these fields always carry a visible label and sit on `background-layer-2`. Checkboxes, radios and switches keep the stronger `border-default` (3:1 on the page), because a small control has nothing else to show where it is. Dropdowns and other select-style buttons have no border at all: a light gray `fill-picker` separates them from the page. Hover moves it to `border-hover`. On focus a text or search field's border darkens to `border-focus` (dark gray) and stays 2px and replaces the blue ring; the Dropdown button deepens its fill on hover and while open, and shows the blue ring on keyboard focus. An invalid field changes its 1px border to `negative-border` and adds an alert icon and message. A disabled field uses `fill-disabled` with `border-disabled` and `content-disabled` text. Never use `border-subtle` on a control: it is for decorative dividers only. Menus and pickers have no border in light and a 1px `border-popover` in dark. Floating surfaces use `shadow-elevated`; dragged items `shadow-dragged`. Cards inside the page use a border or a layer step, not a shadow.

**Focus.** Every interactive element shows a 2px `focus-ring`, offset 2px, on keyboard focus. It meets 3:1 on every surface. Do not remove it.

**Motion.** Hover and press states change color over 130ms. Respect `prefers-reduced-motion`: indeterminate progress stops animating.

**States.** Hover steps one shade (`accent-background-hover`, `fill-neutral-hover`); pressed steps two (`accent-background-down`, `fill-neutral-down`); disabled drops to `fill-neutral-hover` with `content-disabled` text.

## Accessibility

Text colors hold 4.5:1 on the grounds named in their usage notes, in both themes; borders, focus rings and icons that carry meaning hold 3:1. Status never relies on hue alone: success and failure always carry a word and an icon.

## Iconography

Use the `Icon` component: 56 outline icons from Lucide (ISC licence), drawn at Spectrum's sizes with a 2.4 stroke on Lucide's 24px grid (2px at 20px), round caps and joins, single-ink in `currentColor`. Sizes follow the control they sit in: 16 in small, 20 in medium, 22 in large, 26 in extra-large (`icon-size-75`, `-100`, `-200`, `-300`). Pass `icon="name"` to `Button` and `ActionButton` and they size it for you. Icons never carry meaning alone: add a label, or an `aria-label` on an icon-only button. Four filled status glyphs (info, positive, notice, negative) are built into `InlineAlert`, `Badge` and field messages. Do not mix another icon set on the same screen. Spectrum's own workflow icons are Adobe property and are not included.

## Using the components

Load `tokens.css`, `components/bundle.css`, React 18, then `components/bundle.js`. Components live on `window.Lumen` and are listed in `components/index.d.ts`. Each component's guidelines are in `components/<Name>/README.md`. The system ships thirty-one components. Foundations: Icon. Actions: Button, ActionButton, Menu. Forms: TextField, TextArea, SearchField, Dropdown, Checkbox, Switch, RadioGroup, LoginForm. Navigation: Tabs, Tree, Pagination, Steps. Containers: Card, Table, List, Accordion, Disclosure, Drawer. Status and feedback: StatusLight, Badge, ProgressBar, InlineAlert, EmptyState, Avatar, AvatarGroup, Timeline. Layout: Divider. Anything else in a layout (dialogs, tooltips, toasts) you build from tokens in the same shapes.

Lumen's palette, spacing, radius, type-size and component-height values are adapted from Adobe's open-source Spectrum design tokens (Apache License 2.0). Lumen is an independent system and is not affiliated with or endorsed by Adobe; it uses none of Adobe's marks, fonts or icons. Icons are from Lucide (ISC licence, https://lucide.dev); the licence text is in `lucide-license.md`.

## Easy Apply's deviations

This copy of Lumen is the source of truth for Easy Apply's interface. The app
follows it everywhere except where it would fall short of WCAG 2.2 AA; each
departure is listed here and next to the code that implements it.

| Lumen says | Easy Apply does | Why |
| --- | --- | --- |
| Text fields rest on `border-field` (#dadada, about 1.4:1) | `border-default` (3.2:1 light, 4.6:1 dark), 2px | SC 1.4.11 asks 3:1 of the boundary that identifies a control |
| Dropdowns are borderless on `fill-picker` (about 1.2:1) | Native `<select>` styled as a text field, same border | Same reason; one field style for every input |
| Default control height 32px | Buttons and fields 40px (`btn-sm` is the 32px desktop size) | Lumen's touch scale; well clear of SC 2.5.8's 24px minimum |
| Checkbox 16px | 20px, label clickable | Larger target for the same visual weight |
| Accent text on `*-subtle` tints | Never: text on tints stays `content-default` / `content-heading` | `accent-content` on `informative-subtle` and `negative-content` on `negative-subtle` measure 4.2:1 in light |
| Tabs: emphasized is an option | App tabs are always emphasized (accent label and indicator) | One consistent "you are here" cue across skill categories, job sections, settings and the portal |
| (not specified) | Flash messages stay until dismissed | SC 2.2.1: no message disappears on a timer |
| (not specified) | Off-canvas navigation is `invisible` when closed and focus moves into it on open | Hidden links must not be in the tab order |

Contrast was measured on the generated `static/src/tokens.css` for every
foreground/background pair the components use, in both themes.

Tabs follow the Spectrum 2 rebuild of `components/Tabs.md` (1px divider, sliding 2px indicator, medium-weight labels, vertical and compact variants, overflow into a picker) through `.tab-strip*` in `static/src/input.css` and `static/js/tabs.js`.

Icons are rendered server-side by `{% icon "name" %}` (`core/templatetags/lumen.py`,
paths in `core/icons.py`): the 56 Lumen icons plus a few more Lucide glyphs
(briefcase, graduation-cap, languages, sun, moon, shield, activity,
credit-card, flag, file-text, award, target, chevrons-left). Lucide's licence is
in `lucide-license.md`.
