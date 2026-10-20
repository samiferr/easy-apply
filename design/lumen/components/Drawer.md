A panel that slides in from the edge over a dimmed page.

Use `Drawer` for secondary tasks that should not leave the page: filters, details, settings. It is modal: the page behind is dimmed and inert until the drawer closes.

## Props

`isOpen`, `onClose` (required; called by the close button, the scrim and Escape), `title` (required), `side` — `right` (default) or `left`, `width` (default 360), `footer` (actions, right-aligned), `children`, `isContained` (position inside the nearest positioned parent instead of the whole window; use for embedding and previews).

## Behavior

`role="dialog"` with `aria-modal`; focus moves to the panel on open, is trapped while open, and returns to the previous element on close. Motion is skipped when the person prefers reduced motion.

## Do

- Put the primary action in the footer and make sure it can be reached without scrolling.
- Keep the content to one task.

## Don't

- Don't open a drawer from another drawer.
- Don't use it for a confirmation; use a dialog.
