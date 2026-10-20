A vertical list of rows with optional visual, description and selection.

Use `List` to show a short set of similar items, each with a title and optional supporting text. With `selectionMode` it becomes a listbox for choosing items.

## Props

`items` — array of `{key, title, description, visual, end}` (`visual` is a 32px node or initials; `end` is trailing text or a node). `aria-label` (required). `selectionMode` — `none` (default), `single`, `multiple`. `selectedKeys` / `defaultSelectedKeys` / `onSelectionChange(keys)`. `onAction(key)` makes each row a button when nothing is selectable.

## Behavior

In a selectable list, Up/Down/Home/End move focus; Space or Enter selects. A selected row has a filled background and a check icon.

## Do

- Keep each row to one title line and one description line.
- Use `List` for up to about 50 rows; use `Table` when rows have several fields.

## Don't

- Don't mix selectable and action rows in one list.
