A vertical list of tappable rows with a headline, optional supporting text, a leading icon or avatar and trailing meta.

**You provide:** `items` (`[{headline, supporting?, lines?, icon?, avatar?, trailing?, selected?, onClick?}]`) and `dividers` to draw hairlines between rows.

- Rows are 56px (one line), 72px (two) or 88px (three); the headline is `body-large`, supporting text `body-medium` in `on-surface-variant`.
- `selected` fills with `secondary-container`.
- Use `avatar` (one or two letters) for people; use `icon` for navigation and settings.
