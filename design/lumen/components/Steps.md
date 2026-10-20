A progress indicator of dots on a track for a multi-step flow.

Use `Steps` to show where someone is in a short, ordered flow (checkout, setup, a wizard). It indicates progress; your page supplies the content for each step.

## Props

`items` — array of `{title, description}`. `currentStep` — zero-based index. `orientation` — `horizontal` (default) or `vertical`. `onStepPress(index)` makes completed steps buttons so people can go back. `aria-label`.

## Behavior

An ordered list; the current step has `aria-current="step"`. Each step also carries hidden text ("completed", "current step", "not started") so state does not depend on color. Markers are 16px: completed steps are a filled accent dot with a check, the current step an accent ring with a dot, upcoming steps an empty gray ring. The track is 2px.

## Do

- Use three to six steps and keep titles to one or two words.

## Don't

- Don't make upcoming steps clickable; people should not skip ahead.
