#!/usr/bin/env python3
"""Configuration transaction and real terminal tests for make menuconfig.

The PTY tests send normal user keystrokes through GNU Make to the curses UI.
They use only the standard library and temporary configurations, never the
checked-in npu.mk. No RTL rebuild is needed for configuration editing.
"""
from __future__ import annotations

import errno
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from capacity import config  # noqa: E402
from capacity.menuconfig_state import MenuConfigState  # noqa: E402

MENU = ROOT / "scripts/capacity/menuconfig.py"
MAKE = shutil.which("make")
CONFIG_TEXT = ("# Keep this configuration comment.\n" +
               "\n".join(f"{key} ?= {value}" for key, value in config.DEFAULTS.items()) +
               "\nUSER_CLOCK_MHZ ?= 50  # Keep this custom value.\n")


def clean_environment():
    env = os.environ.copy()
    # The outer make capacity-test exports these; nested Make probes must have
    # their own isolated command-line and configuration context.
    for name in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS", "NPU_CONFIG",
                 "NPU_CONFIG_INCLUDED", "CONFIG", *config.DEFAULTS):
        env.pop(name, None)
    return env


class ConfigurationFixture(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ, clean_environment(), clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        temporary = tempfile.TemporaryDirectory(prefix="gempact-menuconfig-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "npu.mk"
        self.path.write_text(CONFIG_TEXT)
        self.output = self.directory / "solution.json"

    def state(self, **kwargs):
        return MenuConfigState(self.path, output_path=self.output, **kwargs)

    def stamp(self):
        return self.path.read_bytes(), self.path.stat().st_mtime_ns


class MenuStateTests(ConfigurationFixture):
    def test_loading_and_leaving_draft_does_not_write(self):
        before = self.stamp()
        state = self.state()
        self.assertFalse(state.dirty)
        self.assertEqual(state.values, config.DEFAULTS)
        summary = state.capacity_summary()
        self.assertTrue(summary["active"])
        self.assertIsNotNone(summary["allocation"])
        state.set_value("IA_CACHE_BLOCKS", "8")
        self.assertTrue(state.dirty)
        self.assertEqual(self.stamp(), before)

    def test_byte_units_and_related_settings(self):
        state = self.state()
        for text, expected in (("128 KiB", 131072), ("1.5 MiB", 1572864),
                               ("32k", 32768), ("0x8000", 32768), ("4096 B", 4096)):
            with self.subTest(text=text):
                state.set_value("CAPACITY_BUDGET_BYTES", text)
                self.assertEqual(state.values["CAPACITY_BUDGET_BYTES"], expected)
        state.set_value("PS_POOL_BYTES", "9.25 KiB")
        self.assertEqual(state.values["PS_POOL_BYTES"], 9472)
        state.set_value("PCR_ENGINE", "1")
        self.assertEqual(state.values["SIZE"], 16)
        state.set_value("CAPACITY_REPRESENTATION", "raw32")
        self.assertEqual(state.values["PS_FORCE_RAW"], 1)
        state.set_value("PS_FORCE_RAW", "0")
        self.assertEqual(state.values["CAPACITY_REPRESENTATION"], "adaptive")

    def test_full_configuration_save_preserves_custom_content(self):
        state = self.state()
        edits = {"PCR_ENGINE": 1, "SIZE": 16, "PS_POOL_BYTES": "9.25 KiB",
                 "CAPACITY_BUDGET_BYTES": "128 KiB", "CAPACITY_BUDGET_SCOPE": "buffer-ram",
                 "CAPACITY_REPRESENTATION": "raw32", "IA_CACHE_BLOCKS": 8,
                 "PS_FRAME_COUNT": 25, "AXI_READ_OUTSTANDING": 8,
                 "NPU_AXI_DATA_WIDTH": 32, "SHARED_BANK_BYTES": "4 KiB", "SHARED_BANK_COUNT": 9}
        for key, value in edits.items():
            state.set_value(key, value)
        self.assertTrue(state.save())
        actual = config.read_config(self.path)
        self.assertEqual(actual, state.values)
        self.assertEqual(actual["PS_FORCE_RAW"], 1)
        self.assertIn("# Keep this configuration comment.", self.path.read_text())
        self.assertIn("USER_CLOCK_MHZ ?= 50  # Keep this custom value.", self.path.read_text())
        self.assertFalse(state.dirty)
        before = self.stamp()
        self.assertFalse(state.save())
        self.assertEqual(self.stamp(), before)

    def test_invalid_field_edits_leave_draft_and_file_unchanged(self):
        state = self.state()
        before = self.stamp()
        invalid = (("IA_CACHE_BLOCKS", "3"), ("PS_FRAME_COUNT", "0"),
                   ("PS_POOL_BYTES", "1025"), ("PS_POOL_BYTES", "1.1 B"),
                   ("PCR_ENGINE", "2"), ("SIZE", "3"),
                   ("NPU_AXI_DATA_WIDTH", "128"), ("SHARED_BANK_BYTES", "3 KiB"),
                   ("SHARED_BANK_COUNT", "5"), ("SHARED_BANK_COUNT", "10"),
                   ("NPU_AXI_DATA_WIDTH", True), ("SHARED_BANK_COUNT", True),
                   ("CAPACITY_BUDGET_BYTES", "0"),
                   ("CAPACITY_BUDGET_BYTES", "$(shell echo 32768)"),
                   ("CAPACITY_BUDGET_SCOPE", "unknown"), ("UNKNOWN_KEY", "1"))
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                draft = dict(state.values)
                with self.assertRaises(ValueError):
                    state.set_value(key, value)
                self.assertEqual(state.values, draft)
                self.assertEqual(self.stamp(), before)

    def test_overbudget_draft_is_visible_but_cannot_be_saved(self):
        state = self.state()
        before = self.stamp()
        state.set_value("PCR_ENGINE", 1)
        state.set_value("CAPACITY_BUDGET_BYTES", "1 KiB")
        summary = state.capacity_summary()
        self.assertTrue(summary["active"])
        self.assertLess(summary["allocation"]["unused_budget_bytes"], 0)
        self.assertTrue(summary["validation_error"])
        with self.assertRaises(ValueError):
            state.validate()
        with self.assertRaises(ValueError):
            state.save()
        self.assertEqual(self.stamp(), before)
        self.assertFalse(self.output.exists())

    def test_optimizer_changes_only_draft_until_save(self):
        state = self.state(budget_bytes=49152, budget_scope="buffer-ram")
        before = self.stamp()
        result = state.solve()
        a = result["allocation"]
        self.assertLessEqual(a["buffer_ram_bytes"], 49152)
        self.assertEqual(a["ps_pool_bytes"] % 64, 0)
        self.assertEqual(state.values["PCR_ENGINE"], 1)
        self.assertEqual(state.values["SIZE"], 16)
        self.assertEqual(state.values["PS_POOL_BYTES"], a["ps_pool_bytes"])
        self.assertEqual(state.values["SHARED_BANK_BYTES"], a["shared_bank_bytes"])
        self.assertEqual(state.values["SHARED_BANK_COUNT"], a["shared_physical_bank_count"])
        self.assertEqual(self.stamp(), before)
        self.assertFalse(self.output.exists())
        self.assertTrue(state.dirty)
        state.save()
        self.assertEqual(config.read_config(self.path), state.values)
        report = json.loads(self.output.read_text())
        self.assertEqual(report["allocation"], result["allocation"])

    def test_failed_optimizer_leaves_draft_and_files_unchanged(self):
        state = self.state(budget_bytes=1024, budget_scope="buffer-ram")
        before = self.stamp()
        draft = dict(state.values)
        with self.assertRaises(ValueError):
            state.solve()
        self.assertEqual(state.values, draft)
        self.assertEqual(self.stamp(), before)
        self.assertFalse(self.output.exists())

    def test_external_edits_require_reload_before_saving(self):
        state = self.state()
        state.set_value("IA_CACHE_BLOCKS", 8)
        self.path.write_text(self.path.read_text().replace("AXI_READ_OUTSTANDING ?= 4",
                                                         "AXI_READ_OUTSTANDING ?= 6"))
        external = self.stamp()
        with self.assertRaises(ValueError):
            state.save()
        self.assertEqual(self.stamp(), external)
        state.reload()
        self.assertFalse(state.dirty)
        self.assertEqual(state.values["AXI_READ_OUTSTANDING"], 6)
        self.assertEqual(state.values["IA_CACHE_BLOCKS"], 4)

    def test_missing_file_is_created_only_when_saved(self):
        path = self.directory / "new" / "profile.mk"
        state = MenuConfigState(path)
        self.assertTrue(state.dirty)
        self.assertFalse(path.exists())
        state.save()
        self.assertEqual(config.read_config(path), config.DEFAULTS)

    def test_partial_file_and_explicit_overrides_are_editable(self):
        self.path.write_text("# Partial configuration\nPCR_ENGINE ?= 0\n")
        state = self.state(overrides=["PS_FRAME_COUNT=16", "IA_CACHE_BLOCKS=8",
                                      "CAPACITY_BUDGET_BYTES=262144"])
        self.assertTrue(state.dirty)
        self.assertEqual(state.values["PS_FRAME_COUNT"], 16)
        state.save()
        self.assertEqual(set(config.read_config(self.path)), set(config.DEFAULTS))
        self.assertEqual(config.read_config(self.path)["IA_CACHE_BLOCKS"], 8)
        self.assertEqual(config.read_config(self.path)["CAPACITY_BUDGET_BYTES"], 262144)


class MenuCliTests(ConfigurationFixture):
    def test_help_does_not_require_a_terminal_or_import_curses(self):
        fake_modules = self.directory / "modules"
        fake_modules.mkdir()
        (fake_modules / "curses.py").write_text("raise ImportError('deliberately unavailable')\n")
        env = clean_environment()
        env["PYTHONPATH"] = str(fake_modules)
        result = subprocess.run([sys.executable, str(MENU), "--help"], env=env,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--config", result.stdout)

    def test_noninteractive_invocation_is_actionable_and_readonly(self):
        before = self.stamp()
        result = subprocess.run([sys.executable, str(MENU), "--config", str(self.path)],
                                text=True, capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stdout + result.stderr, r"(?i)(interactive|tty|terminal)")
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.stamp(), before)


@unittest.skipUnless(MAKE, "GNU Make is unavailable")
class MenuMakeTests(ConfigurationFixture):
    def make(self, *args, cwd=ROOT):
        return subprocess.run([MAKE, "--no-print-directory", *map(str, args)], cwd=cwd,
                              env=clean_environment(), text=True, capture_output=True, timeout=15)

    def test_all_entry_points_load_the_selected_file(self):
        for cwd in (ROOT, ROOT / "veri/sim", ROOT / "asic", ROOT / "asic/synthesis"):
            with self.subTest(cwd=str(cwd)):
                run = self.make("-n", "menuconfig", f"NPU_CONFIG={self.path}", cwd=cwd)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn(str(self.path), run.stdout)
                self.assertIn("menuconfig.py", run.stdout)
                self.assertNotRegex(run.stdout, r"--set\s+['\"]?SIZE=")

    def test_explicit_values_and_budget_are_forwarded(self):
        run = self.make("-n", "menuconfig", f"NPU_CONFIG={self.path}", "IA_CACHE_BLOCKS=8",
                        "SIZE=16", "MAX_RAM_KIB=64", "REPRESENTATION=raw32",
                        "NPU_AXI_DATA_WIDTH=32", "SHARED_BANK_BYTES=8192", "SHARED_BANK_COUNT=6")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        for text in ("IA_CACHE_BLOCKS=8", "SIZE=16", "--max-ram-kib", "--representation", "raw32",
                     "NPU_AXI_DATA_WIDTH=32", "SHARED_BANK_BYTES=8192", "SHARED_BANK_COUNT=6"):
            self.assertIn(text, run.stdout)

    def test_missing_profile_can_be_opened_for_creation(self):
        path = self.directory / "new.mk"
        run = self.make("-n", "menuconfig", f"NPU_CONFIG={path}")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse(path.exists())

    def test_mixed_goals_and_conflicting_budgets_are_rejected(self):
        before = self.stamp()
        for args in (("-j2", "menuconfig", "capacity-show"),
                     ("menuconfig", "vcs-top"),
                     ("menuconfig", "MAX_RAM_KIB=32", "MAX_STATE_KIB=32")):
            with self.subTest(args=args):
                run = self.make(*args, f"NPU_CONFIG={self.path}")
                self.assertNotEqual(run.returncode, 0)
                self.assertNotIn("Traceback", run.stderr)
                self.assertEqual(self.stamp(), before)


class TerminalSession:
    """Small standard-library PTY harness with bounded waits and cleanup."""
    def __init__(self, command, *, cwd, log_path):
        import fcntl
        import pty
        import termios
        self.fcntl, self.termios = fcntl, termios
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        env = clean_environment()
        env["TERM"] = "xterm"
        env.pop("LINES", None)
        env.pop("COLUMNS", None)

        def controlling_terminal():
            # A real terminal owns a session and foreground process group.
            # Merely connecting an otherwise detached subprocess to a PTY can
            # make ncurses ignore SIGWINCH on some platforms.
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=slave,
                                        stdout=slave, stderr=slave,
                                        preexec_fn=controlling_terminal)
        os.close(slave)
        self.data, self.position = bytearray(), 0
        self.log_path = log_path

    def read(self, timeout=0.05):
        if select.select([self.master], [], [], timeout)[0]:
            try:
                chunk = os.read(self.master, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                return False
            self.data.extend(chunk)
            return bool(chunk)
        return False

    def expect(self, text, timeout=15):
        needle = text.encode()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.data.find(needle, self.position)
            if found >= 0:
                self.position = found + len(needle)
                return
            if self.process.poll() is not None and not self.read(0):
                break
            self.read()
        tail = bytes(self.data[-3000:]).decode(errors="replace")
        raise AssertionError(f"Terminal did not show {text!r}; output tail:\n{tail}")

    def send(self, text):
        os.write(self.master, text.encode())

    def resize(self, rows, columns):
        self.fcntl.ioctl(self.master, self.termios.TIOCSWINSZ,
                         struct.pack("HHHH", rows, columns, 0, 0))
        os.killpg(self.process.pid, signal.SIGWINCH)

    def finish(self, timeout=15):
        deadline = time.monotonic() + timeout
        while self.process.poll() is None and time.monotonic() < deadline:
            self.read()
        if self.process.poll() is None:
            raise AssertionError("Terminal menu did not exit")
        while self.read(0):
            pass
        return self.process.returncode

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=3)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_bytes(self.data)
        os.close(self.master)


@unittest.skipUnless(os.name == "posix" and MAKE and importlib.util.find_spec("curses"),
                     "POSIX PTY, GNU Make and curses are required")
class MenuTerminalTests(ConfigurationFixture):
    def terminal(self, label):
        log_path = ROOT / "build/capacity/menuconfig" / f"{label}.pty.log"
        command = [MAKE, "--no-print-directory", "menuconfig", f"NPU_CONFIG={self.path}",
                   f"CAPACITY_OUTPUT={self.output}"]
        terminal = TerminalSession(command, cwd=ROOT, log_path=log_path)
        self.addCleanup(terminal.close)
        terminal.expect("PgUp/PgDn Scroll")
        return terminal

    def test_real_make_terminal_edit_optimize_save_and_quit(self):
        before = self.stamp()
        terminal = self.terminal("edit_solve_save")
        terminal.send("jjj\n")
        terminal.expect("Edit CAPACITY_BUDGET_BYTES")
        terminal.send("\x1548 KiB\n")
        terminal.send("o")
        # Ncurses may retain the "Optimiz" prefix of "Optimizing..." and
        # emit only the changed suffix; match the newly drawn result text.
        terminal.expect("draft: IA=")
        self.assertEqual(self.stamp(), before)
        self.assertFalse(self.output.exists())
        terminal.send("q")
        terminal.expect("Unsaved changes")
        terminal.send("c")
        terminal.send("s")
        terminal.expect("Saved configuration.")
        terminal.send("q")
        self.assertEqual(terminal.finish(), 0)
        values = config.read_config(self.path)
        self.assertEqual((values["PCR_ENGINE"], values["SIZE"], values["CAPACITY_BUDGET_BYTES"]),
                         (1, 16, 49152))
        self.assertIn(values["IA_CACHE_BLOCKS"], (2, 4, 8, 16))
        self.assertIn(values["PS_FRAME_COUNT"], (4, 8, 16, 25))
        self.assertEqual(values["PS_POOL_BYTES"] % 64, 0)
        self.assertTrue(self.output.is_file())

    def test_real_terminal_invalid_save_and_discard(self):
        state = self.state(budget_bytes=49152)
        state.solve()
        state.save()
        before = self.stamp()
        terminal = self.terminal("invalid_save_discard")
        terminal.send("jjj\n")
        terminal.expect("Edit CAPACITY_BUDGET_BYTES")
        terminal.send("\x151 KiB\n")
        terminal.send("s")
        terminal.expect("Cannot save")
        self.assertEqual(self.stamp(), before)
        terminal.send("\nq")
        terminal.expect("Unsaved changes")
        terminal.send("d")
        self.assertEqual(terminal.finish(), 0)
        self.assertEqual(self.stamp(), before)

    def test_real_terminal_resize_and_clean_exit(self):
        before = self.stamp()
        terminal = self.terminal("resize_no_changes")
        terminal.resize(8, 40)
        terminal.expect("Terminal too small")
        terminal.resize(24, 80)
        terminal.expect("Shared data: 14 KiB")
        terminal.send("q")
        self.assertEqual(terminal.finish(), 0)
        self.assertEqual(self.stamp(), before)


if __name__ == "__main__":
    unittest.main()
