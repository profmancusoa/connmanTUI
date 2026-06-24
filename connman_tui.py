#!/usr/bin/env python3
"""connmanTUI - TUI per gestire connessioni WiFi tramite connman."""

import curses
import os
import pty
import select
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# connmanctl helpers
# ---------------------------------------------------------------------------

def run_cmd(*args, timeout=15):
    try:
        result = subprocess.run(
            list(args), capture_output=True, text=True, timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Timeout", 1
    except FileNotFoundError:
        return "", f"Comando non trovato: {args[0]}", 1


def scan_wifi():
    run_cmd("connmanctl", "scan", "wifi", timeout=20)


def get_services():
    stdout, _, rc = run_cmd("connmanctl", "services")
    if rc != 0:
        return []

    services = []
    for line in stdout.split("\n"):
        if not line.strip() or "wifi_" not in line:
            continue
        tokens = line.split()
        service_id = tokens[-1]
        if not service_id.startswith("wifi_"):
            continue
        flags = line[:4]
        name = line[4 : line.rfind(service_id)].strip()
        services.append(
            {
                "flags": flags,
                "name": name if name else service_id,
                "id": service_id,
                "online": "O" in flags,
                "connected": "*" in flags,
            }
        )
    return services


def disconnect_service(service_id):
    stdout, stderr, rc = run_cmd("connmanctl", "disconnect", service_id, timeout=10)
    return rc == 0, (stdout + stderr).strip()


def connect_via_pty(service_id, password=None):
    """
    Avvia connmanctl in modalità interattiva via PTY.
    Registra l'agent e tenta la connessione.

    Restituisce (needs_password, success, message):
      - needs_password=True  → richiamala di nuovo con password=<stringa>
      - success=True         → connessione riuscita
      - success=False        → connessione fallita, message contiene l'errore
    """
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["connmanctl"],
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    buf = b""

    def _read_until(patterns, timeout=15.0):
        """Legge fino a trovare uno dei pattern. Restituisce il pattern trovato o None."""
        nonlocal buf
        deadline = time.time() + timeout
        while time.time() < deadline:
            r, _, _ = select.select([master_fd], [], [], 0.1)
            if r:
                try:
                    buf += os.read(master_fd, 512)
                except OSError:
                    break
            decoded = buf.decode("utf-8", errors="replace")
            for p in patterns:
                if p in decoded:
                    return p
            if proc.poll() is not None:
                # Svuota il buffer PTY rimasto prima di arrendersi
                try:
                    while select.select([master_fd], [], [], 0.3)[0]:
                        buf += os.read(master_fd, 512)
                except OSError:
                    pass
                decoded = buf.decode("utf-8", errors="replace")
                for p in patterns:
                    if p in decoded:
                        return p
                return None
        return None

    def _write(text):
        try:
            os.write(master_fd, (text + "\n").encode())
        except OSError:
            pass

    def _close():
        try:
            _write("quit")
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        try:
            os.close(master_fd)
        except Exception:
            pass

    try:
        # Attendi prompt iniziale
        if not _read_until(["connmanctl>"], 5.0):
            _close()
            return False, False, "Timeout avvio connmanctl"

        buf = b""
        _write("agent on")
        _read_until(["connmanctl>"], 5.0)

        buf = b""
        _write(f"connect {service_id}")

        found = _read_until(["Connected", "Error", "Passphrase?"], 25.0)

        if found == "Passphrase?":
            if password is None:
                _close()
                return True, False, ""   # segnala: serve password

            buf = b""
            _write(password)
            found = _read_until(["Connected", "Error", "Passphrase?"], 20.0)

            if found == "Passphrase?":
                # Password sbagliata: connmanctl richiede di nuovo
                _close()
                return False, False, "Password non corretta"

        _close()
        decoded = buf.decode("utf-8", errors="replace")

        if found == "Connected":
            return False, True, "Connesso"

        lines = [l.strip() for l in decoded.split("\n") if l.strip()]
        msg = lines[-1] if lines else decoded.strip()
        return False, False, msg

    except Exception as exc:
        try:
            _close()
        except Exception:
            pass
        return False, False, str(exc)


# ---------------------------------------------------------------------------
# Curses widgets
# ---------------------------------------------------------------------------

def password_dialog(stdscr, network_name):
    """Mostra un dialogo per inserire la password. Restituisce la stringa o None se annullato."""
    h, w = stdscr.getmaxyx()
    dw = min(60, w - 4)
    dh = 7
    dy = (h - dh) // 2
    dx = (w - dw) // 2

    win = curses.newwin(dh, dw, dy, dx)
    win.attron(curses.color_pair(3))
    win.box()
    win.attroff(curses.color_pair(3))

    title = f" Password per: {network_name} "
    if len(title) > dw - 2:
        title = title[: dw - 5] + "... "
    win.addstr(0, max(1, (dw - len(title)) // 2), title, curses.color_pair(3) | curses.A_BOLD)
    win.addstr(2, 2, "Passphrase WiFi:")
    win.addstr(5, 2, "Invio = Conferma    Esc = Annulla", curses.color_pair(5))
    win.refresh()

    input_y = dy + 3
    input_x = dx + 2
    input_w = dw - 4

    curses.curs_set(1)
    password = ""

    while True:
        # Ridisegna campo input
        stdscr.addstr(input_y, input_x, " " * input_w)
        display = ("*" * len(password))[: input_w - 1]
        stdscr.addstr(input_y, input_x, display)
        stdscr.move(input_y, input_x + len(display))
        stdscr.refresh()

        key = win.getch()

        if key in (curses.KEY_ENTER, 10, 13):
            break
        elif key == 27:  # ESC
            curses.curs_set(0)
            return None
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            password = password[:-1]
        elif 32 <= key <= 126:
            password += chr(key)

    curses.curs_set(0)
    return password


def draw_ui(stdscr, services, selected, scroll, status_msg):
    h, w = stdscr.getmaxyx()
    stdscr.clear()

    title = " connmanTUI - WiFi Manager "
    stdscr.addstr(0, 0, title.center(w - 1, "─"), curses.color_pair(3) | curses.A_BOLD)
    stdscr.addstr(1, 0, "─" * (w - 1), curses.color_pair(3))

    list_start = 2
    list_height = h - 5

    if not services:
        msg = "Nessuna rete trovata. Premi 'r' per ripetere la scansione."
        stdscr.addstr(
            list_start + list_height // 2,
            max(0, (w - len(msg)) // 2),
            msg,
            curses.color_pair(4),
        )
    else:
        for i, svc in enumerate(services):
            if i < scroll or i >= scroll + list_height:
                continue
            row = list_start + (i - scroll)

            if svc["online"]:
                indicator = "● "
                base_attr = curses.color_pair(1) | curses.A_BOLD
            elif svc["connected"]:
                indicator = "● "
                base_attr = curses.color_pair(1)
            else:
                indicator = "  "
                base_attr = curses.A_NORMAL

            line = f"{indicator}{svc['name']}"
            if len(line) > w - 2:
                line = line[: w - 5] + "..."

            if i == selected:
                stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
                stdscr.addstr(row, 0, line.ljust(w - 1))
                stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)
            else:
                stdscr.addstr(row, 0, line, base_attr)

    stdscr.addstr(h - 3, 0, "─" * (w - 1), curses.color_pair(3))
    if status_msg:
        is_err = status_msg.lower().startswith("errore") or status_msg.lower().startswith("password")
        stdscr.addstr(h - 2, 1, status_msg[: w - 2],
                      curses.color_pair(4) if is_err else curses.A_NORMAL)
    help_line = "↑↓ Naviga  Invio Connetti  d Disconnetti  r Rileggi  q Esci"
    stdscr.addstr(h - 1, 0, help_line[: w - 1], curses.color_pair(5))
    stdscr.refresh()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    # Usa la palette 256 (cube 6x6x6, indici 16-231) se disponibile:
    # questi colori sono fissi e non rimappabili dai temi del terminale.
    # Fallback ai colori ANSI standard per terminali a 8 colori.
    if curses.COLORS >= 256:
        _GREEN = 46   # #00ff00 — sempre verde nella cube xterm-256
        _RED   = 196  # #ff0000 — sempre rosso
        _CYAN  = 44   # #00d7d7 — sempre ciano
        _GREY  = 250  # #bcbcbc — grigio chiaro per testo secondario
        _BG_SEL = 24  # #005f87 — blu scuro per la riga selezionata
    else:
        _GREEN = curses.COLOR_GREEN
        _RED   = curses.COLOR_RED
        _CYAN  = curses.COLOR_CYAN
        _GREY  = curses.COLOR_WHITE
        _BG_SEL = curses.COLOR_BLUE

    curses.init_pair(1, _GREEN, -1)                  # connesso → verde
    curses.init_pair(3, _CYAN,  -1)                  # header   → ciano
    curses.init_pair(4, _RED,   -1)                  # errore   → rosso
    curses.init_pair(5, _GREY,  -1)                  # help     → grigio
    curses.init_pair(6, curses.COLOR_WHITE, _BG_SEL) # selezionato → bianco su blu

    h, w = stdscr.getmaxyx()
    stdscr.clear()
    msg = "Scansione reti WiFi in corso..."
    stdscr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg, curses.color_pair(3) | curses.A_BOLD)
    stdscr.refresh()

    scan_wifi()
    services = get_services()

    selected = 0
    scroll = 0
    status_msg = f"Trovate {len(services)} reti. Premi 'r' per aggiornare."

    while True:
        h, w = stdscr.getmaxyx()
        list_height = h - 5

        if selected < scroll:
            scroll = selected
        elif selected >= scroll + list_height:
            scroll = selected - list_height + 1

        draw_ui(stdscr, services, selected, scroll, status_msg)
        key = stdscr.getch()

        if key in (ord("q"), 27):
            break

        elif key == curses.KEY_UP:
            if selected > 0:
                selected -= 1

        elif key == curses.KEY_DOWN:
            if selected < len(services) - 1:
                selected += 1

        elif key in (curses.KEY_ENTER, 10, 13):
            if not services:
                continue
            svc = services[selected]

            status_msg = f"Connessione a {svc['name']}..."
            draw_ui(stdscr, services, selected, scroll, status_msg)

            svc_id = svc["id"]
            svc_name = svc["name"]

            needs_pw, _, _ = connect_via_pty(svc_id)

            if needs_pw:
                password = password_dialog(stdscr, svc_name)
                if password is None:
                    status_msg = "Connessione annullata"
                    continue
                status_msg = f"Connessione a {svc_name}..."
                draw_ui(stdscr, services, selected, scroll, status_msg)
                connect_via_pty(svc_id, password)

            # Aspetta sempre che connman aggiorni lo stato, poi verifica
            # dallo stato reale del servizio (non dal return value del PTY)
            time.sleep(2.5)
            services = get_services()
            selected = min(selected, max(0, len(services) - 1))
            updated = next((s for s in services if s["id"] == svc_id), None)
            if updated and (updated["connected"] or updated["online"]):
                status_msg = f"Connesso a {svc_name}"
            else:
                status_msg = f"Connessione a {svc_name} non riuscita"

        elif key == ord("d"):
            if not services:
                continue
            svc = services[selected]
            if svc["connected"]:
                status_msg = f"Disconnessione da {svc['name']}..."
                draw_ui(stdscr, services, selected, scroll, status_msg)
                success, out = disconnect_service(svc["id"])
                if success:
                    time.sleep(1.0)
                services = get_services()
                selected = min(selected, max(0, len(services) - 1))
                status_msg = f"Disconnesso da {svc['name']}" if success else f"Errore: {out}"
            else:
                status_msg = f"{svc['name']} non è connessa"

        elif key == ord("r"):
            status_msg = "Scansione in corso..."
            draw_ui(stdscr, services, selected, scroll, status_msg)
            scan_wifi()
            services = get_services()
            selected = min(selected, max(0, len(services) - 1))
            scroll = 0
            status_msg = f"Scansione completata. Trovate {len(services)} reti."


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)
