#!/usr/bin/env python3
"""证明权重加载控制在完整任务计数范围内的时序等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/loaders/kernel_loader_ctrl.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="aa2ef9a3")
    parser.add_argument("--out", type=Path, default=ROOT / "build/kernel_loader_ctrl_formal")
    parser.add_argument("--profiles", nargs="+", default=["4:8", "8:16", "16:28", "16:32"])
    parser.add_argument("--seq", type=int, default=12)
    parser.add_argument("--fpga", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    reference = out / "kernel_loader_ctrl_ref.sv"
    current = (ROOT / SOURCE).read_text()
    observed = {}
    for label, text in (("reference", original), ("current", current)):
        if 'o_column_group_base' not in text:
            # 新接口仅导出原有寄存操作数，参考模块按同一表达式提供这些观察端口。
            ports = ('o_column_group_base', 'o_column_group_offset', 'o_address_group_base',
                     'o_address_row_offset', 'o_address_column_offset')
            declarations = ''.join(f'\n    output logic [REG_WIDTH-1:0] {name},' for name in ports)
            text, matches = re.subn(r'(output\s+logic\s+\[REG_WIDTH-1:0\]\s+dma_tile_base_addr,)',
                                    lambda match: match.group(1) + declarations, text, count=1)
            assert matches == 1
            expressions = ("REG_WIDTH'(group_base_col) << SIZE_SHIFT",
                           "REG_WIDTH'(load_col_in_group) << SIZE_SHIFT", 'group_base_addr',
                           'row_addr_offset', 'col_addr_offset')
            assignments = ''.join(f'  assign {name} = {expression};\n'
                                  for name, expression in zip(ports, expressions))
            text = text.replace('\nendmodule', '\n' + assignments + '\nendmodule', 1)
        # 步长只在 S_RUN 的更新分支消费，该观察点保留配置阶段的重定时关系。
        register = 'group_addr_step_q' if re.search(r'\bgroup_addr_step_q\b', text) else 'group_addr_step'
        addition = f'group_base_addr + {register};'
        assert text.count(addition) == 1
        text = text.replace(addition, 'group_base_addr + group_addr_step_active;', 1)
        observation = ("  (* keep *) wire [REG_WIDTH-1:0] group_addr_step_active =\n"
                       f"      (state == S_RUN) ? {register} : '0;\n\n")
        text = text.replace('  always_comb begin', observation + '  always_comb begin', 1)
        observed[label] = text
    reference.write_text(re.sub(r"\bkernel_loader_ctrl\b", "kernel_loader_ctrl_ref", observed['reference']))
    gate = out / 'kernel_loader_ctrl_gate.sv'
    gate.write_text(observed['current'])
    source_hash = hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest()
    profiles = []
    helpers = ' '.join(shlex.quote(str(ROOT / 'rtl/common' / name))
                       for name in ('add_equal.sv', 'add3_equal.sv'))
    primitive_library_sha256 = None
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
        model = out / 'xilinx_models.sv'
        model_text = '\n'.join(re.search(r'^module ' + name + r'\b.*?^endmodule',
                              library.read_text(), re.M | re.S).group(0)
                              for name in ('LUT6', 'DSP48E1'))
        model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', model_text, flags=re.S) + '\n')
        helpers += ' ' + shlex.quote(str(model))
        primitive_library_sha256 = hashlib.sha256(library.read_bytes()).hexdigest()
    for profile in args.profiles:
        size, count = map(int, profile.split(":"))
        name = f"n{size}_c{count}"
        script = out / f"{name}.ys"
        params = f"-GSIZE={size} -GCOUNT_WIDTH={count}"
        if args.fpga:
            params += ' -D SYNTHESIS -D YOSYS -D VERIFIC'
        script.write_text(
            f"read_slang --top kernel_loader_ctrl_ref {params} {shlex.quote(str(reference))} {helpers}\n"
            "prep -top kernel_loader_ctrl_ref -flatten\nrename kernel_loader_ctrl_ref gold\n"
            "design -stash gold\n"
            f"read_slang --top kernel_loader_ctrl {params} {shlex.quote(str(gate))} {helpers}\n"
            "prep -top kernel_loader_ctrl -flatten\nrename kernel_loader_ctrl gate\n"
            "design -copy-from gold -as gold gold\n"
            "equiv_make gold gate equiv\nhierarchy -top equiv\n"
            "async2sync\nequiv_simple\n"
            f"equiv_induct -seq {args.seq}\nequiv_status -assert\n")
        log_path = out / f"{name}.log"
        with log_path.open("w") as log:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"Formal verification failed: {log_path}")
        log = log_path.read_text()
        match = re.search(r"Found (\d+) \$equiv cells in equiv", log)
        profiles.append(dict(size=size, count_width=count, passed=True,
                             equivalence_points=int(match.group(1)) if match else None))
        print(json.dumps(profiles[-1]), flush=True)
    if source_hash != hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest():
        raise RuntimeError("Source changed during verification")
    report = dict(passed=True, reference=args.reference, source_sha256=source_hash,
                  reference_sha256=hashlib.sha256(original.encode()).hexdigest(), profiles=profiles,
                  fpga=args.fpga, primitive_library_sha256=primitive_library_sha256)
    assert source_hash == hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest()
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
