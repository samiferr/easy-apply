A labelled single-line text input with a floating label, filled and outlined styles, supporting text and an error state.

**You provide:** `label`, `variant` (`filled` default, `outlined`), `value`/`onChange` (or `defaultValue`), optional `leadingIcon`, `trailingIcon`, `supportingText`, `error` + `errorText`, `disabled`, `type`, `width`.

- Always show a label; never use placeholder text as the label.
- Error text says what to do ("Enter a valid email"), is announced via `aria-describedby`, and the trailing error icon means colour is never the only cue.
- Outlined fields assume a `surface` ground; override `--tn-field-ground` when placing them on another tone.
- 56px tall; the label floats to 12px on focus or when filled.
