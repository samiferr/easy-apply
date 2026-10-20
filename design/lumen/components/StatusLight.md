A colored dot with a text label for status.

Use `StatusLight` to show the state of an object in a list or table. The label always names the status; the dot is reinforcement.

## Props

`variant` — `neutral`, `informative`, `positive`, `notice`, `negative`, `purple`, `cyan`. `children` — the label.

## Do

- Use semantic variants for meaning (positive = done, negative = failed) and the hue variants (`purple`, `cyan`) for categories with no judgment.

## Don't

- Don't use a status light without its label: green versus red cannot be told apart by hue alone.
