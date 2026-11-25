#!/usr/bin/env python3
"""对完整偏置控制器逐周期比较公开输出和全部寄存器的四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "17dda6a11cd55ea470712335f2b5cfcfca4b4bd4"
CONTROL = Path("rtl/npu/loaders/bias_loader_ctrl.sv")
HELPER = Path("rtl/common/parallel_prefix_add.sv")
PROFILES = (
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=32, COUNT_WIDTH=29, GROUP_BLOCKS_MAX=16),
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=64, COUNT_WIDTH=64, GROUP_BLOCKS_MAX=16),
    dict(SIZE=16, BUS_WIDTH=64, REG_WIDTH=16, COUNT_WIDTH=29, GROUP_BLOCKS_MAX=16),
    dict(SIZE=4, BUS_WIDTH=32, REG_WIDTH=8, COUNT_WIDTH=1, GROUP_BLOCKS_MAX=1),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    originals = {
        "reference": subprocess.check_output(["git", "show", f"{revision}:{CONTROL}"], cwd=ROOT),
        "current": (root / CONTROL).read_bytes(),
    }
    helper = out / HELPER.name
    helper.write_bytes((root / HELPER).read_bytes())
    if helper.read_bytes() != subprocess.check_output(["git", "show", f"{revision}:{HELPER}"], cwd=ROOT):
        raise RuntimeError("此比较要求两侧使用完全相同的公共加法器")
    register_sets = [set(re.findall(r"\b(\w+)\s*<=", data.decode())) for data in originals.values()]
    if register_sets[0] != register_sets[1]:
        raise RuntimeError("控制器寄存器集合发生变化")
    registers = sorted(register_sets[0])
    text = originals["reference"].decode()
    ports = re.findall(r"^\s*(input|output)\s+logic\s+(\[[^\]]+\]\s*)?(\w+)\s*,?\s*$",
                       text[:text.index(");")], re.M)
    models = []
    for label, data in originals.items():
        original = out / (label + "_source.sv")
        original.write_bytes(data)
        text = data.decode().replace("module bias_loader_ctrl", "module " + label)
        marker = "    output logic                 switch_pending\n"
        if text.count(marker) != 1:
            raise RuntimeError("控制器公开端口定义不符合预期")
        text = text.replace(marker, marker.rstrip() + ",\n    output logic [4095:0] formal_state\n")
        text = text.replace("\nendmodule", "\n  assign formal_state = {" +
                            ", ".join(registers) + "};\nendmodule", 1)
        model = out / (label + ".sv")
        model.write_text(text)
        models.append(model)
    records = []
    for index, parameters in enumerate(PROFILES):
        folder = out / f"profile_{index}"
        folder.mkdir(exist_ok=True)
        declarations, instances = [], []
        for direction, width, name in ports:
            if direction == "input":
                declarations.append(f"  logic {width or ''} {name};")
            else:
                declarations.extend(f"  wire {width or ''} {label}_{name};"
                                    for label in ("reference", "current"))
        declarations.append("  wire [4095:0] reference_state, current_state;")
        for label in ("reference", "current"):
            connections = ",".join(f".{name}({name if direction == 'input' else label + '_' + name})"
                                    for direction, _, name in ports)
            options = ",".join(f".{key}({value})" for key, value in parameters.items())
            instances.append(f"  {label} #({options}) u_{label}({connections},.formal_state({label}_state));")
        names = [name for direction, _, name in ports if direction == "output"] + ["state"]
        expected = "{" + ",".join("reference_" + name for name in names) + "}"
        actual = "{" + ",".join("current_" + name for name in names) + "}"
        bench = folder / "tb.sv"
        bench.write_text("module tb;\n" +
            "\n".join(f"  localparam {key}={value};" for key, value in parameters.items()) + "\n" +
            "\n".join(declarations + instances) + f"""
  integer seed={20261125+index}, cycles=0, configuration_samples=0;
  always #5 clk=~clk;
  task check;
    begin
      #1; cycles++;
      if ({expected} !== {actual})
        $fatal(1,"Bias control/state differs at cycle %0d",cycles);
    end
  endtask
  initial begin
    clk=0; rst_n=0; init_cfg=0; bias_base=0; m=0; bias_step_blocks=0;
    bias_switch=0; bias_last_loop=0; load_bias_granted=0; dma_busy=0; dma_done=0;
    load_block_valid=0; load_block_bank=0;
    repeat(2) begin @(posedge clk); check(); @(negedge clk); end
    for(integer sample=0;sample<16384;sample++) begin
      rst_n=(sample%257)!=0;
      init_cfg=($random(seed)&31)==0;
      for(integer bit_index=0;bit_index<REG_WIDTH;bit_index++) begin
        bias_base[bit_index]=$random(seed);
        m[bit_index]=$random(seed);
        bias_step_blocks[bit_index]=$random(seed);
      end
      if(sample%7==0) m=REG_WIDTH'(sample%1025);
      if(sample%5==0) bias_step_blocks=REG_WIDTH'(sample%65);
      if(sample%11==0) bias_base=0;
      bias_switch=$random(seed); bias_last_loop=$random(seed);
      load_bias_granted=$random(seed); dma_busy=$random(seed); dma_done=$random(seed);
      load_block_valid=$random(seed); load_block_bank=$random(seed);
      if(sample%3==0) bias_base[sample%REG_WIDTH]=1'bx;
      if(sample%5==0) m[(sample/3)%REG_WIDTH]=1'bz;
      if(sample%7==0) bias_step_blocks[(sample/7)%REG_WIDTH]=1'bx;
      if(sample%4==0) begin
        case((sample/4)%12)
          0:load_bias_granted=1'bx;
          1:load_bias_granted=1'bz;
          2:dma_done=1'bx;
          3:load_block_valid=1'bz;
          4:load_block_bank=1'bx;
          5:bias_switch=1'bx;
          6:bias_last_loop=1'bz;
          7:dma_busy=1'bx;
          8:init_cfg=1'bx;
          9:init_cfg=1'bz;
          10:rst_n=1'bx;
          11:rst_n=1'bz;
        endcase
      end
      if(init_cfg && rst_n) configuration_samples++;
      @(posedge clk); check(); @(negedge clk);
    end
    $display("BIAS_ARITHMETIC_FOUR_STATE_PASS cycles=%0d configs=%0d",cycles,configuration_samples);
    $finish;
  end
endmodule
""")
        executable = folder / "simulation.vvp"
        command = ["iverilog", "-g2012", "-s", "tb", "-o", str(executable),
                   *map(str, models), str(helper), str(bench)]
        with (folder / "compile.log").open("w") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(["vvp", str(executable)], text=True, capture_output=True, timeout=180)
        log = folder / "run.log"
        log.write_text(result.stdout + result.stderr)
        match = re.search(r"BIAS_ARITHMETIC_FOUR_STATE_PASS cycles=(\d+) configs=(\d+)", result.stdout)
        if result.returncode or match is None:
            raise RuntimeError(str(log))
        record = dict(parameters=parameters, passed=True, cycles=int(match[1]),
                      sampled_configurations=int(match[2]), seed=20261125+index,
                      testbench_sha256=digest(bench), simulator_sha256=digest(executable),
                      log_sha256=digest(log), build_command=command)
        records.append(record)
        print(json.dumps({key: record[key] for key in ("parameters", "passed", "cycles")}), flush=True)
    hashes = {label: hashlib.sha256(data).hexdigest() for label, data in originals.items()}
    if digest(root / CONTROL) != hashes["current"] or digest(root / HELPER) != digest(helper):
        raise RuntimeError("验证期间 RTL 源文件发生变化")
    report = dict(passed=True, reference_commit=revision, source_sha256=hashes,
                  common_helper_sha256=digest(helper), all_public_outputs_compared=True,
                  all_controller_registers_compared=registers, strict_four_state_comparison=True,
                  profiles=records, cycles=sum(row["cycles"] for row in records))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
