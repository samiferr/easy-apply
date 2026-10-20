A vertical list of events in time order.

Use `Timeline` to show what happened, and when, to one object: order history, an audit trail, release notes.

## Props

`items` — newest first, each `{title, time, dateTime, description, variant}`. `variant` — `neutral` (default), `informative`, `positive`, `notice`, `negative` colors the dot. `aria-label`.

## Do

- Put the newest event first unless the content is a plan; then use time order and say so.
- Write each title as an event ("Payment failed"), so the dot color is not the only cue.

## Don't

- Don't use it for steps the person must complete; use `Steps`.
