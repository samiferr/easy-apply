# Spectrum 2 conformance

Lumen's measurements are checked against the published Spectrum 2 design tokens (the open-source `@adobe/spectrum-tokens` package, version 15.4.1): palette, spacing, corner radius, component heights, and the per-component tokens listed below. Where a token exists, Lumen uses the same value. The Spectrum guideline pages on spectrum.adobe.com render only in a browser and could not be read here, so usage guidance is written from the tokens and general accessibility practice, not copied from those pages.

## Values that match Spectrum 2

| Area | Lumen value | Spectrum 2 token |
| --- | --- | --- |
| Control heights | 20, 24, 32, 40, 48, 56, 64 | `component-height-50` to `-500` |
| Spacing scale | 1, 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96 | `spacing-25` to `-1000` |
| Corner radius | 3 to 10, 16, full | `corner-radius-75` to `-800`, `-full` |
| Button | pill; padding 12/16/20/24; min width 2.25 × height; icon gap 5/6/7/8 | `component-pill-edge-to-text-*`, `button-minimum-width-multiplier`, `text-to-visual-*` |
| Action button | radius 7/8/9 by size; padding 9/12/15 | `corner-radius-medium-size-*`, `component-edge-to-text-*` |
| Text field | 32 tall, 8 radius, 2px border (owner's choice; Spectrum's token is 1px), 12 edge to text, 208 wide, asterisk gap 4, alert icon 12 from edge and 12 before the text | `field-default-width-medium`, `field-edge-to-alert-icon-medium`, `field-text-to-alert-icon-medium`, `field-label-text-to-asterisk-medium` |
| Search field | 32 tall (24, 40), 128px minimum width, icon 12 from the edge, same border rules as the text field | `search-field-minimum-width-multiplier`, `component-height-*` |
| Control borders (checkbox, radio, switch) | `border-default` is gray-500 in light and gray-600 in dark; hover one step further; disabled `fill-disabled` (gray-100) with `border-disabled` (gray-300); invalid `negative-border` (red-900) and `negative-border-hover` (red-1000) | `neutral-visual-color`, `disabled-background-color`, `disabled-border-color`, `negative-border-color-default`, `negative-border-color-hover` |
| Checkbox | 16px, 2px border, 4 radius | `checkbox-control-size-medium` |
| Radio | 14px, 4px selection ring | `radio-button-control-size-medium`, `radio-button-selection-indicator` |
| Switch | 26 × 16 track, 8px handle, 10px when on | `switch-control-width/height-medium`, `switch-handle-*` |
| Tabs | 48 tall, 24 gap, 2px indicator | `tab-item-height-medium`, `tab-gap-horizontal-medium`, `tab-selection-indicator-thickness` |
| Status light | 10px dot, 6px gap | `status-light-dot-size-medium`, `status-light-text-to-visual-100` |
| Progress bar | 6px thick | `progress-bar-thickness-medium` |
| Avatar | 16 to 56px sizes; overlap 5/6/8/10; 1px ring; 30% disabled | `avatar-size-*`, `avatar-to-avatar-*`, `avatar-border-width`, `avatar-opacity-disabled` |
| Divider | 1, 2, 4px | `divider-thickness-*` |
| Table | rows 32, 40, 48; 12px cell padding; selected row 10% accent, hover 7% gray | `table-row-height-medium-*`, `table-item-padding-regular`, `table-selected-row-background-opacity`, `table-row-hover-opacity` |
| List, tree | rows at least 40 tall; 8px radius | `list-view-minimum-height`, `tree-view-minimum-height`, `list-view-item-top-corner-radius` |
| Popover and menu | 8px padding, 8px gap from trigger, 32px items; border 1px gray-400 in dark and none in light | `popover-padding`, `popover-gap`, `popover-border-color`, `popover-border-opacity` |
| Steps | 16px markers, 2px track | `steplist-visual-size-medium`, `steplist-track-thickness-medium` |
| Dialog and drawer | title 22, body 16 | `standard-dialog-title-font-size`, `standard-dialog-body-font-size` |
| Empty state | title 22, body 14 | `illustrated-message-title-size`, `illustrated-message-body-size` |
| Focus ring | 2px, 2px gap, `blue-800` | `focus-indicator-thickness`, `focus-indicator-gap`, `focus-indicator-color` |
| Icons | 14, 16, 20, 22, 26 | `workflow-icon-size-50` to `-300` |
| Accent and status fills | `blue-900` light, `blue-800` dark; `red`, `green`, `orange` the same way | `accent-background-color-default`, `negative-`, `positive-`, `notice-` |

## Where Lumen differs on purpose

- **Typeface.** Spectrum uses Adobe Clean, which is not licensed for reuse. Lumen uses Source Sans 3 at the same sizes and line heights.
- **Icons.** Spectrum's workflow icons are Adobe's and are not licensed for reuse. Lumen uses Lucide (ISC licence) at Spectrum's icon sizes with a 2px-at-20px stroke (heavier than Spectrum's lighter strokes, at the owner's request), so the shapes are not Spectrum's. Lucide strokes can fall between pixels at 20 and 22px; Spectrum's icons are pixel-aligned.
- **Themes.** Spectrum ships light, dark and darkest. Lumen ships light and dark only.
- **Scale.** Spectrum has a touch (mobile) scale and sizes from extra-small to extra-extra-large for most controls. Lumen implements the desktop scale, and buttons in small, medium, large and extra-large.
- **Quiet and static variants.** Spectrum's quiet fields and static-color buttons are not included.
- **Components with no Spectrum 2 equivalent.** Pagination, Timeline, Drawer, LoginForm and Badge are Lumen additions built from the same tokens (heights, radii, spacing, colors). Disclosure and Accordion follow Spectrum's accordion spacing.
- **Names.** Spectrum's Picker is Lumen's Dropdown, Steplist is Steps, Illustrated message is EmptyState, Tree view is Tree.

## Corrections from the form-input review

- Dark-theme field, checkbox, radio and switch borders were gray-500 (3.1:1 on the field background, so they looked faint). They now follow Spectrum's `neutral-visual-color` (gray-600 in dark), which gives 4.6:1 on `background-layer-2`.
- Disabled fields used a transparent fill and a `content-disabled` outline. They now use Spectrum's disabled fill and border (`fill-disabled`, `border-disabled`).
- Invalid fields change the border color to `negative-border` (darker on hover) and add the in-field alert icon and message, so the state is never color alone.
- Popover borders were removed in both themes; Spectrum keeps one in dark, so `border-popover` is transparent in light and gray-400 in dark.
- Text fields, text areas and search fields use a 2px border (Spectrum's `picker-border-width` is 1px), darkening to `border-focus` (gray-800) on focus. Dropdowns and other select-style buttons have no border and use a light gray fill (`fill-picker`, gray-100) that deepens on hover. These follow the owner's direction and the look of the React Spectrum text field and picker examples; the Spectrum 2 token package has no separate tokens for them. The borderless dropdown relies on its fill, chevron and label to be recognizable as a control; its fill alone is about 1.2:1 against a white page, below the 3:1 a visible outline would give, so keep a visible label and chevron on every dropdown.
- Text, text area and search field borders are `border-field` (gray-300, #dadada in light) at the owner's direction, with `border-field-hover` (gray-500) on hover. Spectrum's `neutral-visual-color` for these is gray-500 (3.2:1); #dadada is about 1.4:1 on white (1.6:1 in dark), below the 3:1 that WCAG 1.4.11 asks of a control's boundary. Lumen keeps a visible label, a white fill and a darker hover and focus border so the field is still findable, but a stricter accessibility review would flag the resting border. Checkboxes, radios and switches keep `border-default`.
- The field background is `background-layer-2`; the token package does not name a separate field background, so this one is Lumen's choice.

## Not yet matched

- Field and control sizes other than medium (small, large, extra-large) for text fields, checkboxes, radios and switches.
- Spectrum's keyboard focus treatments for each control (for example the inset gap on tabs).
- Table section headers, column resizing and drag-and-drop.
