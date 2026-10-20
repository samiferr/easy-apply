Tonal is a Material Design 3 style system built on a five-colour palette: tonal colour roles that pair a fill with the text that sits on it, a fifteen-step type scale in Roboto, soft corner shapes, and state layers instead of hard hover colours. It is an original implementation built on M3's published conventions; it contains no Google assets or marks. Load `tokens.css`, then `components/bundle.css`, then React and `components/bundle.js` (global `Tonal`).

## Content fundamentals

- Write in sentence case everywhere: buttons, tabs, titles, list headlines ("Discard draft", not "Discard Draft").
- Address the person directly with "you" and "your"; say "we" only for the product. No exclamation marks, no emoji.
- Buttons and chips are verbs or short nouns of one to three words: "Save", "Add to cart", "Undo". Never "OK" or "Click here".
- Titles state the decision or subject ("Discard draft?"); supporting text gives the consequence in one or two plain sentences.
- Error text says what to do next: "Enter a valid email", not "Invalid input".

## Visual foundations

**Source palette.** Five brand colours seed the system, kept exact as tokens: `ocean-blue` #118ab2, `emerald` #06d6a0, `golden-pollen` #ffd166, `bubblegum-pink` #ef476f and `dark-teal` #073b4c. Use them for illustration, charts, covers and brand moments, never for interface text or controls: none of them reaches 4.5:1 with white or dark text across the board. Interface colour always comes from the roles below.

**Role colours.** Following Material 3, each source colour is expanded into a tonal palette (HCT, tones 0–100) and roles are read from fixed tones: light theme `primary` tone 40, `on-primary` 100, `primary-container` 90, `on-primary-container` 10; dark theme tones 80, 20, 30, 90. The mapping is `primary` from `ocean-blue`, `secondary` from `emerald` (chroma reduced so it supports rather than competes), `tertiary` from `golden-pollen`, `error` from `bubblegum-pink`, and the neutral surfaces from `dark-teal`'s hue at chroma 6 (neutral-variant 8). Every fill has a partner `on-*` token for text and icons on it; never put `on-surface` on a `primary` fill or the reverse. `primary-fixed`, `secondary-fixed` and `tertiary-fixed` (with `-dim` and `on-*-fixed` partners) keep the same value in both themes for surfaces that must not change.

**Surfaces.** The page is `surface` (`background` is identical). Structure a screen with the surface ladder, lowest to highest: `surface-container-lowest`, `surface-container-low`, `surface-container`, `surface-container-high`, `surface-container-highest`; `surface-dim` and `surface-bright` are the extremes for dimmed and lifted regions. Primary text is `on-surface`; secondary text, labels and inactive icons are `on-surface-variant`.

**Emphasis.** Spend `primary` on one thing per view. Use `secondary-container` for supporting actions and selected states, `tertiary` / `tertiary-container` sparingly for highlights and informational callouts, and `error` only for errors and destructive confirmation, always with an icon or words as well as colour. Don't swap roles to chase a brand colour: if you want more green, change the selected-state surface in one place rather than recolouring `primary`.

**Borders.** A border that identifies a control (outlined button, text field, unchecked checkbox) is `outline`, which holds 3:1 on `surface`. `outline-variant` is for decorative dividers and outlined-card edges only; it falls below 3:1, so never rely on it alone to show where a control is.

**Type.** Set everything in Roboto using the scale's own classes: `display-*` for hero moments, `headline-*` for screen and dialog titles, `title-*` for bars, cards and list heads, `label-*` for buttons, tabs and chips, `body-*` for reading and field text. Don't invent sizes between steps.

**Shape.** Corners come from the radius scale: `radius-full` for buttons, switches, icon buttons and indicators; `radius-xl` for dialogs and large FABs; `radius-lg` for FABs and sheets; `radius-md` for cards; `radius-sm` for chips; `radius-xs` for snackbars and text-field tops.

**Elevation.** Hierarchy is carried first by surface tone and second by shadow. Use `elevation-1` for elevated cards and buttons, `elevation-3` for FABs, dialogs and snackbars; `elevation-0` everywhere else. Cards at rest never exceed level 1.

**State.** Hover, focus and press are a `currentColor` veil at `state-hover` (0.08), `state-focus` (0.10) and `state-pressed` (0.10) opacity; dragged is `state-dragged` (0.16). Disabled content is 38% opacity (`state-disabled-content`) on a 12% container (`state-disabled-container`). Keyboard focus also draws a 3px solid `secondary` ring offset 2px, which holds at least 3:1 on every surface tone in both themes.

**Spacing.** Build on a 4px grid with the `space-*` steps: 16px screen and card padding, 24px button side padding, 8px between icon and label, 48px minimum touch targets.

**Motion.** Use a standard easing of `cubic-bezier(0.2, 0, 0, 1)`; 150ms for state changes and toggles, 200ms for indicators and bars, 250–300ms for dialogs and sheets. Animate colour, opacity and transform only, and honour `prefers-reduced-motion` by removing movement and keeping fades.

**Themes.** `light` and `dark` supply a value for every colour token. Switch with `data-theme="dark"` on `html`; never hard-code hex values in components.

## Iconography

Icons are Material-style 24px glyphs, single-weight and filled, drawn in `currentColor`. The bundle's `Icon` carries a small inline set (add, close, check, menu, search, arrow_back, more_vert, home, favorite, person, edit, star, mail, remove, error). For anything else use Material Symbols Rounded at weight 400, 24px grid, and keep the same colour rules. Icons are never decorative emoji; an icon that carries meaning has a label.

## Using the components

Use `Button` for text actions and `IconButton` for glyph-only actions (it requires a `label`). One `Fab` per screen, one filled `Button` per view. `Card` has three variants (elevated, filled, outlined); pick one per surface. Navigation is `TopAppBar` plus `NavigationBar` on compact layouts, `Tabs` for sibling views of one subject. Inputs are `TextField`, `Checkbox`, `Radio` and `Switch`; always label them. `Dialog` and `Snackbar` interrupt: a dialog asks for a decision, a snackbar only reports and offers one undo-style action. Per-component guidelines live in each component's README; props are in `components/index.d.ts`.

## What this system leaves out

Date and time pickers, menus, sheets, sliders, search, progress indicators, navigation drawer and rail, tooltips and segmented buttons are not built yet. Follow the same tokens and state rules if you add them.
