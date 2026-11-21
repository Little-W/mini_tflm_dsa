#!/usr/bin/env python3
"""验证权重缓存比较资格及完整加载器的逐周期行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/loaders/kernel_loader.sv")
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source

FLAGS = ("managed_mode", "ctrl_load_req", "comparison_valid_q",
         "comparison_from_candidate_q", "candidate_equal_o_equal", "comparison_match_q",
         "buf_load_commit", "cache_flush", "init_cfg", "buf_discard_ready", "transfer_active")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def control_model(source, name):
    expressions = []
    for signal in ("comparison_ready", "cache_hit_fire", "discard_fire"):
        matches = re.findall(r"  assign " + signal + r" = .*?;", source, re.S)
        if len(matches) != 1:
            raise RuntimeError(f"无法唯一提取 {signal}")
        expressions.append(matches[0])
    stored = re.search(r"  always_comb begin\n    case \(\^prefetch_state\).*?\n  end", source, re.S)
    if stored:
        expressions.append(stored[0])
    inputs = "input logic [1:0] prefetch_state,\n    input logic " + ",".join(FLAGS)
    return f"""module {name}({inputs},
    output logic cache_hit_fire,discard_fire);
    localparam PF_EMPTY=2'd0,PF_PENDING=2'd1,PF_LOADING=2'd2,PF_CACHED=2'd3;
    logic comparison_ready,comparison_stored_ready;
""" + "\n".join(expressions) + "\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--reference", default="415a70a")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    reference_path = Path(args.reference)
    reference_text = reference_path.read_text() if reference_path.is_file() else read_rtl_source(
        f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    current_text = source.read_text()
    dependencies = [ROOT / "rtl/npu/loaders" / name for name in
                    ("kernel_loader_ctrl.sv", "kernel_loader_buffer.sv")]
    dependencies += sorted(path for path in (ROOT / "rtl/common").glob("*")
                           if path.suffix in (".sv", ".v"))
    hashes = {str(path): digest(path) for path in [source] + dependencies}
    snapshots = []
    for path in dependencies:
        target = out / "inputs" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        snapshots.append(target)
    source_paths = {}
    for label, content in (("reference", reference_text), ("current", current_text)):
        path = out / (label + ".sv")
        path.write_text(content)
        source_paths[label] = path

    def worker(name, commands):
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, check=True,
                           stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        return log.read_text(), digest(log)

    model = out / "control.sv"
    model.write_text(control_model(reference_text, "reference_control") +
                     control_model(current_text, "current_control") + """
module proof(input logic [12:0] inputs, output logic equivalent);
    wire [1:0] reference_result,current_result;
    reference_control u_reference(inputs[1:0],inputs[2],inputs[3],inputs[4],inputs[5],
        inputs[6],inputs[7],inputs[8],inputs[9],inputs[10],inputs[11],inputs[12],
        reference_result[0],reference_result[1]);
    current_control u_current(inputs[1:0],inputs[2],inputs[3],inputs[4],inputs[5],
        inputs[6],inputs[7],inputs[8],inputs[9],inputs[10],inputs[11],inputs[12],
        current_result[0],current_result[1]);
    assign equivalent = reference_result == current_result;
endmodule
""")
    text, log_hash = worker("control", ["read_slang --top proof " + shlex.quote(str(model)),
        "prep -top proof -flatten", "sat -verify -prove equivalent 1 -show-inputs -show-outputs"])
    assert "SAT proof finished - no model found: SUCCESS!" in text
    tb = out / "tb.sv"
    tb.write_text("""module tb;
    logic [12:0] inputs;
    wire equivalent;
    integer checks=0;
    proof u_proof(inputs,equivalent);
    task automatic compare;
        #1;
        if(u_proof.reference_result !== u_proof.current_result)
            $fatal(1,"Cache eligibility differs inputs=%h ref=%b current=%b",inputs,
                   u_proof.reference_result,u_proof.current_result);
        checks++;
    endtask
    initial begin
        for(integer value=0;value<8192;value++) begin
            inputs=13'(value); compare();
        end
        for(integer value=0;value<4096;value++) begin
            inputs=13'b0100000011100;
            for(integer digit=0;digit<6;digit++) begin
                case((value>>(2*digit))&3)
                    0:inputs[digit<2 ? digit : digit+3]=1'b0;
                    1:inputs[digit<2 ? digit : digit+3]=1'b1;
                    2:inputs[digit<2 ? digit : digit+3]=1'bx;
                    3:inputs[digit<2 ? digit : digit+3]=1'bz;
                endcase
            end
            compare();
        end
        $display("CACHED_COMPARE_FOUR_STATE_PASS checks=%0d",checks);
        $finish;
    end
endmodule
""")
    binary = out / "four_state.vvp"
    with (out / "four_state_build.log").open("w") as stream:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary), str(model), str(tb)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=60)
    result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, timeout=60)
    (out / "four_state.log").write_text(result.stdout + result.stderr)
    match = re.search(r"CACHED_COMPARE_FOUR_STATE_PASS checks=(\d+)", result.stdout)
    if result.returncode or match is None:
        raise RuntimeError("缓存比较资格的四态检查未通过")
    report = {"passed": False, "reference": args.reference, "source_sha256": hashes,
              "reference_sha256": digest(source_paths["reference"]),
              "source_input_constraints": False,
              "control": {"passed": True, "log_sha256": log_hash},
              "four_state": {"passed": True, "strict_four_state": True,
                             "checks": int(match[1]), "log_sha256": digest(out / "four_state.log")},
              "loader_profiles": []}
    for size, count, bus, fpga in ((4, 8, 32, False), (16, 29, 32, True), (16, 29, 64, True)):
        commands = []
        mode = "-D SYNTHESIS=1 -D XILINX_FPGA=1" if fpga else "-D ASIC_SYNTHESIS=1"
        for label, path in source_paths.items():
            commands += [f"read_slang {mode} --top kernel_loader -GSIZE={size} "
                f"-GCOUNT_WIDTH={count} -GBUS_WIDTH={bus} -GDATA_WIDTH=16 " +
                " ".join(shlex.quote(str(p)) for p in [path] + snapshots),
                "prep -top kernel_loader -flatten", "memory_map", "async2sync", "opt_clean",
                f"rename kernel_loader {label}", f"design -stash {label}"]
        commands += ["design -copy-from reference -as reference reference",
            "design -copy-from current -as current current",
            "equiv_make reference current equivalent", "hierarchy -top equivalent",
            "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2", "equiv_status -assert"]
        text, log_hash = worker(f"loader_s{size}_c{count}_b{bus}_f{int(fpga)}", commands)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        assert match is not None and int(match[2]) == 0
        row = {"SIZE": size, "COUNT_WIDTH": count, "BUS_WIDTH": bus, "fpga": fpga,
               "passed": True, "equivalent_bits": int(match[1]), "log_sha256": log_hash}
        report["loader_profiles"].append(row)
        print(json.dumps(row), flush=True)
    if hashes != {str(path): digest(path) for path in [source] + dependencies}:
        raise RuntimeError("验证期间源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
