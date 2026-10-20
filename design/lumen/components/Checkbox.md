Square checkbox with checked and indeterminate states.

Use `Checkbox` when someone can pick any number of options, or to confirm a statement.

## Props

`defaultSelected` / `isSelected`, `onChange(checked)`, `isIndeterminate` (for a parent of partly-selected children), `isDisabled`, `children` (the label).

## Do

- Phrase the label so "checked" means yes.
- Stack checkboxes vertically with 12px (`spacing-200`) between them.

## Don't

- Don't use a checkbox for an action that takes effect immediately; use `Switch`.
