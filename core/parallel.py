"""Run independent AI calls side by side.

The AI calls are network waits, so a thread per call is what makes them overlap;
the callables must not touch the database or other per-thread state.
"""

from concurrent.futures import ThreadPoolExecutor

from django.conf import settings


def run_parallel(jobs: dict, *, keep_partial: bool = False):
    """Run every zero-argument callable in `jobs` concurrently.

    Every call is allowed to finish. By default the first failure (in `jobs`
    order) is raised and the result is `{name: result}`. With `keep_partial` the
    return value is `(results, errors)` instead — the answers that succeeded and
    `{name: exception}` for those that did not — and an exception is raised only
    when nothing succeeded (the first one, in `jobs` order).
    """
    if not jobs:
        return ({}, {}) if keep_partial else {}
    workers = max(1, min(len(jobs), settings.AI_MAX_PARALLEL))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {name: pool.submit(job) for name, job in jobs.items()}
    if not keep_partial:
        return {name: future.result() for name, future in futures.items()}
    results, errors = {}, {}
    for name, future in futures.items():
        try:
            results[name] = future.result()
        except Exception as exc:
            errors[name] = exc
    if not results:
        raise next(iter(errors.values()))
    return results, errors
