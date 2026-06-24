# connmanTUI

A minimal terminal user interface (TUI) for managing Wi-Fi connections on Linux systems that use [ConnMan](https://wiki.archlinux.org/title/ConnMan) as their network manager.

## Motivation

ConnMan's GTK GUI is unreliable on many setups. The command-line tool `connmanctl` works perfectly but requires several manual steps to scan, list, and connect to a network. connmanTUI wraps that workflow into a simple, keyboard-driven interface.

## Features

- Scans for available Wi-Fi networks on startup
- Lists networks with live connection status
- Connects to known networks (stored credentials) with a single keypress
- Prompts for a WPA/WPA2 passphrase when connecting to a new network
- Auto-refreshes the network list after connecting or disconnecting
- No external dependencies — uses only Python 3 stdlib (`curses`, `pty`, `subprocess`)

## Requirements

- Python 3.6+
- `connman` installed and running
- A terminal emulator with 256-color support (recommended)

## Usage

```bash
python3 connman_tui.py
```

Or make it executable and run directly:

```bash
chmod +x connman_tui.py
./connman_tui.py
```

## Key bindings

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate the network list |
| `Enter` | Connect to the selected network |
| `d` | Disconnect from the selected network |
| `r` | Rescan for networks |
| `q` / `Esc` | Quit |

## Network status indicators

| Indicator | Meaning |
|-----------|---------|
| `●` green | Connected and online |
| `  ` white | Not connected |

## Tested on

Artix Linux (OpenRC), ConnMan 1.45

## Development

This project was developed with the assistance of [Claude Code](https://claude.ai/code), Anthropic's AI coding assistant.
