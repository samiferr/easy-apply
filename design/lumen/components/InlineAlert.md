An in-page message with a colored border, icon and title.

Use `InlineAlert` for a message that belongs to one part of the page and should stay until it is dealt with.

## Props

`variant` — `neutral`, `informative`, `positive`, `notice`, `negative`. `title` — bold first line. `children` — the message.

## Behavior

`negative` uses `role="alert"`; the others use `role="status"`. The border, icon and a soft tinted background (`neutral-subtle`, `informative-subtle`, `positive-subtle`, `notice-subtle`, `negative-subtle`) show the variant; the title and icon carry it too, so color is never the only cue. Text stays `content-heading` and `content-default` on every tint.

## Do

- Write the title as a short statement and the body as what to do next.
- Place it next to the thing it is about.

## Don't

- Don't stack more than two alerts; combine or prioritize.
