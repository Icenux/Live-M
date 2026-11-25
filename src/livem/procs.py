"""Opt-in, low-overhead process sampler.

Live-M normally never looks at processes (that is what keeps it light). This
module is only used while the user has the process panel switched on (`p`).

To keep the cost low it reads only ``/proc/<pid>/stat`` — one small file per
process, no psutil objects — and it is meant to be polled slowly (see
``PROC_TTL`` in app.py). Measured on ~300 processes: ~6 ms CPU per sample,
i.e. about 0.2 % of one core at a 3 s cadence.
"""

import os
import time
from typing import Dict, List, NamedTuple, Optional, Tuple

CLK_TCK = os.sysconf('SC_CLK_TCK')
PAGE_SIZE = os.sysconf('SC_PAGE_SIZE')


class ProcInfo(NamedTuple):
    pid: int
    name: str
    cpu: float   # percent of ONE core (100 = one core fully busy), like htop
    rss: int     # resident set size in bytes


def parse_stat(raw: bytes) -> Optional[Tuple[str, int, int]]:
    """Parse the content of /proc/<pid>/stat -> (comm, cpu_ticks, rss_bytes).

    The command name sits in parentheses and may itself contain spaces and
    parentheses, so split on the *first* '(' and the *last* ')'.
    """
    try:
        lpar = raw.index(b'(')
        rpar = raw.rindex(b')')
        name = raw[lpar + 1:rpar].decode('utf-8', 'replace')
        rest = raw[rpar + 2:].split()
        # rest[0] is field 3 (state); utime=14, stime=15, rss=24 (1-based)
        ticks = int(rest[11]) + int(rest[12])
        rss = int(rest[21]) * PAGE_SIZE
    except (ValueError, IndexError):
        return None
    return name, ticks, max(rss, 0)


def read_all() -> Dict[int, Tuple[str, int, int]]:
    """Read every process once: {pid: (comm, cpu_ticks, rss_bytes)}."""
    out: Dict[int, Tuple[str, int, int]] = {}
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            with open(f'/proc/{entry}/stat', 'rb') as fh:
                parsed = parse_stat(fh.read())
        except OSError:
            continue  # process exited meanwhile / hidden by hidepid
        if parsed is not None:
            out[int(entry)] = parsed
    return out


def compute(prev: Dict[int, Tuple[str, int, int]], cur: Dict[int, Tuple[str, int, int]],
            dt: float) -> List[ProcInfo]:
    """Turn two snapshots `dt` seconds apart into per-process CPU/RSS rows.

    Processes that did not exist in `prev` get no CPU figure (0.0) — a PID may
    also have been reused, so a tick counter that went backwards counts as new.
    """
    rows: List[ProcInfo] = []
    for pid, (name, ticks, rss) in cur.items():
        old = prev.get(pid)
        cpu = 0.0
        if old is not None and dt > 0 and ticks >= old[1]:
            cpu = (ticks - old[1]) / CLK_TCK / dt * 100.0
        rows.append(ProcInfo(pid, name, cpu, rss))
    return rows


def top(rows: List[ProcInfo], n: int, key: str) -> List[ProcInfo]:
    """Top `n` rows by 'cpu' or 'rss', skipping zero values."""
    ranked = sorted((r for r in rows if getattr(r, key) > 0),
                    key=lambda r: getattr(r, key), reverse=True)
    return ranked[:n]


class ProcSampler:
    """Holds the previous snapshot and the latest top lists.

    `poll(now)` is cheap to call every frame: it only does real work when the
    sample is due. Until two snapshots exist `ready` is False.
    """

    FIRST_DELAY = 1.0   # gap between the priming snapshot and the first result

    def __init__(self, ttl: float, count: int = 5) -> None:
        self.ttl = ttl
        self.count = count
        self.ready = False
        self.top_cpu: List[ProcInfo] = []
        self.top_mem: List[ProcInfo] = []
        self._prev: Optional[Dict[int, Tuple[str, int, int]]] = None
        self._prev_t = 0.0

    def poll(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        if self._prev is None:
            self._prev, self._prev_t = read_all(), now
            return
        due = self.ttl if self.ready else self.FIRST_DELAY
        if now - self._prev_t < due:
            return
        cur = read_all()
        rows = compute(self._prev, cur, now - self._prev_t)
        self.top_cpu = top(rows, self.count, 'cpu')
        self.top_mem = top(rows, self.count, 'rss')
        self._prev, self._prev_t = cur, now
        self.ready = True
