A bottom bar of three to five top-level destinations, with a pill indicator on the current one.

**You provide:** `items` (`[{label, icon, badge?}]`; `badge` is a count or `true` for a dot), `value`/`onChange` (or `defaultValue`).

- 80px tall on `surface-container`; the active destination gets a `secondary-container` pill and a bold label.
- Labels are always visible, one word.
- Use on compact widths; switch to a rail or drawer from 600px up (your layout's job).
