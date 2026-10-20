A message with a simple illustration for when there is nothing to show.

Use `EmptyState` when a list, table or page has no content, either because nothing exists yet or because a search or filter matched nothing. Say what happened and offer one next step.

## Props

`title` (required), `description`, `illustration` — `empty` (default), `search`, `null` for none, or your own node. `headingLevel` (default 2). `children` — actions, usually one `Button`.

## Do

- First-run: tell people what the space is for and how to start. No results: say what was searched and how to widen it.
- Keep the title under eight words.

## Don't

- Don't use it for errors; use `InlineAlert`.
