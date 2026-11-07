# Live-M

Lightweight CLI system monitor — lightweight replacement for htop + psensors.

[![Platform](https://img.shields.io/badge/platform-Linux-blue?logo=linux&logoColor=white)](https://www.linux.org/)
[![Python](https://img.shields.io/badge/language-python_3.8+-green)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-yellow)](https://opensource.org/license/MIT)
[![Stars](https://img.shields.io/github/stars/Icenux/Live-M?style=social)](https://github.com/Icenux/Live-M)

![Screenshot of Live-M running in a terminal (fake demo data)](docs/screenshot.png)

## What it shows

- **CPU** — per-core usage bars with color coding (2-column on wide terminals) + average + load average (1/5/15 min)
- **RAM & SWAP** — usage bars with used/total in GiB and percentage
- **Disks** — usage bars for all real mountpoints (skips tmpfs, snap, /boot)
- **Temperatures** — CPU package (full-width bar) + per-core bars; other detected sensors
- **Wi-Fi** — live ↓/↑ speed shown in the header

All panels update live. No process list — that's why it's lighter than htop.

## Requirements

- Linux (Debian / Ubuntu / Mint)
- Python 3.8+
- python3-psutil

## Installation

From the Icenux package repository (Debian / Ubuntu / Mint) — later versions then arrive with `apt upgrade`:

```bash
sudo curl -fsSL https://icenux.github.io/icenux/icenux.asc -o /usr/share/keyrings/icenux.asc
echo 'deb [signed-by=/usr/share/keyrings/icenux.asc] https://icenux.github.io/icenux/apt ./' \
  | sudo tee /etc/apt/sources.list.d/icenux.list
sudo apt update && sudo apt install livem
```

From source:

```bash
git clone https://github.com/Icenux/Live-M.git && cd Live-M
pip install .          # or run without installing: PYTHONPATH=src python3 -m livem
```

## Usage

```bash
livem
```

| Key | Action |
|-----|--------|
| `q` / `Ctrl+C` | Quit |
| `+` | Increase refresh interval |
| `-` | Decrease refresh interval |

Optional flags:

```bash
livem --interval 2    # refresh every 2 seconds
livem --no-color      # disable colors
livem --version
livem --help
```

## Why not htop?

htop iterates over all processes in `/proc/[pid]/` on every refresh. Live-M skips processes entirely — CPU usage stays under 0.5%.
