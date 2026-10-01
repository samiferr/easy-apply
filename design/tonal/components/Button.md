A pill-shaped action trigger in five emphasis levels: filled, tonal, elevated, outlined and text.

**You provide:** `children` (the label, sentence case, one to three words), optional `icon` (leading, 18px), `variant`, `disabled` and `onClick`.

- Use **one** filled button per view for the primary action; pair it with a text or outlined button for the alternative.
- Use `tonal` for important but secondary actions, `elevated` only when the button sits on a patterned ground, `text` for low-emphasis and dialog actions.
- Height is 40px; wrap it in a 48px hit area on touch layouts.
- Don't mix two filled buttons side by side; don't use icon-only labels — use `IconButton`.
