A multi-line text input for longer free text, such as descriptions and notes.

Use `TextArea` when the answer may run past one line. For a short value use `TextField`; for a query use `SearchField`.

## Props

`label` (required for accessibility), `description`, `errorMessage` with `validationState="invalid"`, `placeholder`, `defaultValue` / `value`, `onChange(value)`, `rows` (default 3), `resize` (`vertical` by default, or `none`), `maxLength`, `isRequired`, `isDisabled`, `width`, `name`.

## Appearance

It matches the text field: 2px light gray `border-field` (#dadada), 8px radius, `background-layer-2`. On focus the border turns dark gray (`border-focus`). Invalid is a red `negative-border` with the message and an icon below; disabled uses `fill-disabled` with `border-disabled`. The minimum height is two single-line fields (64px), and the handle at the bottom right resizes it vertically.

## Do

- Keep the label visible; use the description for limits ("Up to 200 characters").
- Size `rows` to the expected answer so people do not have to scroll for a typical entry.

## Don't

- Don't use a `TextArea` for a one-line value.
