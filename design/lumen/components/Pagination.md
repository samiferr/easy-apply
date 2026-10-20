Previous, next and numbered page buttons for paged content.

Use `Pagination` to move through a long set that is split into pages, usually under a `Table` or `List`.

## Props

`pageCount` (required), `page` / `defaultPage`, `onChange(page)`, `siblingCount` (pages shown either side of the current one, default 1), `aria-label` (default "Pagination").

## Behavior

The current page is `aria-current="page"` and drawn as a filled pill; Previous and Next are disabled at the ends. Ellipses are decorative and hidden from assistive technology; each button is labeled "Page N".

## Do

- Show the total elsewhere ("Showing 21–40 of 312") so people know where they are.
- Keep the control in the same place on every page.

## Don't

- Don't use pagination for fewer than three pages.
