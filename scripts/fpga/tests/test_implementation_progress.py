#!/usr/bin/env python3
"""检查子进程运行资源及终止状态均写入可恢复的阶段记录。"""
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_fpga_implementation import run_command


class ProgressTest(unittest.TestCase):
    def test_successful_process_records_memory_and_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            command = [sys.executable, '-c', 'import time; data=bytearray(4*1024*1024); time.sleep(0.5)']
            result = run_command(command, folder, 'execute', os.environ.copy())
            saved = json.loads((folder / 'execute.progress.json').read_text())
            self.assertEqual(result, saved)
            self.assertEqual(saved['state'], 'complete')
            self.assertEqual(saved['return_code'], 0)
            self.assertGreater(saved['peak_process_tree_rss_bytes'], 4 * 1024 * 1024)
            self.assertEqual(saved['current_process_tree_rss_bytes'], 0)
            self.assertFalse((folder / 'execute.progress.json.tmp').exists())

    def test_signal_exit_keeps_resource_record(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            command = [sys.executable, '-c',
                       'import os,signal,time; data=bytearray(4*1024*1024); time.sleep(0.5); os.kill(os.getpid(),signal.SIGKILL)']
            with self.assertRaises(RuntimeError):
                run_command(command, folder, 'execute', os.environ.copy())
            saved = json.loads((folder / 'execute.progress.json').read_text())
            self.assertEqual(saved['state'], 'failed')
            self.assertEqual(saved['return_code'], -signal.SIGKILL)
            self.assertGreater(saved['peak_process_tree_rss_bytes'], 4 * 1024 * 1024)
            self.assertEqual(saved['command'], command)


if __name__ == '__main__':
    unittest.main()
