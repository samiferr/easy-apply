A screen header with a leading navigation icon, a title and up to three action icons.

**You provide:** `title`, `variant` (`small`, `center`, `medium`, `large`), `leading` icon name (menu or arrow_back), `actions` (icon names or `{icon, label}`), and `scrolled` when content scrolls beneath it (the bar moves to `surface-container`).

- Titles are sentence case and truncate to one line in `small`/`center`.
- Medium and large collapse to small on scroll; manage that in your layout.
- Action icons need labels for assistive tech.
