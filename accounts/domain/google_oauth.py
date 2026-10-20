"""Google sign-in: the OpenID Connect authorization-code flow, with PKCE.

No library: the flow is two HTTP calls and a handful of checks, and `requests`
is already a dependency.

1. `authorization_url` sends the browser to Google with a random `state`
   (CSRF), `nonce` (replay) and PKCE `code_challenge`, all kept in the session.
2. Google redirects back with a `code`; `exchange_code` checks `state`, trades
   the code (plus the PKCE verifier and the client secret) for tokens at
   Google's token endpoint, and validates the ID token's claims.

The ID token arrives over a direct TLS call to Google's token endpoint, which
OpenID Connect Core §3.1.3.7 accepts in place of verifying its signature; the
issuer, audience, expiry and nonce are still checked here.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils.translation import gettext as _

from core.exceptions import ServiceError

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
SESSION_KEY = "google_oauth"
#: How long a sign-in attempt may sit at Google's consent screen.
FLOW_TTL = 600


class GoogleAuthError(ServiceError):
    """The sign-in could not be completed; the message is safe to show."""


def is_configured() -> bool:
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def authorization_url(request, redirect_uri: str, next_url: str = "") -> str:
    """Start a sign-in: remember the flow's secrets and return Google's URL."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    request.session[SESSION_KEY] = {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "next": next_url,
        "started": int(time.time()),
    }
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _decode_payload(id_token: str) -> dict:
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise GoogleAuthError(_("Google sent an unreadable sign-in token.")) from exc


def exchange_code(request, code: str, state: str, redirect_uri: str) -> tuple[dict, str]:
    """Finish a sign-in. Returns the validated ID-token claims and the `next` URL.

    The flow's session entry is consumed whatever happens, so a code or state
    can never be replayed.
    """
    flow = request.session.pop(SESSION_KEY, None)
    if not flow or not state or not secrets.compare_digest(flow["state"], state):
        raise GoogleAuthError(_("That sign-in link has expired. Please try again."))
    if time.time() - flow["started"] > FLOW_TTL:
        raise GoogleAuthError(_("That sign-in took too long. Please try again."))
    if not code:
        raise GoogleAuthError(_("Google did not complete the sign-in."))

    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": flow["verifier"],
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise GoogleAuthError(_("Google could not be reached. Please try again.")) from exc
    if response.status_code != 200:
        raise GoogleAuthError(_("Google refused the sign-in. Please try again."))
    id_token = response.json().get("id_token")
    if not id_token:
        raise GoogleAuthError(_("Google did not return an identity."))

    claims = _decode_payload(id_token)
    if claims.get("iss") not in ISSUERS:
        raise GoogleAuthError(_("That sign-in did not come from Google."))
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if settings.GOOGLE_OAUTH_CLIENT_ID not in audiences:
        raise GoogleAuthError(_("That sign-in was meant for another application."))
    if int(claims.get("exp", 0)) < time.time():
        raise GoogleAuthError(_("That sign-in has expired. Please try again."))
    if not secrets.compare_digest(str(claims.get("nonce", "")), flow["nonce"]):
        raise GoogleAuthError(_("That sign-in could not be verified. Please try again."))
    if not claims.get("sub"):
        raise GoogleAuthError(_("Google did not return an account id."))
    return claims, flow.get("next", "")
