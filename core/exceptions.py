"""How a use case says "not now" without knowing anything about HTTP.

Each app's `services.py` raises one of these instead of returning a status or
reaching for `django.contrib.messages`. The view decides what the visitor sees
(a flash message, a form error, a redirect); `str(error)` is always a sentence
that is safe to show them.
"""


class ServiceError(Exception):
    """A use case could not proceed. `str(error)` is written for the user."""


class Blocked(ServiceError):
    """The plan, the monthly allowance or the AI kill switch does not allow it right now."""


class PreconditionFailed(ServiceError):
    """What the use case works on is not yet in the state it needs — for example
    a job post that has not been analysed."""


class Refused(ServiceError):
    """A business rule forbids it — for example suspending your own account or
    deleting your only profile."""
