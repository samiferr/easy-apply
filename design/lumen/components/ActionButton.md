Rounded-rectangle buttons for tool and toolbar actions, with a pressed state.

Use `ActionButton` for secondary, tool-like actions: toolbars, table row actions, toggles. It has an 8px radius, not a pill, so it reads as a tool rather than a call to action.

## Props

`isQuiet` — no background until hover. `isSelected` — when set (true or false) the button becomes a toggle with `aria-pressed`. `size` — `s`, `m`, `l`. `isDisabled`, `onPress`, `icon` (an `Icon` name or a node), `aria-label` (required when there is no text), `children`. With no children it becomes a square icon button.

## Do

- Use `isSelected` only for real toggles (bold, filter on).
- Group related action buttons with 8px (`spacing-100`) between them.
- Icon-only buttons need `aria-label`; the icon is hidden from assistive technology.

## Don't

- Don't use it for the main action of a page; use `Button`.
