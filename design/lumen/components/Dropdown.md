A button that opens a list of options and shows the chosen one.

Use `Dropdown` to choose one value from five to about fifteen options when a radio group would take too much room. For actions rather than values, use `Menu`.

## Props

`label` (required), `items` — array of `{key, label, description, isDisabled}`. `placeholder`, `description`, `errorMessage` with `validationState="invalid"`, `selectedKey` / `defaultSelectedKey`, `onSelectionChange(key)`, `isDisabled`, `width`, `defaultOpen`.

## Appearance

The button has no border: a light gray `fill-picker` background and the chevron mark it as a control, which sets it apart from the bordered text field. Hover and the open state deepen the fill (`fill-neutral-down`); keyboard focus adds the 2px `focus-ring`; an invalid dropdown gets a thin red outline plus the error message. Disabled uses `fill-disabled`.

## Behavior

Click, or press Up/Down on the button, to open. Up/Down/Home/End move the active option; Enter or Space chooses; Escape closes and returns focus to the button; Tab closes. The chosen option has a check and bold text. The popover opens below the button and scrolls past 240px.

## Do

- Keep option labels short and parallel.
- Provide a placeholder that says what to do ("Select a country").

## Don't

- Don't use a dropdown for two or three options; use `RadioGroup`.
