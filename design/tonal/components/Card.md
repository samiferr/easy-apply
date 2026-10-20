A rounded container that groups related content and actions on one subject.

**You provide:** optional `title`, `subtitle`, `children` (supporting text), `actions` (buttons, usually `text`), `variant` (`elevated`, `filled`, `outlined`), `selected`, `width`; give it `onClick` to make the whole card a button.

- Pick one variant per surface: `outlined` on `surface`, `filled` for emphasis, `elevated` when cards sit on a patterned or media ground.
- 12px corners (`radius-md`), 16px padding (`space-4`).
- Keep one primary action per card; don't nest cards.
