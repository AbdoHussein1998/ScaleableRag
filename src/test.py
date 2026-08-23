#!/usr/bin/env python3
"""
Concurrent Load Tester for RAG API Endpoint
Sends 10,000 concurrent requests to http://localhost:80/api/v1/client/
Works in both regular Python scripts and Jupyter notebooks.
"""

import asyncio
import aiohttp
import time
import sys
import threading
from collections import Counter
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────
URL = "http://localhost:80/api/v1/client/"
TOTAL_REQUESTS = 10_000
CONCURRENCY_LIMIT = 1000          # Max simultaneous connections
TIMEOUT_SECONDS = 500             # Per-request timeout
REQUEST_METHOD = "POST"           # Change to POST/PUT if needed
REQUEST_PAYLOAD = None           # Set to dict for POST/PUT body
REQUEST_HEADERS = {
    "User-Agent": "RAG-LoadTester/1.0",
    "Accept": "application/json",
}

# ── Globals ────────────────────────────────────────────────────
results = {
    "success": 0,
    "failed": 0,
    "timeouts": 0,
    "errors": 0,
}
status_codes = Counter()
response_times = []
error_details = []
results_lock = threading.Lock()


def record_success(status, elapsed):
    with results_lock:
        results["success"] += 1
        status_codes[status] += 1
        response_times.append(elapsed)


def record_failed(status, elapsed, req_id):
    with results_lock:
        results["failed"] += 1
        status_codes[status] += 1
        response_times.append(elapsed)
        error_details.append(f"[{req_id}] HTTP {status}")


def record_timeout(req_id):
    with results_lock:
        results["timeouts"] += 1
        error_details.append(f"[{req_id}] TIMEOUT after {TIMEOUT_SECONDS}s")


def record_error(e, req_id):
    with results_lock:
        results["errors"] += 1
        error_details.append(f"[{req_id}] ERROR: {type(e).__name__}: {e}")


async def fetch(session: aiohttp.ClientSession, sem: asyncio.Semaphore, req_id: int):
    """Send a single request and record metrics."""
    async with sem:
        start = time.perf_counter()
        try:
            async with session.request(
                method=REQUEST_METHOD,
                url=URL,
                headers=REQUEST_HEADERS,
                json=REQUEST_PAYLOAD,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
            ) as response:
                await response.read()  # Ensure full response is received
                elapsed = time.perf_counter() - start

                if 200 <= response.status < 300:
                    record_success(response.status, elapsed)
                else:
                    record_failed(response.status, elapsed, req_id)

        except asyncio.TimeoutError:
            record_timeout(req_id)
        except aiohttp.ClientError as e:
            record_error(e, req_id)
        except Exception as e:
            record_error(e, req_id)


async def run_load_test():
    """Orchestrate the concurrent load test."""
    print("=" * 60)
    print("   RAG API Load Tester")
    print("=" * 60)
    print(f"Target URL:     {URL}")
    print(f"Total Requests: {TOTAL_REQUESTS:,}")
    print(f"Concurrency:    {CONCURRENCY_LIMIT}")
    print(f"Method:         {REQUEST_METHOD}")
    print(f"Timeout:        {TIMEOUT_SECONDS}s")
    print("-" * 60)
    print(f"Started at:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()

    # TCP connector tuned for high concurrency
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY_LIMIT,
        limit_per_host=CONCURRENCY_LIMIT,
        enable_cleanup_closed=True,
        force_close=True,
    )

    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            fetch(session, sem, i + 1)
            for i in range(TOTAL_REQUESTS)
        ]

        # Progress reporting
        done = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done += 1
            if done % 1000 == 0 or done == TOTAL_REQUESTS:
                print(f"  Progress: {done:,} / {TOTAL_REQUESTS:,} requests completed")


def print_report(duration: float):
    """Print formatted test results."""
    print()
    print("=" * 60)
    print("   TEST RESULTS")
    print("=" * 60)
    print(f"Duration:        {duration:.2f} seconds")
    print(f"Total Requests:  {TOTAL_REQUESTS:,}")
    print(f"Successful:      {results['success']:,}  ({results['success']/TOTAL_REQUESTS*100:.1f}%)")
    print(f"Failed (HTTP):   {results['failed']:,}  ({results['failed']/TOTAL_REQUESTS*100:.1f}%)")
    print(f"Timeouts:        {results['timeouts']:,}  ({results['timeouts']/TOTAL_REQUESTS*100:.1f}%)")
    print(f"Errors:          {results['errors']:,}  ({results['errors']/TOTAL_REQUESTS*100:.1f}%)")
    print()

    if response_times:
        sorted_times = sorted(response_times)
        print("─ Response Times ─")
        print(f"  Min:    {min(response_times)*1000:.2f} ms")
        print(f"  Max:    {max(response_times)*1000:.2f} ms")
        print(f"  Mean:   {sum(response_times)/len(response_times)*1000:.2f} ms")
        print(f"  Median: {sorted_times[len(sorted_times)//2]*1000:.2f} ms")
        print(f"  p95:    {sorted_times[int(len(sorted_times)*0.95)]*1000:.2f} ms")
        print(f"  p99:    {sorted_times[int(len(sorted_times)*0.99)]*1000:.2f} ms")
        print()

    if status_codes:
        print("─ HTTP Status Codes ─")
        for code, count in sorted(status_codes.items()):
            print(f"  {code}: {count:,}")
        print()

    print(f"Throughput:      {TOTAL_REQUESTS/duration:.1f} req/sec")
    print(f"Successful/sec:  {results['success']/duration:.1f} req/sec")
    print("=" * 60)

    if error_details:
        print()
        print("─ First 20 Errors ─")
        for err in error_details[:20]:
            print(f"  {err}")
        if len(error_details) > 20:
            print(f"  ... and {len(error_details) - 20} more")


def run_in_notebook():
    """Run the async code in a Jupyter/IPython environment."""
    import nest_asyncio
    nest_asyncio.apply()

    start_time = time.perf_counter()

    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_load_test())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")

    duration = time.perf_counter() - start_time
    print_report(duration)


def run_in_script():
    """Run the async code in a regular Python script."""
    start_time = time.perf_counter()

    try:
        asyncio.run(run_load_test())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")

    duration = time.perf_counter() - start_time
    print_report(duration)


def main():
    if sys.version_info < (3, 7):
        print("ERROR: Python 3.7+ required.")
        sys.exit(1)

    # Detect if running in Jupyter/IPython
    try:
        from IPython import get_ipython
        if get_ipython() is not None:
            print("Detected Jupyter/IPython environment. Using nest_asyncio.\n")
            run_in_notebook()
            return
    except ImportError:
        pass

    # Regular Python script
    run_in_script()


if __name__ == "__main__":
    main()