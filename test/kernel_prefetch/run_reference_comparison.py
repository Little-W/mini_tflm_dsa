#!/usr/bin/env python3
"""使用独立历史 RTL，每周期比较内核加载器的全部公开输出。"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[2]
TOP = "kernel_loader"


def split_values(text):
    start, depth, values = 0, 0, []
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            values.append(text[start:index].strip())
            start = index + 1
    values.append(text[start:].strip())
    return values


def prepare_reference(revision, out):
    revision = subprocess.check_output(
        ["git", "rev-parse", revision + "^{commit}"], cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(["git", "archive", revision, "rtl"], cwd=ROOT)
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    parts, names, hashes = [], {}, {}
    with tempfile.TemporaryDirectory() as temporary:
        source_root = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
            source.extractall(source_root, filter="data")
        for path in resolve([source_root / "rtl/npu/loaders/kernel_loader.sv"], source_root):
            relative = str(path.relative_to(source_root))
            content = path.read_text()
            parts.append((relative, content))
            hashes[relative] = hashlib.sha256(content.encode()).hexdigest()
            code = re.sub(r"//[^\n]*|/\*.*?\*/", " ", content, flags=re.S)
            for name in re.findall(r"\b(?:module|package)\s+(\w+)\b", code):
                names[name] = "kernel_ref__" + name
    identifiers = re.compile(r"\b(" + "|".join(sorted(names, key=len, reverse=True)) + r")\b")
    reference = "\n".join(identifiers.sub(lambda match: names[match.group()], content)
                           for _, content in parts)
    reference_file = out / "kernel_loader_reference.sv"
    reference_file.write_text(reference)

    current = (ROOT / "rtl/npu/loaders/kernel_loader.sv").read_text()
    header_pattern = r"module kernel_loader\s*#\((.*?)\)\s*\((.*?)\n\);"
    declaration = re.search(header_pattern, current, re.S)
    if declaration is None:
        raise ValueError("无法读取内核加载器公开接口")
    parameters, header = declaration.groups()
    header = re.sub(r"//[^\n]*|/\*.*?\*/", " ", header, flags=re.S)
    original = next(content for relative, content in parts
                    if relative == "rtl/npu/loaders/kernel_loader.sv")
    original_header = re.search(header_pattern, original, re.S)[2]
    original_header = re.sub(r"//[^\n]*|/\*.*?\*/", " ", original_header, flags=re.S)
    if re.sub(r"\s+", "", header) != re.sub(r"\s+", "", original_header):
        raise ValueError("参考设计和待测设计的公开接口不同")
    parameter_names = re.findall(r"parameter\s+int\s+(?:unsigned\s+)?(\w+)", parameters)
    declarations = list(re.finditer(
        r"\b(input|output)\s+(?:wire\s+)?(logic(?:\s+signed)?(?:\s*\[[^\]]+\])*)\s+"
        r"(.+?)(?=,\s*(?:input|output)\b|\Z)", header.strip(), re.S))
    if len(declarations) != len(re.findall(r"\b(?:input|output)\b", header)):
        raise ValueError("公开端口包含无法读取的声明")
    ports = []
    for match in declarations:
        direction, dtype, values = match.groups()
        for value in split_values(values.strip().rstrip(",")):
            variable = re.fullmatch(r"(\w+)(\s*(?:\[[^\]]+\]\s*)*)(?:\s*=.*)?", value, re.S)
            if variable is None:
                raise ValueError("无法读取公开端口：" + value)
            ports.append((direction, dtype, variable[1], variable[2].strip()))
    observer = ["// 两个加载器接收相同输入，历史模块与当前模块使用独立定义。\n",
                "module kernel_loader_equivalence_observer #(\n", parameters, ") ();\n",
                "  longint unsigned cycles = 0;\n"]
    for direction, dtype, name, dimensions in ports:
        if direction == "output":
            observer.append(f"  {dtype} reference_{name} {dimensions};\n")
    observer.append("  kernel_ref__kernel_loader #(\n")
    observer.append(",\n".join(f"    .{name}({name})" for name in parameter_names))
    observer.append("\n  ) reference_loader (\n")
    observer.append(",\n".join(
        f"    .{name}({'reference_' + name if direction == 'output' else TOP + '.' + name})"
        for direction, _, name, _ in ports))
    observer.append("\n  );\n  always @(negedge kernel_loader.clk) if (kernel_loader.rst_n) begin\n")
    observer.append("    cycles <= cycles + 1;\n")
    outputs = 0
    for direction, _, name, dimensions in ports:
        if direction != "output":
            continue
        outputs += 1
        suffix = ""
        for index, length in enumerate(re.findall(r"\[([^\]]+)\]", dimensions)):
            observer.append(f"    for (int item{index}=0; item{index}<{length}; item{index}++)\n")
            suffix += f"[item{index}]"
        observer.append(f"    assert (reference_{name}{suffix} === kernel_loader.{name}{suffix})\n"
                        f'      else $fatal(1, "内核加载器输出不一致：{name}，周期 %0d", cycles);\n')
    observer.append("  end\n")
    observer.append(f'  final $display("KERNEL_LOADER_EQUIVALENCE_PASS cycles=%0d output_ports={outputs}", cycles);\n')
    observer.append("endmodule\n\nbind kernel_loader kernel_loader_equivalence_observer #(\n")
    observer.append(",\n".join(f"  .{name}({name})" for name in parameter_names))
    observer.append("\n) u_cycle_comparison ();\n")
    observer_file = out / "kernel_loader_equivalence_observer.sv"
    observer_file.write_text("".join(observer))
    manifest = dict(revision=revision, source_sha256=hashes, definition_names=names,
                    reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                    public_ports=len(ports), compared_output_ports=outputs)
    (out / "reference_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return reference_file, observer_file, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="2247144937c2")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bus-width", type=int, choices=(32, 64, 128), default=64)
    parser.add_argument("--count-width", type=int, default=16)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference, observer, manifest = prepare_reference(args.reference, out)
    command = [sys.executable, str(ROOT / "test/kernel_prefetch/run.py"), "--out", str(out),
               "--bus-width", str(args.bus_width), "--count-width", str(args.count_width),
               "--verilator", args.verilator, "--extra-source", str(reference), "--extra-source", str(observer)]
    subprocess.run(command, cwd=ROOT, check=True)
    match = re.search(r"KERNEL_LOADER_EQUIVALENCE_PASS cycles=(\d+) output_ports=(\d+)",
                      (out / "run.log").read_text())
    if match is None or int(match[2]) != manifest["compared_output_ports"]:
        raise RuntimeError("逐周期输出比较未报告成功")
    summary = json.loads((out / "summary.json").read_text())
    summary["reference_comparison"] = dict(manifest, compared_cycles=int(match[1]))
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"KERNEL_REFERENCE_COMPARISON_PASS cycles={match[1]} outputs={match[2]}")


if __name__ == "__main__":
    main()
