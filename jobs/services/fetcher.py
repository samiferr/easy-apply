"""Fetches a job posting URL and extracts its readable text.

Includes basic SSRF protections since this fetches arbitrary,
user-supplied URLs from the server: only http(s) is allowed, every
resolved IP (including on each redirect hop) is checked against
private/loopback/link-local/reserved ranges, and the response body is
capped in size.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings

USER_AGENT = (
    "Mozilla/5.0 (compatible; EasyApplyBot/1.0; "
    "+https://github.com/samiferr/easy-apply) job-post-analyzer"
)
MAX_REDIRECTS = 5
_NOISE_TAGS = ["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]


class JobFetchError(Exception):
    """Raised for any user-facing failure while fetching/reading a job post URL."""


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise JobFetchError("Please provide a valid http:// or https:// URL.")
    hostname = parsed.hostname
    if not hostname:
        raise JobFetchError("That doesn't look like a valid URL.")

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise JobFetchError(f"Couldn't resolve the host “{hostname}”.")

    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise JobFetchError(
                "That URL points to a location we're not allowed to fetch."
            )
    return url


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def fetch_job_post_text(url: str) -> str:
    """Fetch `url` and return its readable, whitespace-collapsed text.

    Raises JobFetchError with a message safe to show to the end user.
    """
    max_bytes = settings.JOB_FETCH_MAX_BYTES
    timeout = settings.JOB_FETCH_TIMEOUT
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}

    next_url = _validate_public_url(url)
    for _ in range(MAX_REDIRECTS):
        try:
            response = requests.get(
                next_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.exceptions.Timeout:
            raise JobFetchError("The job posting site took too long to respond.")
        except requests.exceptions.SSLError:
            raise JobFetchError("Couldn't establish a secure connection to that site.")
        except requests.exceptions.ConnectionError:
            raise JobFetchError("Couldn't connect to that site. Check the URL and try again.")
        except requests.exceptions.RequestException:
            raise JobFetchError("Something went wrong fetching that URL.")

        if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise JobFetchError("That URL redirected without a destination.")
            next_url = _validate_public_url(
                requests.compat.urljoin(next_url, location)
            )
            continue

        if response.status_code == 404:
            response.close()
            raise JobFetchError("That job posting couldn't be found (404).")
        if response.status_code in (401, 403):
            response.close()
            raise JobFetchError(
                "That site blocked automated access to this posting (try pasting the "
                "text instead)."
            )
        if not response.ok:
            response.close()
            raise JobFetchError(f"That site returned an error (HTTP {response.status_code}).")

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            response.close()
            raise JobFetchError("That URL doesn't look like a web page we can read.")

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192, decode_unicode=False):
            total += len(chunk)
            if total > max_bytes:
                break
            chunks.append(chunk)
        response.close()
        html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")

        text = _extract_text(html)
        if len(text) < 100:
            raise JobFetchError(
                "We couldn't read enough content from that page — it may require "
                "JavaScript to load. Try pasting the job description text instead."
            )
        return text

    raise JobFetchError("That URL redirected too many times.")
