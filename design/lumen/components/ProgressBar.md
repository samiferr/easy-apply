A thin bar showing determinate or indeterminate progress.

Use `ProgressBar` when work takes more than a second or two and you know (or don't know) how far along it is.

## Props

`label` (required), `value` (0 to 100; omit for indeterminate).

## Do

- Show the number whenever you know it; the bar's fill is a graphic, the number is the information.
- Use indeterminate only when progress is unknowable.

## Don't

- Don't animate when the person prefers reduced motion; the stylesheet already stops it.
