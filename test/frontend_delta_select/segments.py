#!/usr/bin/env python3
"""读取已完成映射，计算窗口占用寄存器至各步长位的实际组合单元数。"""
import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from lut_dependencies import lut_output_dependencies
from netlist_metrics import FF_PATTERN, net_names, register_origins


def analyze(mapped, pre_lut):
    module = json.loads(mapped.read_text())["modules"]["delta_path"]
    cells, names = module["cells"], net_names(module)
    origins = register_origins(pre_lut)
    drivers = {}
    for name, cell in cells.items():
        for port, bits in cell["connections"].items():
            if cell["port_directions"][port] == "output":
                for bit in bits:
                    if isinstance(bit, int):
                        if bit in drivers:
                            raise RuntimeError("网络存在多个驱动")
                        drivers[bit] = (name, port)

    @lru_cache(maxsize=None)
    def walk(bit):
        if not isinstance(bit, int) or bit not in drivers:
            return None
        name, output = drivers[bit]
        cell = cells[name]
        if FF_PATTERN.fullmatch(cell["type"]):
            return () if origins.get(name) == "win_busy" else None
        inputs = lut_output_dependencies(cell, output)
        if inputs is None:
            if cell["type"] in ("MUXF7", "MUXF8"):
                inputs = tuple((port, 0, cell["connections"][port][0]) for port in ("I0", "I1", "S"))
            else:
                raise RuntimeError("步长输入范围含未实现的单元: " + cell["type"])
        options = []
        for port, _, upstream in inputs:
            path = walk(upstream)
            if path is not None:
                options.append(path + (dict(cell=name, type=cell["type"], input_port=port, output_port=output,
                                           input_net=names.get(upstream, str(upstream)), output_net=names.get(bit, str(bit))),))
        return max(options, key=len) if options else None

    result = {}
    for index, bit in enumerate(module["netnames"]["incoming_delta"]["bits"]):
        if index < 2:
            continue
        path = walk(bit)
        if path is None:
            raise RuntimeError("目标步长位与窗口选择寄存器没有组合路径")
        result[str(index)] = dict(combinational_cells=len(path), path=path)
    return dict(mapped_sha256=hashlib.sha256(mapped.read_bytes()).hexdigest(), bits=result,
                maximum_combinational_cells=max(item["combinational_cells"] for item in result.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", type=Path, required=True)
    args = parser.parse_args()
    folder = args.local.resolve()
    results = {}
    measured = json.loads((folder / "summary.json").read_text())
    for name, case in measured["cases"].items():
        case_dir = Path(case["directory"])
        results[name] = analyze(case_dir / "mapped.json", case_dir.parent / "pre_lut.il")
    report = dict(passed=True, scope="已映射网络的 win_busy 寄存器输出至 incoming_delta[31:2]；终点为组合网络",
                  no_netlist_modification=True, cases=results)
    (folder / "delta_segments.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print({name: case["maximum_combinational_cells"] for name, case in results.items()})


if __name__ == "__main__":
    main()
