Single-line text input with label, help text and an error state.

Use `TextField` for short free-text values. The label sits above the input; help text or an error sits below.

## Props

`label` (required for accessibility), `description` (help text), `errorMessage`, `validationState` (`invalid` swaps help text for the error and draws a 2px `negative-border` (red, 3:1), an alert icon inside the field and the message with an icon below), `placeholder`, `defaultValue` / `value`, `onChange(value)`, `type`, `isRequired` (adds `*`), `isDisabled`, `width`, `name`, `autoComplete`, `inputRef`, and `revealable` (adds a Show/Hide button for password fields).

## States

Default: 2px light gray `border-field` (#dadada). Hover: `border-field-hover` (a mid gray). Focus: the border turns dark gray (`border-focus`); there is no extra ring. Invalid: red `negative-border`, which stays red on focus. Disabled: `fill-disabled` with `border-disabled`.

## Do

- Always show a visible label; a placeholder is an example, never a label.
- Say what to fix in the error text, not just that something is wrong.
- Errors show an icon and text, not color alone.

## Don't

- Don't remove the 2px `border-field` or the visible label: the outline is deliberately soft (about 1.4:1 on white), so the label and the white fill are what make the field findable. Disabled fields use `fill-disabled` and `border-disabled` instead.
