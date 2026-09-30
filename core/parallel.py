"""Run independent AI calls side by side.

The AI calls are network waits, so a thread per call is what makes them overlap;
the callables must not touch the database or other per-thread state.
"""

from concurrent.futures import ThreadPoolExecutor

from django.conf import settings


def run_parallel(jobs: dict) -> dict:
    """Run every zero-argument callable in `jobs` concurrently and return
    `{name: result}` in the same order.

    Every call is allowed to finish, then the first failure (in `jobs` order) is
    raised, so a retry of the caller starts from a settled state.
    """
    if not jobs:
        return {}
    workers = max(1, min(len(jobs), settings.AI_MAX_PARALLEL))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {name: pool.submit(job) for name, job in jobs.items()}
    return {name: future.result() for name, future in futures.items()}
