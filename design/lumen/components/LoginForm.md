A complete sign-in form with validation, password reveal and optional SSO.

Use `LoginForm` for the sign-in page of an app. It handles layout, labels, validation messages, focus and the loading state; you handle the request.

## Props

`onSubmit({email, password, remember})` — called only when both fields are filled and the email looks complete. `errorMessage` / `errorTitle` — a server error shown as a `negative` `InlineAlert` above the fields. `isLoading` — disables the form and changes the button to "Signing in…". `title` (default "Sign in"), `description`, `submitLabel`, `logo` (a node), `defaultEmail`, `forgotPasswordHref`, `signUpHref` (adds "Create an account"), `onSSO` (adds the "or" divider and a single sign-on button), `ssoLabel`.

## Behavior

Validation runs on submit, not while typing; errors name what to fix, and focus moves to the first invalid field. Fields use `autocomplete="username"` and `"current-password"` so password managers work. "Show" and "Hide" reveal the password; the field is never logged or stored by the component.

## Do

- Keep server errors vague about which field was wrong ("email or password is incorrect").
- Show one `accent` button per screen; the SSO button is `secondary` outline.

## Don't

- Don't remove the visible labels or replace them with placeholders.
- Don't clear the email after a failed attempt.
