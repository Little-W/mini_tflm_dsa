#!/usr/bin/env python3
"""归纳证明整组预留、循环地址关系和 SRAM 同地址读写互斥。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [source_root / "rtl/npu/writeback/requant_group_buffer.sv",
               source_root / "rtl/common/regfile.v",
               source_root / "test/requant_time_share/buffer_proof.sv",
               ROOT / "test/monitors/requant_group_buffer_observer.sv",
               Path(__file__).resolve()]
    hashes = {str(path): sha(path) for path in sources}
    proof = out / "buffer_proof.sv"
    original = sources[2].read_text()
    if original.count("endmodule") != 1:
        raise RuntimeError("Unexpected proof module structure")
    additions = """
    // 队列地址距离对应尚未读取的行数，满状态由行数区分。
    wire [31:0] write_address = 32'(dut.write_addr_q);
    wire [31:0] read_address = 32'(dut.read_addr_q);
    wire [31:0] address_distance = (write_address >= read_address) ?
        write_address - read_address : 32'(p_rows) + write_address - read_address;
    always_comb if (rst_n) begin
        if (write_address == read_address)
            assert(dut.stored_rows_q == 0 || dut.stored_rows_q == p_rows);
        else
            assert(32'(dut.stored_rows_q) == address_distance);
        if (dut.push_row && dut.read_row)
            assert(write_address != read_address);
    end
"""
    proof.write_text(original.replace("endmodule", additions + "endmodule"))
    profiles = []
    for rows in (1, 3, 16, 127, 128, 129, 511, 512, 513, 1024):
        script = out / f"rows_{rows}.ys"
        script.write_text(
            f"read_slang --top requant_buffer_proof -Gp_rows={rows} "
            + " ".join(map(str, [*sources[:2], proof, sources[3]]))
            + "\nproc\nflatten\nopt -full\nmemory_map\nasync2sync\nchformal -lower\nopt -full\n"
              "sat -seq 2 -tempinduct -maxsteps 12 -set-at 1 rst_n 0 -set-assumes "
              "-prove-asserts -verify -timeout 60\n"
        )
        command = [sys.executable, str(source_root / "scripts/fpga/open_fpga_synth.py"),
                   "--worker", str(script)]
        log = out / f"rows_{rows}.log"
        with log.open("w") as stream:
            status = subprocess.run(command, cwd=source_root, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=150)
        if status.returncode:
            raise RuntimeError(log.read_text()[-8000:])
        profiles.append({"rows": rows, "passed": True, "script_sha256": sha(script)})
    if hashes != {str(path): sha(path) for path in sources}:
        raise RuntimeError("Source files changed during proof")
    summary = {
        "passed": True, "source_sha256": hashes, "proof_sha256": sha(proof),
        "profiles": profiles,
        "properties": ["整组预留覆盖全部未完成行", "地址始终位于有效行范围", "循环地址距离与未读取行数一致",
                       "同步 SRAM 不发生同地址读写"],
        "assumptions": ["整组仅在 ready 时预留，行数在 1 至容量之间", "输入行数不超过已预留行数",
                        "输出只消费已发射的行"],
        "unconstrained_inputs": ["组到达时间", "输入行到达时间", "输出背压", "流水完成时间", "复位和清空"],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "profiles": len(profiles)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
