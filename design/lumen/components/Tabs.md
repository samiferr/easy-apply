Switch between related views of the same content.

Use `Tabs` to split one object's content into peer views. Only one panel shows at a time.

## Props

`items` (array of `{key, title, content, isDisabled}`), `defaultSelectedKey` / `selectedKey`, `onSelectionChange(key)`, `aria-label`.

## Behavior

Left and right arrow keys move between tabs and wrap; the selected tab is the only tab stop. The selected tab gets a 2px underline in `content-heading`, so state does not rely on color.

## Do

- Keep titles to one or two words.
- Keep three to six tabs.

## Don't

- Don't use tabs for steps in a flow; use a step list.
