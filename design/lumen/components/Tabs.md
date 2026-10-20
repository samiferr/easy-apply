Switch between peer views of the same content. Only one panel shows at a time.

Use `Tabs` to split one object's content into views people move between freely (Overview, Files, Settings). For steps in a flow, use `Steps`; for a single control that switches a view mode, use a group of `ActionButton`s.

## Props

`items` — array of `{key, title, icon, aria-label, content, isDisabled}`. A tab can show a title, an icon and a title, or only an icon (then `aria-label` is required). `defaultSelectedKey` / `selectedKey`, `onSelectionChange(key)`. `orientation` (`horizontal` default, `vertical`), `size` (`s`, `m`, `l`, `xl`), `density` (`regular`, `compact`), `isEmphasized` (blue selected text and indicator), `keyboardActivation` (`automatic` default: arrow keys select; `manual`: arrows move focus, Enter or Space selects), `overflowMode` (`collapse` default: horizontal tabs that do not fit become a picker; `none`), `isDisabled`, `aria-label` or `aria-labelledby` (required).

## Anatomy and sizes

Measurements follow the Spectrum 2 tab tokens.

| Size | Height (compact) | Gap between tabs | Text | Icon | Icon to text |
| --- | --- | --- | --- | --- | --- |
| s | 40 (24) | 21 | 12 | 14 | 5 |
| m | 48 (32) | 24 | 14 | 18 | 6 |
| l | 56 (40) | 27 | 16 | 22 | 7 |
| xl | 64 (48) | 30 | 18 | 26 | 8 |

The tab list sits on a 1px `border-subtle` divider. The selected tab is marked by a 2px indicator in `content-default` (or `accent-content` when emphasized) that slides to the new tab in 130ms, plus darker text, so selection does not rely on color. Unselected text is `content-subdued`, hover and focus `content-default`, disabled `content-disabled`. Labels are medium weight so they do not shift when selected. The keyboard focus ring wraps the label with the Spectrum focus gap (8px at medium, 4px compact).

Vertical tabs stack with a 4px gap, 12px start padding, and the divider and indicator on the start edge.

## Behavior

The selected tab is the only tab stop; Tab moves into the panel next. Arrow keys move between tabs (Left/Right, or Up/Down when vertical; mirrored in right-to-left layouts) and skip disabled tabs, wrapping at the ends; Home and End jump to the first and last. With automatic activation the panel changes as focus moves; use `manual` when a panel is slow to load. When horizontal tabs no longer fit their container they collapse into a picker that lists every tab, and expand again when there is room. Reduced motion turns off the indicator slide.

## Do

- Keep titles to one or two words, in sentence case.
- Use three to seven tabs; use the same kind of label (all text, or all icon and text) across a set.
- Give icon-only tabs an `aria-label`; the label also shows as a tooltip.

## Don't

- Don't nest tabs inside tabs.
- Don't use tabs to filter a list; use a `Dropdown` or `SearchField`.
- Don't make every tab disabled except one; hide views people cannot use.
