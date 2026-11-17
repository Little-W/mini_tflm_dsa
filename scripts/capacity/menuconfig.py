#!/usr/bin/env python3
"""Edit the shared NPU configuration in an interactive terminal.

Uses Python's standard curses module. Changes, including optimized capacity
settings, remain in a draft until Save is selected.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import locale
import os
from pathlib import Path
import sys
import textwrap
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from scripts.capacity import model, im2col_cache


@dataclass(frozen=True)
class Field:
    key: str
    group: str
    label: str
    help: str
    choices: tuple = ()
    byte_size: bool = False


FIELDS = (
    Field("PCR_ENGINE", "Compute and PS", "Compressed PS storage",
          "Use the addressable PS frame store with the shared compute array. "
          "INT8, INT16, WS/IS, Conv and the vector engine remain available.", (0, 1)),
    Field("SIZE", "Compute and PS", "Array size",
          "Square compute array dimension. Compressed PS requires SIZE=16.", (2, 4, 8, 16, 32)),
    Field("CAPACITY_BUDGET_SCOPE", "Budget", "Budget scope",
          "buffer-ram counts all operand, PS, output, Conv and vector buffer arrays plus metadata. "
          "logical-state requires actual Verilator elaboration of every sequential declaration.",
          ("buffer-ram", "logical-state")),
    Field("CAPACITY_BUDGET_BYTES", "Budget", "Capacity limit",
          "Enter bytes or binary units such as 128 KiB. Save requires the selected allocation to fit.", byte_size=True),
    Field("CAPACITY_REPRESENTATION", "Budget", "PS representation",
          "adaptive enables the row codec. raw32 forces four payload words per row. "
          "Planning checks each format's bank bandwidth, protected-frame capacity and directory.", ("adaptive", "raw32")),
    Field("IA_CACHE_BLOCKS", "Buffers and bus", "IA cache blocks",
          "Tile-buffer configuration for output queues and ordinary FIFO operation. "
          "Shared IA allocation and source format determine each layer's R limit."),
    Field("PS_FRAME_COUNT", "Buffers and bus", "PS frame slots",
          "Frame metadata entries. Shared tasks are also limited by 1024 directory rows and PS capacity."),
    Field("PS_POOL_BYTES", "Buffers and bus", "PS build parameter",
          "Positive multiple of 64 bytes for standalone PS store tests. Shared hardware capacity "
          "is determined by bank size and bank count.", byte_size=True),
    Field("SHARED_BANK_BYTES", "Shared IA/PS RAM", "Bytes per bank",
          "Physical RAM bytes in each independent bank. Directory and decode buffers are separate.",
          (2048, 4096, 8192), byte_size=True),
    Field("SHARED_BANK_COUNT", "Shared IA/PS RAM", "Physical bank count",
          "Total data RAM is bank count times bytes per bank. Prepare assigns 1, 2 or 4 banks to IA.",
          (6, 7, 8, 9)),
    Field("PS_FORCE_RAW", "Buffers and bus", "Force RAW32 records",
          "Store every encoded PS row as four 128-bit words.", (0, 1)),
    Field("NPU_AXI_DATA_WIDTH", "Buffers and bus", "NPU AXI4 data width",
          "NPU DMA and memory data bits. CPU and AXI-Lite register data remain 32 bits.", (32, 64)),
    Field("AXI_READ_OUTSTANDING", "Buffers and bus", "AXI read outstanding",
          "Maximum queued read transactions, from 1 to 16."),
    Field("IM2COL_CACHE_BYTES", "Convolution input cache", "im2col data cache",
          "Original-image data bytes, separate from shared IA/PS RAM. Two ways and 16-byte lines; "
          "512 B to 64 KiB in powers of two. Press ? for convolution sizes at the selected capacity.",
          im2col_cache.BYTE_CHOICES, byte_size=True),
)

ACTIONS = (("optimize", "Optimize capacity for the selected workloads"),
           ("save", "Save configuration"),
           ("reload", "Reload configuration from disk"),
           ("quit", "Exit menuconfig"))


def byte_text(value):
    if abs(value) >= 1024:
        return f"{value / 1024:g} KiB"
    return exact_bytes(value) + " B"


def exact_bytes(value):
    """State counts are whole bits, so byte counts need at most 3 decimals."""
    if isinstance(value, int):
        return str(value)
    return format(value, ".3f").rstrip("0").rstrip(".")


def clip_cells(text, width):
    """Clip display text without splitting wide characters at the edge."""
    result, used = [], 0
    for char in str(text).replace("\n", " ").replace("\r", " "):
        cells = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in "WF" else 1)
        if used + cells > width:
            break
        result.append(char)
        used += cells
    return "".join(result)


def path_label(path, width):
    """Prefer repository-relative paths; keep the filename when shortening."""
    path = Path(path)
    try:
        text = str(path.relative_to(ROOT))
    except ValueError:
        text = str(path)
    if clip_cells(text, width) == text:
        return text
    head = clip_cells(text, max(0, width // 3))
    head_width = sum(0 if unicodedata.combining(char) else
                     2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in head)
    tail = clip_cells(text[::-1], max(0, width - head_width - 3))[::-1]
    return head + "..." + tail


class TerminalMenu:
    MIN_HEIGHT = 18
    MIN_WIDTH = 60

    def __init__(self, screen, state, curses):
        self.screen, self.state, self.c = screen, state, curses
        self.selected = self.scroll = 0
        self.status = "Edit the draft, then press S to save. O optimizes capacity."
        self.status_error = False
        self.ever_saved = self.discarded = False
        self.title_style = curses.A_BOLD
        self.selected_style = curses.A_REVERSE
        self.warning_style = curses.A_BOLD
        self.good_style = 0
        screen.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if hasattr(curses, "set_escdelay"):
            curses.set_escdelay(30)
        try:
            if curses.has_colors():
                curses.start_color()
                try:
                    curses.use_default_colors()
                    background = -1
                except curses.error:
                    background = curses.COLOR_BLACK
                curses.init_pair(1, curses.COLOR_CYAN, background)
                curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
                curses.init_pair(3, curses.COLOR_YELLOW, background)
                curses.init_pair(4, curses.COLOR_GREEN, background)
                self.title_style |= curses.color_pair(1)
                self.selected_style = curses.color_pair(2) | curses.A_BOLD
                self.warning_style |= curses.color_pair(3)
                self.good_style = curses.color_pair(4)
        except curses.error:
            pass

    def _put(self, window, y, x, text, style=0):
        height, width = window.getmaxyx()
        if 0 <= y < height and 0 <= x < width:
            # Avoid the bottom-right cell, which raises on some terminals.
            room = width - x - (1 if y == height - 1 else 0)
            if room > 0:
                try:
                    window.addstr(y, x, clip_cells(text, room), style)
                except (self.c.error, UnicodeError):
                    pass

    def _get_key(self, window):
        # A terminal resize may reach a Make-launched process while ncurses is
        # blocked reading input. Check the actual PTY dimensions periodically
        # as well as consuming KEY_RESIZE, including while a dialog is open.
        window.timeout(200)
        while True:
            try:
                size = os.get_terminal_size(sys.stdout.fileno())
            except OSError:
                size = None
            if (size is not None and size.lines > 0 and size.columns > 0 and
                    (size.lines, size.columns) != self.screen.getmaxyx()):
                self.c.resizeterm(size.lines, size.columns)
                self.screen.clearok(True)
                return self.c.KEY_RESIZE
            try:
                return window.get_wch()
            except self.c.error:
                # get_wch reports an error when its bounded wait expires.
                continue

    def _rows(self):
        rows, previous = [], None
        for index, field in enumerate(FIELDS):
            if field.group != previous:
                rows.append((None, field.group, ""))
                previous = field.group
            value = self.state.values[field.key]
            if field.choices == (0, 1):
                display = "[*]" if value else "[ ]"
            elif field.byte_size:
                display = byte_text(value)
            else:
                display = str(value)
            rows.append((index, field.label, display))
        rows.append((None, "Actions", ""))
        for offset, (_, label) in enumerate(ACTIONS):
            rows.append((len(FIELDS) + offset, label, "--->"))
        return rows

    def draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < self.MIN_HEIGHT or width < self.MIN_WIDTH:
            self._put(self.screen, 0, 0, "GEMPACT NPU menuconfig", self.title_style)
            self._put(self.screen, 1, 0, f"Terminal too small ({width}x{height}).")
            self._put(self.screen, 2, 0, "Resize to at least 60x18. Q quits.")
            self.screen.refresh()
            return False
        dirty = "  [modified]" if self.state.dirty else "  [saved]"
        self._put(self.screen, 0, 1, "GEMPACT NPU menuconfig" + dirty, self.title_style)
        self._put(self.screen, 1, 1, "Config: " + path_label(self.state.path, width - 10))
        workload = self.state.workload_label
        if Path(workload).is_absolute():
            workload = path_label(workload, width - 13)
        self._put(self.screen, 2, 1, "Workloads: " + workload)
        self._put(self.screen, 3, 1, "Parameter", self.c.A_DIM)
        self._put(self.screen, 3, max(34, width - 20), "Value", self.c.A_DIM)

        rows = self._rows()
        selected_row = next(i for i, row in enumerate(rows) if row[0] == self.selected)
        visible = height - 13
        if selected_row < self.scroll:
            self.scroll = selected_row
        elif selected_row >= self.scroll + visible:
            self.scroll = selected_row - visible + 1
        self.scroll = max(0, min(self.scroll, max(0, len(rows) - visible)))
        for offset, (index, label, value) in enumerate(rows[self.scroll:self.scroll + visible]):
            y = 4 + offset
            if index is None:
                self._put(self.screen, y, 1, "--- " + label + " ---", self.title_style)
            else:
                style = self.selected_style if index == self.selected else 0
                self._put(self.screen, y, 1, " " * (width - 2), style)
                value_x = max(34, width - 20)
                self._put(self.screen, y, 2, clip_cells(("> " if index == self.selected else "  ") + label,
                                                       value_x - 3), style)
                self._put(self.screen, y, value_x, value, style)
        summary = self.state.capacity_summary()
        self._put(self.screen, height - 9, 1, "-" * (width - 2), self.c.A_DIM)
        alloc = summary["allocation"]
        if alloc is not None:
            if alloc["shared_ia_ps_enabled"]:
                allocation_text = (f"Shared data: {byte_text(alloc['shared_total_bytes'])}  "
                                   f"IA banks: 1/2/4  Frames: {alloc['ps_frame_count']}")
            else:
                allocation_text = (f"IA blocks: {alloc['ia_cache_blocks']}  Frames: {alloc['ps_frame_count']}  "
                                   f"PS: {byte_text(alloc['ps_pool_bytes'])}  RAM: {byte_text(alloc['buffer_ram_bytes'])}")
            self._put(self.screen, height - 8, 1, allocation_text)
            state = alloc['logical_state_bytes']
            state_text = "Complete state: requires RTL elaboration" if state is None else f"Complete state: {byte_text(state)} ({exact_bytes(state)} B)"
            self._put(self.screen, height - 7, 1, state_text)
            budget = self.state.values["CAPACITY_BUDGET_BYTES"]
            self._put(self.screen, height - 6, 1,
                      f"{self.state.values['CAPACITY_BUDGET_SCOPE']}: "
                      f"{byte_text(alloc['budget_used_bytes'])} / {byte_text(budget)}; "
                      f"free {byte_text(alloc['unused_budget_bytes'])}")
        else:
            self._put(self.screen, height - 8, 1, "Capacity requires a valid configuration and RTL state measurement.")
        error = summary["validation_error"]
        self._put(self.screen, height - 5, 1,
                  "Invalid: " + error if error else "Configuration is valid.",
                  self.warning_style if error else self.good_style)
        if self.selected < len(FIELDS):
            self._put(self.screen, height - 4, 1, FIELDS[self.selected].key + "  [? for help]", self.c.A_DIM)
        self._put(self.screen, height - 3, 1, self.status,
                  self.warning_style if self.status_error else self.good_style)
        self._put(self.screen, height - 2, 1, "Up/Down Move  Enter/Space Edit  O Optimize  S Save", self.c.A_BOLD)
        self._put(self.screen, height - 1, 1, "L Reload  Q Quit  ? Help  PgUp/PgDn Scroll", self.c.A_BOLD)
        self.screen.refresh()
        return True

    def _dialog(self, title, lines, footer, scroll=0):
        self.draw()
        height, width = self.screen.getmaxyx()
        w = max(1, min(width - 2, 78))
        wrapped = []
        for line in lines:
            wrapped.extend(textwrap.wrap(str(line), max(1, w - 4)) or [""])
        h = max(1, min(height - 2, len(wrapped) + 5))
        win = self.c.newwin(h, w, max(0, (height - h) // 2), max(0, (width - w) // 2))
        win.keypad(True)
        try:
            win.box()
        except self.c.error:
            pass
        self._put(win, 0, 2, " " + title + " ", self.title_style)
        visible = max(1, h - 4)
        scroll = max(0, min(scroll, max(0, len(wrapped) - visible)))
        for index, line in enumerate(wrapped[scroll:scroll + visible]):
            self._put(win, index + 1, 2, line)
        self._put(win, h - 2, 2, footer, self.c.A_BOLD)
        win.refresh()
        return win, scroll, max(0, len(wrapped) - visible)

    def message(self, title, text):
        scroll = 0
        while True:
            win, scroll, maximum = self._dialog(title, str(text).splitlines(), "Enter Back | Up/Down Scroll", scroll)
            key = self._get_key(win)
            if key == self.c.KEY_RESIZE:
                continue
            if key in (self.c.KEY_DOWN, "j"):
                scroll = min(maximum, scroll + 1)
            elif key in (self.c.KEY_UP, "k"):
                scroll = max(0, scroll - 1)
            elif key == self.c.KEY_NPAGE:
                scroll = min(maximum, scroll + 5)
            elif key == self.c.KEY_PPAGE:
                scroll = max(0, scroll - 5)
            else:
                return

    def confirm(self, title, body, footer, allowed):
        while True:
            win, _, _ = self._dialog(title, [body], footer)
            key = self._get_key(win)
            if key == self.c.KEY_RESIZE:
                continue
            if isinstance(key, str) and key.lower() in allowed:
                return key.lower()
            if key in ("\x1b", "\n", "\r", "q", "Q", self.c.KEY_ENTER):
                return "c"

    def edit_number(self, field):
        text = str(self.state.values[field.key])
        cursor, first = len(text), True
        try:
            self.c.curs_set(1)
        except self.c.error:
            pass
        try:
            while True:
                self.draw()
                height, width = self.screen.getmaxyx()
                if height < 9 or width < 30:
                    self._put(self.screen, 3, 0, "Resize to edit; Esc cancels.")
                    self.screen.refresh()
                    if self._get_key(self.screen) == "\x1b":
                        return
                    continue
                h, w = 8, min(78, width - 2)
                win = self.c.newwin(h, w, (height - h) // 2, (width - w) // 2)
                win.keypad(True)
                win.box()
                self._put(win, 0, 2, " Edit " + field.key + " ", self.title_style)
                self._put(win, 2, 2, "New value (B, KiB, MiB; no suffix = bytes):" if field.byte_size
                          else "New integer value:")
                room = max(1, w - 5)
                offset = max(0, cursor - room + 1)
                self._put(win, 3, 2, text[offset:offset + room], self.c.A_REVERSE if first else 0)
                self._put(win, 5, 2, "Enter Apply | Esc Cancel | Ctrl-U Clear", self.c.A_BOLD)
                win.move(3, min(w - 3, 2 + cursor - offset))
                win.refresh()
                key = self._get_key(win)
                if key == self.c.KEY_RESIZE:
                    continue
                if key == "\x1b":
                    return
                if key in ("\n", "\r", self.c.KEY_ENTER):
                    try:
                        self.state.set_value(field.key, text)
                    except (ValueError, OSError) as error:
                        self.message("Invalid value", error)
                        continue
                    self.status, self.status_error = "Updated draft. Press S to save.", False
                    return
                if key == "\x15":
                    text, cursor, first = "", 0, False
                elif key in (self.c.KEY_BACKSPACE, "\x7f", "\b"):
                    if first:
                        text, cursor = "", 0
                    elif cursor:
                        text = text[:cursor - 1] + text[cursor:]
                        cursor -= 1
                    first = False
                elif key == self.c.KEY_DC:
                    text = "" if first else text[:cursor] + text[cursor + 1:]
                    cursor = min(cursor, len(text))
                    first = False
                elif key in (self.c.KEY_HOME, "\x01"):
                    cursor, first = 0, False
                elif key in (self.c.KEY_END, "\x05"):
                    cursor, first = len(text), False
                elif key == self.c.KEY_LEFT:
                    cursor, first = max(0, cursor - 1), False
                elif key == self.c.KEY_RIGHT:
                    cursor, first = min(len(text), cursor + 1), False
                elif isinstance(key, str) and key.isprintable():
                    if first:
                        text, cursor = "", 0
                    text = text[:cursor] + key + text[cursor:]
                    cursor += len(key)
                    first = False
        finally:
            try:
                self.c.curs_set(0)
            except self.c.error:
                pass

    def edit(self, direction=1):
        if self.selected >= len(FIELDS):
            return self.action(ACTIONS[self.selected - len(FIELDS)][0])
        field = FIELDS[self.selected]
        if field.choices:
            value = self.state.values[field.key]
            index = field.choices.index(value) if value in field.choices else -1
            try:
                self.state.set_value(field.key, field.choices[(index + direction) % len(field.choices)])
                self.status, self.status_error = "Updated draft. Press S to save.", False
            except (ValueError, OSError) as error:
                self.message("Invalid value", error)
        else:
            self.edit_number(field)
        return False

    def save(self):
        try:
            changed = self.state.save()
        except (ValueError, OSError) as error:
            self.status, self.status_error = "Save failed; see the validation message.", True
            self.message("Cannot save", error)
            return False
        self.ever_saved |= changed
        self.status = "Saved configuration." if changed else "Configuration unchanged."
        self.status_error = False
        return True

    def action(self, name):
        if name == "optimize":
            self.status, self.status_error = "Optimizing allocation...", False
            self.draw()
            try:
                result = self.state.solve()
            except (ValueError, OSError) as error:
                self.status, self.status_error = "Optimization failed; draft unchanged.", True
                self.message("Cannot optimize", error)
            else:
                alloc = result["allocation"]
                self.status = (f"Optimized draft: IA={alloc['ia_cache_blocks']} Frames={alloc['ps_frame_count']} "
                               f"PS={byte_text(alloc['ps_pool_bytes'])}. Press S to save.")
        elif name == "save":
            self.save()
        elif name == "reload":
            if self.state.dirty and self.confirm("Reload configuration",
                    "Discard draft edits and reload the file?",
                    "[D] Discard and reload  [C] Cancel", "dc") != "d":
                return False
            try:
                self.state.reload()
            except (ValueError, OSError) as error:
                self.message("Cannot reload", error)
            else:
                self.status, self.status_error = "Reloaded configuration from disk.", False
        elif name == "quit":
            if not self.state.dirty:
                return True
            answer = self.confirm("Unsaved changes", "Save changes before exiting?",
                                  "[S] Save and exit  [D] Discard and exit  [C] Cancel", "sdc")
            if answer == "s":
                return self.save()
            if answer == "d":
                self.discarded = True
                return True
        return False

    def help(self):
        paths = "\n\nConfiguration: " + str(self.state.path) + "\nWorkloads: " + self.state.workload_label
        if self.selected < len(FIELDS):
            field = FIELDS[self.selected]
            detail = im2col_cache.help_text(self.state.values[field.key]) if field.key == "IM2COL_CACHE_BYTES" else field.help
            self.message(field.key, detail + "\n\nChanges are kept in memory until Save. "
                         "O runs the capacity solver for the selected workloads and updates the draft. "
                         "For full details, see docs/capacity.md." + paths)
        else:
            self.message("Menuconfig help",
                         "Up/Down or j/k select a setting. Enter edits numbers or cycles a choice. "
                         "Left/Right cycle choices in either direction. O optimizes capacity using "
                         "the selected workloads. S validates and saves. L reloads the file. "
                         "Q exits, offering save/discard/cancel when the draft has changed. "
                         "The capacity solver minimizes device planner service estimates. "
                         "RTL measurements determine task cycles." + paths)

    def run(self):
        count = len(FIELDS) + len(ACTIONS)
        while True:
            large_enough = self.draw()
            key = self._get_key(self.screen)
            if key == self.c.KEY_RESIZE:
                continue
            if key in ("q", "Q", "\x1b"):
                if self.action("quit"):
                    break
            elif not large_enough:
                continue
            elif key in (self.c.KEY_DOWN, "j", "\t"):
                self.selected = (self.selected + 1) % count
            elif key in (self.c.KEY_UP, "k", self.c.KEY_BTAB):
                self.selected = (self.selected - 1) % count
            elif key == self.c.KEY_NPAGE:
                self.selected = min(count - 1, self.selected + max(1, self.screen.getmaxyx()[0] - 14))
            elif key == self.c.KEY_PPAGE:
                self.selected = max(0, self.selected - max(1, self.screen.getmaxyx()[0] - 14))
            elif key == self.c.KEY_HOME:
                self.selected = 0
            elif key == self.c.KEY_END:
                self.selected = count - 1
            elif key in ("\n", "\r", " ", self.c.KEY_ENTER, self.c.KEY_RIGHT):
                if self.edit():
                    break
            elif key == self.c.KEY_LEFT:
                if self.selected < len(FIELDS) and FIELDS[self.selected].choices:
                    self.edit(-1)
            elif isinstance(key, str) and key.lower() in ("o", "s", "l"):
                self.action({"o": "optimize", "s": "save", "l": "reload"}[key.lower()])
            elif key in ("?", "h", "H", self.c.KEY_F1):
                self.help()
            elif key == "\x0c":
                self.screen.clearok(True)
        message = f"Saved configuration: {self.state.path}" if self.ever_saved else "No configuration changes saved."
        if self.discarded:
            message += " Unsaved draft changes discarded."
        return message


def shape_argument(text):
    try:
        values = [int(part) for part in text.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("shape must contain M,K,N integers") from error
    if len(values) != 3:
        raise argparse.ArgumentTypeError("shape must contain exactly M,K,N")
    return dict(zip(("M", "K", "N"), values))


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("NPU_CONFIG", ROOT / "config/npu.mk")))
    parser.add_argument("--output", type=Path, default=ROOT / "build/capacity/solution.json",
                        help="solution JSON destination when an optimized draft is saved")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="load a literal override into the draft")
    tasks = parser.add_mutually_exclusive_group()
    tasks.add_argument("--shape", action="append", type=shape_argument, metavar="M,K,N")
    tasks.add_argument("--workloads", type=Path)
    budgets = parser.add_mutually_exclusive_group()
    budgets.add_argument("--max-ram-kib", type=int, help="initial complete buffer RAM limit")
    budgets.add_argument("--max-state-kib", type=int, help="initial complete logical-state limit")
    budgets.add_argument("--budget-kib", type=int, help="initial limit in the selected scope")
    parser.add_argument("--budget-scope", choices=model.SCOPES)
    parser.add_argument("--representation", choices=model.REPRESENTATIONS)
    parser.add_argument("--verilator", default="verilator")
    return parser


def main(argv=None):
    parser = argument_parser()
    args = parser.parse_args(argv)
    if args.budget_scope is not None and (args.max_ram_kib is not None or args.max_state_kib is not None):
        parser.error("--budget-scope cannot be combined with --max-ram-kib or --max-state-kib")
    amount = next((value for value in (args.max_ram_kib, args.max_state_kib, args.budget_kib)
                   if value is not None), None)
    if amount is not None and amount <= 0:
        parser.error("capacity must be positive KiB")
    scope = ("buffer-ram" if args.max_ram_kib is not None else
             "logical-state" if args.max_state_kib is not None else args.budget_scope)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.exit(2, "menuconfig requires an interactive terminal. Run 'make menuconfig' "
                    "directly in a terminal, or use 'make capacity-solve' for batch configuration.\n")
    try:
        import curses
    except ImportError:
        parser.exit(2, "menuconfig requires Python's curses module. Install your platform's Python "
                    "curses support, or use 'make capacity-solve'.\n")
    try:
        curses.setupterm()
        if not curses.tigetstr("cup"):
            parser.exit(2, "menuconfig requires a cursor-addressable terminal. Check TERM "
                        "and run it in a normal terminal emulator.\n")
        from scripts.capacity.menuconfig_state import MenuConfigState
        state = MenuConfigState(args.config, overrides=args.set,
                               workloads_path=args.workloads, shapes=args.shape, output_path=args.output,
                               budget_bytes=None if amount is None else amount * 1024,
                               budget_scope=scope, representation=args.representation, verilator=args.verilator)
        try:
            locale.setlocale(locale.LC_ALL, "")
        except locale.Error:
            pass
        message = curses.wrapper(lambda screen: TerminalMenu(screen, state, curses).run())
        print(message)
        return 0
    except KeyboardInterrupt:
        print("\nmenuconfig interrupted. Only explicitly saved changes were written.", file=sys.stderr)
        return 130
    except curses.error as error:
        parser.exit(2, f"menuconfig could not initialize or update the terminal: {error}. "
                    "Check TERM and use an interactive terminal.\n")
    except (ValueError, OSError) as error:
        parser.exit(2, f"menuconfig: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
