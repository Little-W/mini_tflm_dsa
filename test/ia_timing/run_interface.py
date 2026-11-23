#!/usr/bin/env python3
"""复用 IA 数值回归，逐周期比较原始与当前加载器的全部公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source_group as read_rtl_source, shared_ia_parameters

ROOT = Path(__file__).resolve().parents[2]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def port_declarations(source):
    header = source.split(") (", 1)[1].split("\n);", 1)[0]
    header = re.sub(r"/\*.*?\*/|//[^\n]*", "", header, flags=re.DOTALL)
    entries = []
    depth = 0
    start = 0
    for index, char in enumerate(header):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            entries.append(header[start:index])
            start = index + 1
    entries.append(header[start:])
    ports = []
    for entry in entries:
        # 默认输入表达式不改变比较模块的端口类型。
        entry = re.split(r"(?<![<>=!])=(?!=)", entry, maxsplit=1)[0].strip()
        match = re.fullmatch(r"(input|output)\s+(.*?)\b([A-Za-z_]\w*)\s*((?:\[[^\]]*\]\s*)*)",
                             entry, flags=re.DOTALL)
        if not match:
            raise ValueError("Cannot parse port declaration: " + entry)
        direction, data_type, name, unpacked = match.groups()
        ports.append((direction, data_type.strip(), name, unpacked.strip()))
    return ports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="7ff66a59")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--cases", nargs="+", choices=("prefetch_generic", "prefetch_ordered", "grouped32"),
                        default=("prefetch_generic", "prefetch_ordered", "grouped32"))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    verilator = shutil.which(args.verilator)
    if not verilator:
        raise RuntimeError("Cannot locate Verilator: " + args.verilator)
    vendor_root = subprocess.check_output([verilator, "--getenv", "VERILATOR_ROOT"], text=True).strip()
    current_path = ROOT / "rtl/npu/loaders/ia_loader.sv"
    current = current_path.read_text()
    ports = port_declarations(current)
    reference_source = read_rtl_source(args.reference_rev +
        ":rtl/npu/loaders/ia_loader.sv", cwd=ROOT, text=True)
    pattern = r'\bparameter\s+(?:int\s+unsigned|int|bit|integer)\s+(\w+)\s*='
    current_parameters = set(re.findall(pattern, current[:current.index(') (')]))
    reference_parameters = re.findall(pattern, reference_source[:reference_source.index(') (')])
    parameters = shared_ia_parameters({name: name for name in reference_parameters
                                      if name in current_parameters}, reference_source)
    reference_ports = {name for _, _, name, _ in port_declarations(reference_source)}
    added_outputs = {name for direction, _, name, _ in ports
                     if direction == "output" and name not in reference_ports}
    if added_outputs - {"ram_shared_wr_data"}:
        raise ValueError("Reference does not provide: " + ", ".join(sorted(added_outputs)))
    outputs = [name for direction, _, name, _ in ports if direction == "output"]
    suffix = ["", "    // 与同一输入驱动的原始模块逐周期比较，包括未使能时的输出值。"]
    suffix += [f"    {data_type} reference_{name} {unpacked};"
               for direction, data_type, name, unpacked in ports if direction == "output"]
    # 关闭共享写数据预选时，新增输出的公开定义为零。
    suffix += [f"    assign reference_{name} = '0;" for name in sorted(added_outputs)]
    suffix += ["    ia_loader_reference #(",
               ",\n".join(f"        .{name}({value})" for name, value in parameters.items()),
               "    ) u_reference (",
               ",\n".join(f"        .{name}({'reference_' if direction == 'output' else ''}{name})"
                           for direction, _, name, _ in ports if name in reference_ports),
               "    );", "    always_ff @(posedge clk) begin", "        if (rst_n) begin"]
    suffix += [f"            assert ({name} == reference_{name}) else $fatal(1, \"IA output differs: {name}\");"
               for name in outputs]
    suffix += ["        end", "    end", ""]
    checked_path = out / "ia_loader_checked.sv"
    checked_path.write_text(current.replace("\nendmodule", "\n".join(suffix) + "\nendmodule", 1))
    reference_paths = []
    for module in ("ia_loader_cache_mgr", "ia_loader_ctrl", "ia_loader"):
        original = read_rtl_source(args.reference_rev +
                                            ":rtl/npu/loaders/" + module + ".sv", cwd=ROOT, text=True)
        original = re.sub(r"\bia_loader_ctrl\b", "ia_loader_ctrl_reference", original)
        original = re.sub(r"\bia_loader_cache_mgr\b", "ia_loader_cache_mgr_reference", original)
        original = re.sub(r"\bia_loader\b", "ia_loader_reference", original)
        for helper in ("ia_ordered_coordinate_equal", "ia_ordered_coordinate_same"):
            original = re.sub(r"\b" + helper + r"\b", helper + "_reference", original)
        path = out / (module + "_reference.sv")
        path.write_text(original)
        reference_paths.append(path)
    wrapper = out / "verilator_compare"
    # 将 Verilator 自带的 C++ 头文件作为系统头文件，测试代码仍按其原有警告配置编译。
    wrapper.write_text("#!" + sys.executable + "\nimport os, sys\n" +
                       "arguments = [" + repr(str(checked_path)) + " if argument == " +
                       repr(str(current_path)) + " else argument for argument in sys.argv[1:]]\n" +
                       "if '--getenv' not in arguments and '--version' not in arguments:\n" +
                       "    arguments += ['-CFLAGS', " +
                       repr("-isystem " + str(Path(vendor_root) / "include") +
                            " -Wno-sign-compare -Wno-unused-variable -Wno-unused-parameter -Wno-unused-but-set-variable") +
                       "] + " + repr([str(path) for path in reference_paths]) + "\n" +
                       "os.execv(" + repr(verilator) + ", [" + repr(verilator) +
                       "] + arguments)\n")
    wrapper.chmod(0o755)
    summary = {"reference_rev": args.reference_rev, "compared_outputs": outputs,
               "source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in
                                 (current_path, ROOT / "rtl/npu/loaders/ia_loader_ctrl.sv",
                                  ROOT / "rtl/npu/loaders/ia_loader_cache_mgr.sv")},
               "generated_sha256": {path.name: digest(path) for path in [checked_path, *reference_paths, wrapper]},
               "runs": []}
    for label in args.cases:
        folder = out / label
        command = [sys.executable, str(ROOT / "test/ia_compact/" /
                                      ("run.py" if label == "grouped32" else "run_prefetch.py")),
                   "--out", str(folder), "--verilator", str(wrapper)]
        if label == "prefetch_ordered":
            command.append("--ordered-job")
        elif label == "grouped32":
            command += ["--only", "loader", "--loader-cache-blocks", "32"]
        with (out / (label + ".log")).open("w") as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        report_path = folder / "summary.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        if label == "grouped32":
            report = report.get("tests", {}).get("loader", report)
        record = {"case": label, "passed": result.returncode == 0 and report.get("passed", False),
                  "command": command, "cycles": report.get("cycles"), "cases": report.get("cases"),
                  "commands": report.get("commands"), "value_checks": report.get("value_checks"),
                  "summary": str(report_path)}
        summary["runs"].append(record)
        summary["passed"] = all(item["passed"] for item in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not record["passed"]:
            print((out / (label + ".log")).read_text()[-8000:])
            raise SystemExit(1)


if __name__ == "__main__":
    main()
