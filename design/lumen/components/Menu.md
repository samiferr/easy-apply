A button that opens a list of actions.

Use `Menu` for a short list of commands that apply to the thing next to it. Choosing an item runs it and closes the menu. It shares its behavior with `Dropdown` but has no selected value.

## Props

`label` (the button text), `items` — array of `{key, label, description, isDisabled, isDestructive}`. `onAction(key)`, `isDisabled`, `defaultOpen`.

## Do

- Order items by frequency; put destructive items last.
- Use verbs for item labels.

## Don't

- Don't use a menu to choose a value that stays visible afterwards; use `Dropdown`.
