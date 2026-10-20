On/off toggle that takes effect immediately.

Use `Switch` for a setting that applies the moment it is flipped. It has `role="switch"`.

## Props

`defaultSelected` / `isSelected`, `onChange(selected)`, `isDisabled`, `children` (the label).

## Do

- Label what the switch controls, not its state: "Notifications", not "Turn notifications on".
- Use it only for instant settings; for a value saved with a form, use `Checkbox`.

## Don't

- Don't rely on the handle position alone to show state: the accent fill also changes.
