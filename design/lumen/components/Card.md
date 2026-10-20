A bordered container that groups an image, text and actions about one thing.

Use `Card` to present one object (a file, project or person) as a self-contained summary. A card has an optional preview, a title, a short description and a footer.

## Props

`title`, `description`, `preview` (a node filling the top, or the left in `horizontal`), `footer` (badges, buttons), `children` (extra content), `orientation` (`vertical` default, `horizontal`), `width`, `headingLevel` (1 to 6, default 3). `onPress` makes the whole card one button: it gets hover, a focus ring and Enter/Space; `isSelected` then makes it a toggle with a 2px accent border and a check icon.

## Do

- Keep the title to one line and the description to two.
- Put actions in `footer` only on cards without `onPress`.
- Use the same card width across a grid; 16px (`spacing-300`) gaps.

## Don't

- Don't nest buttons or links inside an `onPress` card.
- Don't use a card for a single value; use plain text.
