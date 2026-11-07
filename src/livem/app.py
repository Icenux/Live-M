import argparse
import curses
import datetime
import os
import socket
import subprocess
import time

import psutil

from livem import __version__ as VERSION

INTERVAL_MIN = 0.5
INTERVAL_MAX = 10.0
INTERVAL_STEP = 0.5

PARTITION_TTL = 60.0   # re-scan mountpoints at most once per minute
SENSOR_TTL    =  5.0   # re-read sensors every 5 s (they change slowly)

# curses color pair IDs
PAIR_HEADER  = 1
PAIR_GREEN   = 2
PAIR_YELLOW  = 3
PAIR_RED     = 4
PAIR_SECTION = 5   # blue panel headings

_SKIP_FSTYPES        = {'tmpfs', 'devtmpfs', 'squashfs', 'overlay'}
_SKIP_MOUNT_PREFIXES = ('/snap/', '/var/snap/', '/run/')
_SKIP_MOUNT_EXACT    = {'/boot', '/boot/efi'}
_SKIP_SENSOR_CHIPS   = {'iwlwifi_1', 'pch_skylake'}


def _find_wifi_iface(counters: dict) -> str:
    """Return first wl* or ww* interface name found in counters, or ''."""
    for prefix in ('wl', 'ww'):
        for name in counters:
            if name.startswith(prefix):
                return name
    return ''


def _fmt_speed(bps: float) -> str:
    """Format bytes-per-second as human-readable speed string."""
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1_048_576:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / 1_048_576:.1f} MB/s"


def uptime_str() -> str:
    """Return human-readable uptime from /proc/uptime."""
    with open("/proc/uptime") as f:
        secs = float(f.read().split()[0])
    h, rem = divmod(int(secs), 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def cpu_color_pair(pct: float) -> int:
    """Map a 0-100 percentage to a curses color pair ID."""
    if pct >= 80:
        return PAIR_RED
    if pct >= 50:
        return PAIR_YELLOW
    return PAIR_GREEN


def temp_color_pair(temp: float) -> int:
    """Map a temperature in °C to a curses color pair ID."""
    if temp > 80:
        return PAIR_RED
    if temp >= 60:
        return PAIR_YELLOW
    return PAIR_GREEN


def _section(stdscr, row: int, title: str, no_color: bool) -> None:
    """Write a bold blue section heading at (row, 0)."""
    attr = (curses.color_pair(PAIR_SECTION) | curses.A_BOLD) if not no_color else curses.A_BOLD
    try:
        stdscr.addstr(row, 0, title, attr)
    except curses.error:
        pass


def draw_header(stdscr, hostname: str, interval: float,
                wifi_str: str, no_color: bool, in_tmux: bool = False) -> int:
    """Draw header line(s) with WiFi speed. Returns number of rows consumed (1 or 2)."""
    _, max_x = stdscr.getmaxyx()
    uptime = uptime_str()
    now    = datetime.datetime.now().strftime("%H:%M:%S")
    tmux_tag = "  [tmux]" if in_tmux else ""
    base   = (
        f"Live-M  hostname: {hostname}   uptime: {uptime}"
        f"   {now}   refresh: {interval:.1f}s{tmux_tag}"
    )
    full = f"{base}   {wifi_str}"
    attr = (curses.color_pair(PAIR_HEADER) | curses.A_BOLD) if not no_color else curses.A_BOLD

    if len(full) < max_x:
        try:
            stdscr.addstr(0, 0, full, attr)
        except curses.error:
            pass
        return 1
    else:
        try:
            stdscr.addstr(0, 0, base, attr)
        except curses.error:
            pass
        try:
            stdscr.addstr(1, 0, f"  {wifi_str}", attr)
        except curses.error:
            pass
        return 2


def draw_cpu(stdscr, row: int, no_color: bool, compact: bool = False) -> int:
    """Draw CPU panel. compact=True shows only the Avg line without per-core bars."""
    max_y, max_x = stdscr.getmaxyx()
    per_core = psutil.cpu_percent(percpu=True, interval=None)
    n_cores  = len(per_core)
    avg      = sum(per_core) / n_cores if n_cores else 0.0
    la1, la5, la15 = os.getloadavg()

    _section(stdscr, row, "CPU", no_color)
    row += 1

    if not compact:
        prefix_w = 6   # "  NN ["
        suffix_w = 8   # "  XXXX%]"
        gap      = 2
        # Single-column layout on narrow terminals (< 60 cols)
        two_col_bar = (max_x - gap - 2 * (prefix_w + suffix_w)) // 2
        one_col_bar = max_x - prefix_w - suffix_w
        two_col = (two_col_bar >= 4) and (max_x >= 60)
        bar_w   = two_col_bar if two_col else max(1, one_col_bar)

        def render_core(r: int, c: int, idx: int, pct: float) -> None:
            filled = int(round(pct / 100.0 * bar_w))
            bar   = "|" * filled + " " * (bar_w - filled)
            label = f"  {idx:<2} ["
            tail  = f"  {pct:4.0f}%]"
            try:
                stdscr.addstr(r, c, label)
                if not no_color:
                    stdscr.attron(curses.color_pair(cpu_color_pair(pct)))
                stdscr.addstr(r, c + len(label), bar)
                if not no_color:
                    stdscr.attroff(curses.color_pair(cpu_color_pair(pct)))
                stdscr.addstr(r, c + len(label) + bar_w, tail)
            except curses.error:
                pass

        if two_col:
            col_w = prefix_w + bar_w + suffix_w + gap
            for i in range(0, n_cores, 2):
                if row >= max_y - 1:
                    break
                render_core(row, 0, i, per_core[i])
                if i + 1 < n_cores:
                    render_core(row, col_w, i + 1, per_core[i + 1])
                row += 1
        else:
            for i, pct in enumerate(per_core):
                if row >= max_y - 1:
                    break
                render_core(row, 0, i, pct)
                row += 1

    try:
        stdscr.addstr(row, 0, f"  Avg {avg:4.0f}%   Load: {la1:.2f}  {la5:.2f}  {la15:.2f}")
    except curses.error:
        pass
    row += 1
    return row


def draw_memory(stdscr, row: int, no_color: bool) -> int:
    """Draw Memory panel starting at `row`. Returns next free row."""
    max_y, max_x = stdscr.getmaxyx()
    GiB  = 1024 ** 3
    vm   = psutil.virtual_memory()
    swap = psutil.swap_memory()

    bar_w = max(4, max_x - 30)

    _section(stdscr, row, "Memory", no_color)
    row += 1

    def render_bar(r: int, label: str, used: float, total: float, pct: float) -> None:
        filled  = int(round(pct / 100.0 * bar_w))
        bar     = "|" * filled + " " * (bar_w - filled)
        used_g  = used  / GiB
        total_g = total / GiB
        tail    = f"  {used_g:.1f}/{total_g:.1f} GiB  {pct:3.0f}%]"
        try:
            stdscr.addstr(r, 0, f"  {label}  [")
            if not no_color:
                stdscr.attron(curses.color_pair(cpu_color_pair(pct)))
            stdscr.addstr(r, 2 + len(label) + 3, bar)
            if not no_color:
                stdscr.attroff(curses.color_pair(cpu_color_pair(pct)))
            stdscr.addstr(r, 2 + len(label) + 3 + bar_w, tail)
        except curses.error:
            pass

    render_bar(row, "RAM ", vm.used, vm.total, vm.percent)
    row += 1

    if row < max_y - 1:
        if swap.total == 0:
            try:
                stdscr.addstr(row, 0, "  SWAP [disabled]")
            except curses.error:
                pass
        else:
            render_bar(row, "SWAP", swap.used, swap.total, swap.percent)
        row += 1

    return row


def draw_disks(stdscr, row: int, no_color: bool, partitions: list,
               max_count: int = 0) -> int:
    """Draw Disks panel. max_count > 0 limits to highest-utilization disks."""
    max_y, max_x = stdscr.getmaxyx()
    GiB     = 1024 ** 3
    MOUNT_W = 12
    bar_w   = max(4, max_x - MOUNT_W - 5 - 24)

    # Pre-fetch all usages so we can sort without double-calling disk_usage.
    entries = []
    for part in partitions:
        try:
            entries.append((part, psutil.disk_usage(part.mountpoint)))
        except (PermissionError, OSError):
            pass

    if max_count > 0 and len(entries) > max_count:
        entries.sort(key=lambda e: e[1].percent, reverse=True)
        entries = entries[:max_count]

    _section(stdscr, row, "Disks", no_color)
    row += 1

    for part, usage in entries:
        pct     = usage.percent
        filled  = int(round(pct / 100.0 * bar_w))
        bar     = "|" * filled + " " * (bar_w - filled)
        used_g  = usage.used  / GiB
        total_g = usage.total / GiB
        label   = part.mountpoint[:MOUNT_W].ljust(MOUNT_W)
        tail    = f"  {used_g:5.1f}/{total_g:5.1f} GiB  {pct:3.0f}%]"
        try:
            stdscr.addstr(row, 0, f"  {label}  [")
            if not no_color:
                stdscr.attron(curses.color_pair(cpu_color_pair(pct)))
            stdscr.addstr(row, 2 + MOUNT_W + 3, bar)
            if not no_color:
                stdscr.attroff(curses.color_pair(cpu_color_pair(pct)))
            stdscr.addstr(row, 2 + MOUNT_W + 3 + bar_w, tail)
        except curses.error:
            pass
        row += 1
        if row >= max_y - 1:
            break

    return row


def draw_temperatures(stdscr, row: int, no_color: bool, sensors: dict) -> int:
    """Draw Temperatures panel with bars from pre-fetched `sensors`. Returns next free row."""
    max_y, max_x = stdscr.getmaxyx()

    _section(stdscr, row, "Temperatures", no_color)
    row += 1

    if not sensors:
        try:
            stdscr.addstr(row, 0, "  N/A (no sensors detected)")
        except curses.error:
            pass
        return row + 1

    # Reference CPU bar width for scaling (must match draw_cpu constants)
    CPU_PREFIX_W = 6
    CPU_SUFFIX_W = 8
    CPU_GAP = 2
    cpu_two_col_bar = max(1, (max_x - CPU_GAP - 2 * (CPU_PREFIX_W + CPU_SUFFIX_W)) // 2)

    # Temp bar geometry — 60 % of CPU bar width
    TLABEL_W  = 7                           # "Core  0" .. "Core 10" padded to 7
    TPREFIX_W = 2 + TLABEL_W + 3           # "  " + label(7) + "  [" = 12
    TSUFFIX_W = 9                           # "  XXX °C]"
    TGAP      = 2

    temp_two_col_bar = max(4, int(cpu_two_col_bar * 0.6))
    temp_col_w = TPREFIX_W + temp_two_col_bar + TSUFFIX_W + TGAP
    temp_two_col = (temp_col_w * 2 - TGAP <= max_x) and (max_x >= 60)
    if temp_two_col:
        temp_bar_w = temp_two_col_bar
    else:
        cpu_one_col_bar = max(1, max_x - CPU_PREFIX_W - CPU_SUFFIX_W)
        temp_bar_w = max(4, int(cpu_one_col_bar * 0.6))

    def render_temp_bar(r: int, c: int, label: str, temp: float) -> None:
        t      = round(temp)
        filled = int(min(temp / 100.0, 1.0) * temp_bar_w)
        bar    = "|" * filled + " " * (temp_bar_w - filled)
        prefix = f"  {label:<{TLABEL_W}}  ["
        tail   = f"  {t:3d} °C]"
        try:
            stdscr.addstr(r, c, prefix)
            if not no_color:
                stdscr.attron(curses.color_pair(temp_color_pair(t)))
            stdscr.addstr(r, c + TPREFIX_W, bar)
            if not no_color:
                stdscr.attroff(curses.color_pair(temp_color_pair(t)))
            stdscr.addstr(r, c + TPREFIX_W + temp_bar_w, tail)
        except curses.error:
            pass

    for chip, entries in sensors.items():
        if chip in _SKIP_SENSOR_CHIPS:
            continue

        if chip == "coretemp":
            pkg_entries   = [e for e in entries if "Package" in e.label]
            core_entries  = [e for e in entries if e.label.startswith("Core")]
            other_entries = [e for e in entries
                             if "Package" not in e.label and not e.label.startswith("Core")]

            # Package — solo full-width row
            for entry in pkg_entries:
                if row >= max_y - 1:
                    return row
                t         = round(entry.current)
                pkg_bar_w = max(4, max_x - TPREFIX_W - TSUFFIX_W)
                filled    = int(min(entry.current / 100.0, 1.0) * pkg_bar_w)
                bar       = "|" * filled + " " * (pkg_bar_w - filled)
                tail      = f"  {t:3d} °C]"
                try:
                    stdscr.addstr(row, 0, f"  {'Package':<{TLABEL_W}}  [")
                    if not no_color:
                        stdscr.attron(curses.color_pair(temp_color_pair(t)))
                    stdscr.addstr(row, TPREFIX_W, bar)
                    if not no_color:
                        stdscr.attroff(curses.color_pair(temp_color_pair(t)))
                    stdscr.addstr(row, TPREFIX_W + pkg_bar_w, tail)
                except curses.error:
                    pass
                row += 1

            # Cores — 2-column layout
            if temp_two_col:
                for i in range(0, len(core_entries), 2):
                    if row >= max_y - 1:
                        return row
                    render_temp_bar(row, 0, core_entries[i].label, core_entries[i].current)
                    if i + 1 < len(core_entries):
                        render_temp_bar(row, temp_col_w,
                                        core_entries[i + 1].label, core_entries[i + 1].current)
                    row += 1
            else:
                for entry in core_entries:
                    if row >= max_y - 1:
                        return row
                    render_temp_bar(row, 0, entry.label, entry.current)
                    row += 1

            for entry in other_entries:
                if row >= max_y - 1:
                    return row
                render_temp_bar(row, 0, entry.label[:TLABEL_W], entry.current)
                row += 1
        else:
            # Non-coretemp chips — single column
            for idx, entry in enumerate(entries):
                if row >= max_y - 1:
                    return row
                label = entry.label if entry.label else f"temp{idx}"
                raw   = f"{chip} {label}"
                render_temp_bar(row, 0, raw[:TLABEL_W], entry.current)
                row += 1

    return row


def draw_footer(stdscr, interval: float) -> None:
    """Draw help bar pinned to the last terminal row."""
    max_y, max_x = stdscr.getmaxyx()
    footer = f"[q] quit  [+/-] interval  [current: {interval:.1f}s]"
    ver = "ver: 2.0"
    try:
        stdscr.addstr(max_y - 1, 0, footer[:max_x - 1])
        ver_x = max_x - len(ver) - 1
        if ver_x > len(footer):
            stdscr.addstr(max_y - 1, ver_x, ver)
    except curses.error:
        pass


def _layout(max_y: int, max_x: int,
            n_cores: int, n_disks: int, n_sensors: int,
            hdr_rows: int = 1) -> tuple:
    """Return (compact, sep, max_disks) for current terminal dimensions.

    compact   — skip per-core bars and inter-panel blank lines
    sep       — blank rows between panels (1 or 0)
    max_disks — max disks to show in compact mode (0 = no limit)
    """
    sep = 1 if max_y >= 30 else 0
    two_col = max_x >= 60

    # Row counts per panel in full mode
    cpu_rows  = 1 + (-(-n_cores // 2) if two_col else n_cores) + 1
    mem_rows  = 3
    disk_rows = 1 + n_disks
    temp_rows = 1 + n_sensors if n_sensors else 2  # "N/A" line

    full_needed = (
        hdr_rows    # header (1 or 2 rows depending on terminal width)
        + sep       # blank after header
        + cpu_rows  + sep
        + mem_rows  + sep
        + disk_rows + sep
        + temp_rows
        + 1         # footer
    )

    if full_needed <= max_y:
        return False, sep, 0

    # Compact mode: CPU avg only, no separators, limit disks
    # Fixed rows: header + cpu_compact(2) + mem(3) + temp + warning(1) + footer(1)
    fixed = 1 + 2 + mem_rows + temp_rows + 1 + 1
    avail_for_disks = max_y - fixed
    max_disks = max(0, avail_for_disks - 1)  # -1 for "Disks" header row
    return True, 0, max_disks


def main_loop(stdscr, args) -> None:
    """Curses event loop: draw panels, handle keys and terminal resize."""
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    # halfdelay(1) = block up to 100 ms on getch(); avoids busy-loop in tmux
    # where nodelay(True) + KEY_RESIZE flood would spin the CPU.
    curses.halfdelay(1)

    in_tmux = 'TMUX' in os.environ

    use_color = not args.no_color and curses.has_colors()
    if use_color:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(PAIR_HEADER,  curses.COLOR_CYAN,  -1)
        curses.init_pair(PAIR_GREEN,   curses.COLOR_GREEN, -1)
        curses.init_pair(PAIR_YELLOW,  curses.COLOR_YELLOW,-1)
        curses.init_pair(PAIR_RED,     curses.COLOR_RED,   -1)
        curses.init_pair(PAIR_SECTION, curses.COLOR_BLUE,  -1)

    # Prime psutil — first call returns 0.0 for all cores; discard it.
    psutil.cpu_percent(percpu=True, interval=None)
    n_cores = psutil.cpu_count(logical=True) or 1

    hostname           = socket.gethostname()
    partitions_cache:  list  = []
    partitions_fetched = 0.0
    sensors_cache:     dict  = {}
    sensors_fetched    = 0.0
    wifi_iface         = None   # None = not yet probed; '' = not found
    net_prev           = None   # (bytes_recv, bytes_sent, monotonic_time)

    interval = max(INTERVAL_MIN, min(INTERVAL_MAX, args.interval))
    if in_tmux:
        interval = max(1.0, interval)

    while True:
        now = time.monotonic()

        if now - partitions_fetched >= PARTITION_TTL:
            partitions_cache = [
                p for p in psutil.disk_partitions(all=False)
                if p.fstype not in _SKIP_FSTYPES
                and p.mountpoint not in _SKIP_MOUNT_EXACT
                and not any(p.mountpoint.startswith(pfx)
                            for pfx in _SKIP_MOUNT_PREFIXES)
            ]
            partitions_fetched = now

        if now - sensors_fetched >= SENSOR_TTL:
            try:
                sensors_cache = psutil.sensors_temperatures()
            except Exception:
                sensors_cache = {}
            sensors_fetched = now

        max_y, max_x = stdscr.getmaxyx()

        # --- network speed sampling ---
        try:
            counters = psutil.net_io_counters(pernic=True)
        except Exception:
            counters = {}
        if wifi_iface is None:
            wifi_iface = _find_wifi_iface(counters)
        now_net = time.monotonic()
        if wifi_iface and wifi_iface in counters:
            c = counters[wifi_iface]
            if net_prev is not None:
                dt = now_net - net_prev[2]
                if dt > 0:
                    dl = max(0.0, (c.bytes_recv - net_prev[0]) / dt)
                    ul = max(0.0, (c.bytes_sent - net_prev[1]) / dt)
                    wifi_str = f"↓ {_fmt_speed(dl)}  ↑ {_fmt_speed(ul)}"
                else:
                    wifi_str = "↓ ---  ↑ ---"
            else:
                wifi_str = "↓ ---  ↑ ---"
            net_prev = (c.bytes_recv, c.bytes_sent, now_net)
        else:
            wifi_str = "WiFi: N/A"

        # Estimate header height for layout (base ~70 chars + wifi_str)
        base_est = (
            f"Live-M  hostname: {hostname}   uptime: {uptime_str()}"
            f"   {datetime.datetime.now().strftime('%H:%M:%S')}"
            f"   refresh: {interval:.1f}s"
        )
        hdr_rows_est = 1 if len(base_est) + 3 + len(wifi_str) < max_x else 2

        stdscr.erase()

        n_disks   = len(partitions_cache)
        n_sensors = sum(len(v) for v in sensors_cache.values()) if sensors_cache else 0
        compact, sep, max_disks = _layout(
            max_y, max_x, n_cores, n_disks, n_sensors, hdr_rows_est)

        try:
            hdr_rows = draw_header(stdscr, hostname, interval, wifi_str, args.no_color, in_tmux)

            row = hdr_rows + sep
            row = draw_cpu(stdscr, row, args.no_color, compact=compact)
            row += sep
            row = draw_memory(stdscr, row, args.no_color)
            row += sep
            row = draw_disks(stdscr, row, args.no_color, partitions_cache,
                             max_count=max_disks)
            row += sep
            row = draw_temperatures(stdscr, row, args.no_color, sensors_cache)

            if compact:
                try:
                    warn = "  [terminal too small — resize to see all]"
                    stdscr.addstr(max_y - 2, 0, warn[:max_x - 1])
                except curses.error:
                    pass

            draw_footer(stdscr, interval)
        except curses.error:
            pass  # mid-draw overflow; next resize will fix it

        stdscr.refresh()

        # halfdelay(1) makes each getch() block up to 100 ms, so no sleep needed.
        # 'q' responds within 100 ms; no busy-loop even in tmux.
        deadline = time.monotonic() + interval
        while time.monotonic() < deadline:
            key = stdscr.getch()
            if key in (ord('q'), ord('Q'), 27):
                return
            elif key == ord('+'):
                interval = min(INTERVAL_MAX, round(interval + INTERVAL_STEP, 1))
                interval = max(INTERVAL_MIN, interval)
                break
            elif key == ord('-'):
                interval = max(INTERVAL_MIN, round(interval - INTERVAL_STEP, 1))
                interval = max(INTERVAL_MIN, interval)
                break
            elif key == curses.KEY_RESIZE:
                # Drain any queued KEY_RESIZE events before redrawing —
                # tmux floods these on client attach even without real resize.
                stdscr.nodelay(True)
                while stdscr.getch() == curses.KEY_RESIZE:
                    pass
                curses.halfdelay(1)
                curses.update_lines_cols()
                stdscr.clear()
                break


def main() -> None:
    """Parse CLI args and launch the curses UI."""
    parser = argparse.ArgumentParser(
        prog="livem",
        description="Lightweight live system monitor (CPU, RAM, disks, temps).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="N",
        help="refresh interval in seconds (default: 1.0, range: 0.5–10)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable colors (for unsupported terminals / log capture)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    args = parser.parse_args()

    try:
        curses.wrapper(main_loop, args)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            curses.endwin()
        except Exception:
            pass
        subprocess.run(['reset'], check=False)


if __name__ == "__main__":
    main()
