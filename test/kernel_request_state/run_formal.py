#!/usr/bin/env python3
"""运行待发资格归纳证明及完整加载器状态对应证明。"""
import argparse
import contextlib
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TEST = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextlib.contextmanager
def acquire(path):
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
    parser.add_argument("--reference", default="cfcc1a95")
    parser.add_argument("--profiles", nargs="+", default=("16:29:64",))
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = args.reference_root.resolve() if args.reference_root else out / "reference"
    if args.reference_root is None:
        for name in ("kernel_loader.sv", "kernel_loader_ctrl.sv", "kernel_loader_buffer.sv"):
            relative = Path("rtl/npu/loaders") / name
            target = reference / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(["git", "show", f"{args.reference}:{relative}"], cwd=ROOT))
        shutil.copytree(source / "rtl/common", reference / "rtl/common", dirs_exist_ok=True)

    def run(name, arguments, log):
        with acquire(args.lock_file):
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(TEST / name), *map(str, arguments)],
                               stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=240)

    invariant = out / "invariant"
    run("prove_invariant.py", ["--source-root", source, "--out", invariant], out / "invariant.log")
    profiles = []
    for profile in args.profiles:
        size, count, bus = map(int, profile.split(":"))
        folder = out / profile.replace(":", "_")
        folder.mkdir(exist_ok=True)
        models, proof = folder / "models", folder / "symbolic"
        run("prepare_models.py", ["--source-root", source, "--reference-root", reference,
                                 "--size", size, "--count-width", count, "--bus-width", bus,
                                 "--out", models], folder / "prepare.log")
        run("prove_symbolic.py", ["--models", models, "--invariant", invariant / "summary.json",
                                 "--out", proof], folder / "symbolic.log")
        report = json.loads((proof / "summary.json").read_text())
        if not report["passed"]:
            raise RuntimeError("状态转换证明未完成")
        profiles.append(dict(profile=profile, passed=True, common_state_bits=report["common_state_bits"],
                             additional_state_bits=report["additional_state_bits"],
                             reset_state_bits=report["async_reset_values_compared"],
                             unreset_state_bits=report["unreset_shared_state_bits"],
                             report=str(proof / "summary.json"), report_sha256=digest(proof / "summary.json")))
        print(json.dumps(profiles[-1]), flush=True)
    report = dict(passed=True, profiles=profiles, invariant_report=str(invariant / "summary.json"),
                  invariant_report_sha256=digest(invariant / "summary.json"),
                  all_reference_state_bits_and_public_outputs=True, external_inputs_constrained=False)
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
