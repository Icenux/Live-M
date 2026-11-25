#!/usr/bin/env python3
"""Regenerate docs/screenshot.png with FAKE demo data (no real host data leaks).

Usage (from the repo root; needs tmux, Pillow and the JetBrainsMono Nerd Font):

    python3 tools/make_screenshot.py [output.png]

How it works: the script starts itself inside a tmux pane with psutil, the
hostname, the clock and the process sampler replaced by fixed fake values,
captures the pane with its ANSI colours and draws it into a PNG.
"""

import os
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

COLS, ROWS = 100, 22
REPO = Path(__file__).resolve().parent.parent
FONT_DIR = Path("/usr/share/fonts/TTF")
FONT_REG = FONT_DIR / "JetBrainsMonoNerdFontMono-Regular.ttf"
FONT_BOLD = FONT_DIR / "JetBrainsMonoNerdFontMono-Bold.ttf"

# Colours sampled from the previous screenshot
BG = (0, 0, 0)
BORDER = (40, 85, 119)
PALETTE = {
    None: (0, 170, 0),      # default text
    31: (214, 70, 60),      # red
    32: (0, 170, 0),        # green
    33: (227, 196, 1),      # yellow
    34: (36, 172, 212),     # blue (section headings)
    36: (19, 194, 153),     # cyan (header)
}


# ------------------------------------------------------------------ inner: fake app
def run_fake_app() -> None:
    sys.path.insert(0, str(REPO / "src"))
    os.environ.pop("TMUX", None)   # no "[tmux]" tag in the header
    import datetime
    import socket

    import psutil

    from livem import app, procs

    GiB = 1024 ** 3
    VM = namedtuple("VM", "total used percent")
    DU = namedtuple("DU", "total used free percent")
    Part = namedtuple("Part", "device mountpoint fstype opts")
    Temp = namedtuple("Temp", "label current high critical")
    Net = namedtuple("Net", "bytes_recv bytes_sent")
    t0 = time.monotonic()

    psutil.cpu_percent = lambda percpu=False, interval=None: [14.0, 62.0, 8.0, 41.0]
    psutil.cpu_count = lambda logical=True: 4
    psutil.virtual_memory = lambda: VM(16 * GiB, int(6.4 * GiB), 40.0)
    psutil.swap_memory = lambda: VM(4 * GiB, int(0.3 * GiB), 7.0)
    psutil.disk_partitions = lambda all=False: [
        Part("/dev/sda2", "/", "ext4", ""), Part("/dev/sda3", "/home", "ext4", "")]
    usage = {"/": DU(200 * GiB, 74 * GiB, 126 * GiB, 37.0),
             "/home": DU(400 * GiB, 210 * GiB, 190 * GiB, 52.0)}
    psutil.disk_usage = lambda mp: usage[mp]
    psutil.sensors_temperatures = lambda: {"coretemp": [
        Temp("Package id 0", 48.0, 100.0, 100.0),
        Temp("Core 0", 46.0, 100.0, 100.0),
        Temp("Core 1", 45.0, 100.0, 100.0)]}
    psutil.net_io_counters = lambda pernic=False: {"wlan0": Net(
        int((time.monotonic() - t0) * 146_500), int((time.monotonic() - t0) * 19_500))}
    os.getloadavg = lambda: (0.42, 0.38, 0.51)
    socket.gethostname = lambda: "demo-pc"
    app.uptime_str = lambda: "2h 14m"

    class FakeDT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 25, 11, 6, 24)
    app.datetime = type("dt", (), {"datetime": FakeDT})

    def fake_poll(self, now=None):
        P = procs.ProcInfo
        self.top_cpu = [P(1, "ffmpeg", 94.2, int(0.4 * GiB)), P(2, "firefox", 38.5, int(2.1 * GiB)),
                        P(3, "code", 12.1, int(1.4 * GiB)), P(4, "Xorg", 4.3, 210 * 1024 ** 2),
                        P(5, "pipewire", 1.8, 38 * 1024 ** 2)]
        self.top_mem = [P(2, "firefox", 38.5, int(2.1 * GiB)), P(3, "code", 12.1, int(1.4 * GiB)),
                        P(6, "thunderbird", 0.6, 612 * 1024 ** 2), P(7, "python3", 0.3, 301 * 1024 ** 2),
                        P(4, "Xorg", 4.3, 210 * 1024 ** 2)]
        self.ready = True
    procs.ProcSampler.poll = fake_poll

    sys.argv = ["livem", "--procs"]
    app.main()


# ------------------------------------------------------------------ outer: capture + render
def parse_ansi(text: str):
    """Yield rows of (char, fg_code, bold) from `tmux capture-pane -e` output."""
    rows = []
    fg, bold = None, False
    for line in text.split("\n"):
        row, i = [], 0
        while i < len(line):
            ch = line[i]
            if ch == "\x1b" and line[i + 1:i + 2] == "[":
                j = line.index("m", i)
                for code in (line[i + 2:j] or "0").split(";"):
                    n = int(code or 0)
                    if n == 0:
                        fg, bold = None, False
                    elif n == 1:
                        bold = True
                    elif n == 22:
                        bold = False
                    elif 30 <= n <= 37:
                        fg = n
                    elif n == 39:
                        fg = None
                i = j + 1
                continue
            row.append((ch, fg, bold))
            i += 1
        rows.append(row)
    return rows


def render(rows, out: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    size = 23
    reg, bold = ImageFont.truetype(str(FONT_REG), size), ImageFont.truetype(str(FONT_BOLD), size)
    cw = round(reg.getlength("M"))
    ch = 34
    pad_x, pad_y, border = 32, 22, 4
    width = COLS * cw + 2 * pad_x + 2 * border
    height = ROWS * ch + 2 * pad_y + 2 * border
    img = Image.new("RGB", (width, height), BORDER)
    d = ImageDraw.Draw(img)
    d.rectangle([border, border, width - border - 1, height - border - 1], fill=BG)
    for r, row in enumerate(rows[:ROWS]):
        for c, (char, fg, b) in enumerate(row[:COLS]):
            if char == " ":
                continue
            d.text((border + pad_x + c * cw, border + pad_y + r * ch + 3), char,
                   font=bold if b else reg, fill=PALETTE.get(fg, PALETTE[None]))
    img.save(out, optimize=True)


def main() -> None:
    if "--inner" in sys.argv:
        run_fake_app()
        return
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs" / "screenshot.png"
    sock = f"livem-shot-{os.getpid()}"
    tm = ["tmux", "-L", sock, "-f", "/dev/null"]
    try:
        subprocess.run(tm + ["new-session", "-d", "-x", str(COLS), "-y", str(ROWS),
                             f"{sys.executable} {Path(__file__).resolve()} --inner"], check=True)
        time.sleep(4.0)
        text = subprocess.run(tm + ["capture-pane", "-e", "-p"], check=True,
                              capture_output=True, text=True).stdout
    finally:
        subprocess.run(tm + ["kill-server"], check=False)
    render(parse_ansi(text), out)
    print(f"written {out}")


if __name__ == "__main__":
    main()
