A sortable, selectable data table with a sticky-weight header and row dividers.

Use `Table` to compare many objects across the same fields. It renders a real `<table>`, so screen readers get rows, columns and headers.

## Props

`columns` — array of `{key, title, align, width, isRowHeader, allowsSorting, render(row)}`. `rows` — array of objects with a unique `key`. `aria-label` (required). `density` — `compact` (32px rows), `regular` (40px), `spacious` (48px). `selectionMode` — `multiple` adds a checkbox column and a select-all header. `selectedKeys` / `defaultSelectedKeys` / `onSelectionChange(keys)`. `sortDescriptor` / `defaultSortDescriptor` / `onSortChange({column, direction})` — uncontrolled sorting is done for you. `emptyState` — shown when there are no rows.

## Do

- Mark one column `isRowHeader` (the name) so each row has a label.
- Right-align numbers and give them the same unit in the header.
- Show status with `StatusLight`: label plus dot, never a dot alone.

## Don't

- Don't put more than one action in a row; open a detail view instead.
- Don't rely on the selected row's tint alone: its checkbox is checked too. Selected rows use `selected-subtle` (10% accent); hover uses `row-hover` (7% gray).
