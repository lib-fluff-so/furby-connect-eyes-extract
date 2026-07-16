import time
from contextlib import contextmanager
from collections import defaultdict

timings = defaultdict(float)
t_start = 0

def set_start_time():
    global t_start
    t_start = time.perf_counter()

@contextmanager
def timed(key):
    t0 = time.perf_counter()
    yield
    timings[key] += time.perf_counter() - t0

def print_time_status():
    t_total = time.perf_counter() - t_start
    # pretty table
    print("=" * 59)
    for key, t in timings.items():
        right_side = f"{t:.4f}s ({t / t_total * 100:.1f}%)"
        print(f"| {key:<36} | {right_side:>16} |")
    print("=" * 59)