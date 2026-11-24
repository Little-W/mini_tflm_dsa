#!/usr/bin/env python3
"""Exercise RSS sampling for children launched by worker threads."""
import json
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest

from open_fpga_synth import process_tree_rss


WORKER = r'''
import json, os, queue, subprocess, sys, threading
memory = bytearray(16 * 1024 * 1024)
for index in range(0, len(memory), 4096): memory[index] = 1
ready, done = queue.Queue(), threading.Event()
child_code = """
import os, sys
memory = bytearray(24 * 1024 * 1024)
for index in range(0, len(memory), 4096): memory[index] = 1
print(os.getpid(), flush=True)
sys.stdin.readline()
"""
def work():
    child = subprocess.Popen([sys.executable, '-u', '-c', child_code],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    ready.put(int(child.stdout.readline()))
    done.wait(10)
    child.communicate('\n', timeout=5)
thread = threading.Thread(target=work)
thread.start()
print(json.dumps(dict(parent=os.getpid(), child=ready.get(timeout=5))), flush=True)
sys.stdin.readline()
done.set()
thread.join()
'''


class ProcessTreeRssTests(unittest.TestCase):
    def test_status_parent_relationships_include_all_descendants(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for pid, parent, kb in ((100, 1, 1000), (200, 100, 2000),
                                    (300, 200, 3000), (400, 1, 4000)):
                path = root / str(pid)
                path.mkdir()
                (path / 'status').write_text(f'Name:\ttest\nPPid:\t{parent}\nVmRSS:\t{kb} kB\n')
            (root / 'self').mkdir()
            self.assertEqual(process_tree_rss(100, proc_root=root), 6000 * 1024)
            self.assertEqual(process_tree_rss(200, proc_root=root), 5000 * 1024)
            self.assertEqual(process_tree_rss(999, proc_root=root), 0)

    def test_child_started_by_non_main_thread_is_counted(self):
        process = subprocess.Popen([sys.executable, '-u', '-c', WORKER],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            available, _, _ = select.select([process.stdout], [], [], 8)
            self.assertTrue(available, 'Worker did not report allocated memory')
            ids = json.loads(process.stdout.readline())
            main_children = Path(f'/proc/{ids["parent"]}/task/{ids["parent"]}/children')
            if main_children.exists():
                self.assertNotIn(str(ids['child']), main_children.read_text().split())
            child_rss = process_tree_rss(ids['child'])
            tree_rss = process_tree_rss(ids['parent'])
            self.assertGreaterEqual(child_rss, 24 * 1024 * 1024)
            self.assertGreaterEqual(tree_rss, child_rss + 16 * 1024 * 1024)
            print(json.dumps(dict(parent_pid=ids['parent'], child_pid=ids['child'],
                                  child_rss_bytes=child_rss, process_tree_rss_bytes=tree_rss,
                                  task_children_api_available=main_children.exists())))
            process.communicate('\n', timeout=8)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
