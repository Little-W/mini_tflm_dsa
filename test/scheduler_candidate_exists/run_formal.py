#!/usr/bin/env python3
"""验证候选存在性保存关系及全部公共寄存器与输出的逐周期对应关系。"""
import argparse
import contextlib
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
TEST = Path(__file__).resolve().parent
RTL = Path("rtl/npu/control/ps_window_scheduler.sv")
PROFILES = ("4:4:4", "16:16:32", "4:2:0", "8:4:1", "16:8:16")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextlib.contextmanager
def synthesis_lock(path):
    if path is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference", default="9d75f75a")
    parser.add_argument("--profiles", nargs="+", default=PROFILES)
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = args.reference_root.resolve() if args.reference_root else out / "reference"
    if args.reference_root is None:
        (reference / RTL).parent.mkdir(parents=True, exist_ok=True)
        (reference / RTL).write_bytes(subprocess.check_output(
            ["git", "show", f"{args.reference}:{RTL}"], cwd=ROOT))
        shutil.copytree(source / "rtl/common", reference / "rtl/common", dirs_exist_ok=True)
    source_files = [source / RTL, reference / RTL]
    for folder in (source, reference):
        source_files.extend(sorted(path for path in (folder / "rtl/common").glob("*")
                                   if path.suffix in (".sv", ".v")))
    source_hashes = {str(path): digest(path) for path in source_files}
    profiles = []
    for profile in args.profiles:
        size, frames, reuse = map(int, profile.split(":"))
        folder = out / profile.replace(":", "_")
        folder.mkdir(exist_ok=True)
        reports = {}
        for name, script in (("invariant", "prove_invariant.py"),
                             ("transition", "prove_transition.py")):
            result = folder / name
            command = [sys.executable, str(TEST / script), "--source-root", str(source),
                       "--profiles", profile, "--out", str(result)]
            if name == "transition":
                command.extend(("--reference-root", str(reference)))
            log = folder / (name + ".log")
            with synthesis_lock(args.lock_file):
                with log.open("w") as stream:
                    subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                   check=True, timeout=250)
            reports[name] = json.loads((result / "summary.json").read_text())
            if not reports[name]["passed"]:
                raise RuntimeError(f"证明未完成：{result}")
            time.sleep(0.2)
        state = reports["transition"]["profiles"][0]
        group_path = folder / "transition" / profile.replace(":", "_") / "groups.json"
        groups = json.loads(group_path.read_text())
        covered = [bit for group in groups["groups"]
                   for bit in range(group["first_bit"], group["last_bit"] + 1)]
        if covered != list(range(state["common_state_bits"])):
            raise RuntimeError("公共寄存器状态覆盖范围不完整")
        item = {
            "parameters": {"SIZE": size, "FRAME_COUNT": frames, "MAX_REUSE_TILES": reuse},
            "passed": True, "common_state_bits": state["common_state_bits"],
            "added_state_bits": state["added_state_bits"],
            "transition_groups": len(groups["groups"]),
            "invariant_report": str(folder / "invariant/summary.json"),
            "transition_report": str(folder / "transition/summary.json"),
            "group_report_sha256": digest(group_path),
        }
        profiles.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    if source_hashes != {str(path): digest(path) for path in source_files}:
        raise RuntimeError("验证期间源文件发生变化")
    report = {
        "passed": True, "source_sha256": source_hashes, "profiles": profiles,
        "common_state_bits": sum(item["common_state_bits"] for item in profiles),
        "unconstrained_external_inputs": True,
        "all_common_register_bits_and_public_outputs": True,
        "verification": "复位检查、独立不变量的一步无界归纳、公共状态对应下的全部输出与分组状态转移",
    }
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
