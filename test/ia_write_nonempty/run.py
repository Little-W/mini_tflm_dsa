#!/usr/bin/env python3
"""证明 IA 写命令的有效字节条件及共享存储的全部访问命令。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prove(out: Path, name: str, commands: list[str]) -> dict:
    script, log = out / (name + ".ys"), out / (name + ".log")
    script.write_text("\n".join(commands) + "\n")
    with log.open("w") as stream:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                 "--worker", str(script)], stdout=stream,
                                stderr=subprocess.STDOUT, timeout=180)
    text = log.read_text()
    passed = result.returncode == 0 and "Induction step proven: SUCCESS!" in text
    row = dict(case=name, passed=passed, script_sha256=digest(script), log_sha256=digest(log))
    if not passed:
        raise RuntimeError(f"Write command proof did not complete: {log}")
    print(json.dumps(row), flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="ef0dc75342997721bdc4110b2841445df962018e")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out, source = args.out.resolve(), args.source_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    helper = load("ia_write_wrapper", ROOT / "test/ia_shared_write_stage/helpers.py")
    helper.ROOT = source
    wrapper = out / "producer.sv"
    ports = helper.make_wrapper(wrapper, formal=True)
    text = wrapper.read_text().replace("logic [4:0] o_properties", "logic [1:0] o_properties")
    text = re.sub(r"    assign o_properties\[\d+\] = .*?;\n", "", text)
    text = text.replace("endmodule", """    assign o_properties[0] = !ram_port_wr_en[0] || (|ram_port_wr_mask[0]);
    assign o_properties[1] = !ram_port_wr_en[1] || (|ram_port_wr_mask[1]);
endmodule""")
    wrapper.write_text(text)
    inputs = [source / item for item in helper.SOURCES]
    inputs.append(source / "rtl/npu/buffers/vector_shared_store.sv")
    inputs += sorted(path for path in (source / "rtl/common").iterdir() if path.suffix in (".v", ".sv"))
    hashes = {str(path.relative_to(source)): digest(path) for path in inputs}
    outputs = [name for direction, _, name, _ in ports if direction == "output" and name != "o_properties"]
    report = dict(source_sha256=hashes, producer=[], consumer=[], reference=args.reference)
    for stage in (0, 1):
        for layout in (0, 1):
            selected = out / f"producer_s{stage}_layout{layout}.sv"
            selected.write_text(text.replace(".p_dma_source_layout(1'b1)", f".p_dma_source_layout(1'b{layout})"))
            commands = [shlex.join(["read_slang", "--top", "cache_shared", "-DSYNTHESIS=1",
                         "-DXILINX_FPGA=1", f"-Gp_shared_write_stage={stage}",
                         *map(str, [*inputs, selected])]), "prep -top cache_shared -flatten",
                        "delete -output " + " ".join("cache_shared/" + name for name in outputs),
                        "opt_clean -purge", "memory_map", "async2sync", "opt_clean -purge",
                        "select -module cache_shared",
                        "sat -seq 2 -set-at 1 rst_n 0 -prove-skip 1 -set-def-inputs "
                        "-set-def-formal -set-init-def -prove o_properties 3 -verify",
                        "sat -seq 1 -tempinduct-inductonly -maxsteps 1 -set-def-inputs "
                        "-set-def-formal -set-init-def -prove o_properties 3 -verify"]
            report["producer"].append(prove(out, f"producer_s{stage}_layout{layout}", commands))
    vector = source / "rtl/npu/buffers/vector_shared_store.sv"
    vector_ports = helper.port_declarations(vector.read_text())
    vector_inputs = [port for port in vector_ports if port[0] == "input"]
    vector_outputs = [port for port in vector_ports if port[0] == "output"]
    parameters = dict(p_bank_bytes=8192, p_total_bytes=57344, p_addr_width=12,
                      p_bank_count_width=3, p_fixed_ps_channels=1)
    lines = ["module vector_write_property #(",
             ",\n".join(f"parameter int {name}={value}" for name, value in parameters.items()),
             ") (", ",\n".join(f"{direction} {kind} {name} {array}" for
                                     direction, kind, name, array in vector_inputs),
             ", output logic [1:0] o_properties);"]
    lines += [f"{kind} {name} {array};" for _, kind, name, array in vector_outputs]
    lines += ["vector_shared_store #(",
              ",\n".join(f".{name}({name})" for name in parameters), ") u_store (",
              ",\n".join(f".{name}({name})" for _, _, name, _ in vector_ports), ");",
              "assign o_properties[0] = !o_ia_write_en[0] || (|o_ia_write_mask[0]);",
              "assign o_properties[1] = !o_ia_write_en[1] || (|o_ia_write_mask[1]);", "endmodule"]
    vector_wrapper = out / "vector_producer.sv"
    vector_wrapper.write_text("\n".join(lines) + "\n")
    report["producer"].append(prove(out, "vector_producer", [
        shlex.join(["read_slang", "--top", "vector_write_property", str(vector), str(vector_wrapper)]),
        "prep -top vector_write_property -flatten", "async2sync", "opt_clean",
        "sat -verify -tempinduct -seq 1 -prove o_properties 3"]))
    shared = load("shared_ram_commands", ROOT / "test/shared_ram_access_depth/run_formal.py")
    relative = "rtl/npu/buffers/ia_ps_shared_ram.sv"
    original = read_rtl_source(f"{args.reference}:{relative}", cwd=ROOT).decode()
    current = (source / relative).read_text()
    model = shared.miter(original, current)
    start = model.index("module access_miter #(")
    before, body = model[:start], model[start:]
    for port, count in (("i_ia_read_en", 2), ("i_ia_write_en", 2), ("i_ps_read_en", 4), ("i_ps_write_en", 4)):
        body = body.replace(f".{port}({port} & {{{count}{{i_access_enable}}}})", f".{port}({port})")
    begin = body.index("channel_reference #(")
    body = body[:begin] + body[begin:].replace(".clk(clk), .rst_n(rst_n), .i_cfg_valid(i_cfg_valid),",
             ".clk(clk), .rst_n(rst_n), .i_access_enable(i_access_enable), .i_cfg_valid(i_cfg_valid),", 1)
    body = body.replace(".p_shared_write_stage(p_shared_write_stage)) u_current",
                        ".p_shared_write_stage(p_shared_write_stage), .p_ia_nonempty_writes(1'b1)) u_current")
    body = body.replace(".i_ia_write_en(i_ia_write_en)", ".i_ia_write_en(qualified_write_en)")
    marker = "  logic reference_fault, current_fault;"
    body = body.replace(marker, """  logic [1:0] qualified_write_en;
  for (genvar port_index=0; port_index<2; port_index++) begin : g_valid_write
    assign qualified_write_en[port_index] = i_ia_write_en[port_index] && (|i_ia_write_mask[port_index]);
  end
""" + marker)
    model_path = out / "consumer.sv"
    model_path.write_text(before + body)
    for size, banks in ((2048, 6), (2048, 8), (8192, 7), (8192, 9)):
        name = f"consumer_b{size}_n{banks}"
        commands = [shlex.join(["read_slang", "--top", "access_miter", f"-Gp_bank_bytes={size}",
                     f"-Gp_total_bytes={size*banks}", str(model_path)]),
                    "prep -top access_miter -flatten", "async2sync", "opt_clean",
                    "sat -verify -tempinduct -seq 2 -set-at 1 rst_n 0 -prove equivalent 1"]
        report["consumer"].append(prove(out, name, commands))
    report["reset_condition"] = "rst_n=0 at the first sampled edge; subsequent resets are unrestricted"
    report["producer_input_constraints"] = None
    report["consumer_write_condition"] = "Each enabled IA write has at least one enabled byte, as proved for the connected producer"
    report["consumer_scope"] = "All storage commands, data, masks, enabled addresses, configuration, fault and return selection state"
    report["memory_abstraction"] = "Storage commands and return selection are compared; stored contents do not affect control"
    report["source_hashes_unchanged"] = hashes == {str(p.relative_to(source)): digest(p) for p in inputs}
    if not report["source_hashes_unchanged"]:
        raise RuntimeError("RTL changed during verification")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
