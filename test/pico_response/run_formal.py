#!/usr/bin/env python3
"""证明 CPU 桥接器的全部控制信号和有效读响应逐周期一致。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/soc/pico_native_to_axi.sv")
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source


def observe(source: str, name: str) -> str:
    # 数据端口只在读响应有效期间参与比较；写响应与空闲期间没有读数据传输。
    source = source.replace("module pico_native_to_axi #(", f"module {name} #(", 1)
    source = re.sub(r"\bassign mem_rdata\s*=", "assign formal_read_data =", source)
    source = source.replace("    localparam int unsigned BYTEW",
                            "    wire [DATA_WIDTH-1:0] formal_read_data;\n\n" +
                            "    localparam int unsigned BYTEW", 1)
    source = source.replace("endmodule", """
    assign mem_rdata = (rsp_valid_q || read_done_fire) ? formal_read_data : '0;
endmodule
""", 1)
    return source.replace("formal_read_data", f"formal_read_data_{name}")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def registered_properties(source: str, out: Path) -> list[dict]:
    # 归纳同时检查禁用缓存时的状态不变量，读响应数据和完成事件均完整保留。
    properties = """
    logic formal_past_valid = 1'b0;
    always_ff @(posedge clk) begin
        formal_past_valid <= 1'b1;
        if (formal_past_valid) begin
            assert(!ic_fill_q && !ic_req_q);
            if ($past(rst_n)) begin
                assert(mem_ready == $past(read_done_fire || b_fire));
                if ($past(read_done_fire)) begin
                    assert(mem_rdata == $past(m_axi_rdata));
                end else begin
                    assert(rsp_data_q == $past(rsp_data_q));
                end
            end else begin
                assert(!mem_ready);
            end
        end
        if (rsp_valid_q) begin
            assert(!new_read_req && !new_write_req);
        end
    end
"""
    generated = out / "registered.sv"
    generated.write_text(source.replace("module pico_native_to_axi #(",
                                        "module registered_bridge #(", 1)
                         .replace("endmodule", properties + "endmodule", 1))
    results = []
    for address, data in ((32, 32), (40, 64)):
        script = out / f"registered_a{address}_d{data}.ys"
        log = script.with_suffix(".log")
        script.write_text("read_slang --top registered_bridge " +
                          f"-GADDR_WIDTH={address} -GDATA_WIDTH={data} " +
                          "-GENABLE_ICACHE=0 -GREGISTER_RESPONSE=1 " +
                          shlex.quote(str(generated)) +
                          "\nprep -top registered_bridge -flatten\nmemory_map\nopt -full\nasync2sync\n" +
                          "chformal -lower\nopt_clean\n" +
                          "sat -seq 2 -tempinduct -maxsteps 6 -set-at 1 rst_n 0 " +
                          "-set-init-zero -prove-asserts -verify\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        if "Induction step proven: SUCCESS!" not in log.read_text():
            raise RuntimeError(f"寄存响应归纳证明未完成：{log}")
        results.append(dict(address_width=address, data_width=data,
                            passed=True, log_sha256=digest(log)))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="415a70a")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    reference = out / "reference.sv"
    candidate = out / "candidate.sv"
    reference.write_text(observe(original, "reference"))
    candidate.write_text(observe(current, "candidate"))
    report = dict(reference=args.reference, source_sha256=digest(ROOT / SOURCE),
                  input_constraints=None,
                  observation="全部控制端口；读数据在实际读响应周期比较",
                  profiles=[])
    profiles = [(32, 32, 0, 64, 4), (40, 64, 0, 64, 4),
                (32, 32, 1, 1, 1), (32, 32, 1, 4, 2), (40, 64, 1, 4, 2)]
    for index, (address, data, cache, lines, words) in enumerate(profiles):
        params = dict(ADDR_WIDTH=address, DATA_WIDTH=data, ENABLE_ICACHE=cache,
                      ICACHE_LINES=lines, ICACHE_LINE_WORDS=words)
        options = " ".join(f"-G{key}={value}" for key, value in params.items())
        script, log = out / f"case{index}.ys", out / f"case{index}.log"
        proof = (
            "miter -equiv -flatten gold gate miter\nprep -top miter -flatten\nopt -full\n" +
            "sat -seq 1 -tempinduct -maxsteps 8 -set-at 1 in_rst_n 0 " +
            "-set-init-zero -prove trigger 0 " +
            "-prove gold.ic_fill_q 0 -prove gate.ic_fill_q 0 -verify\n"
        ) if not cache else (
            "equiv_make gold gate equiv\nhierarchy -top equiv\nopt_clean\n" +
            "equiv_simple\nequiv_induct -seq 4\nequiv_status -assert\n")
        script.write_text(
            f"read_slang --top reference {options} {shlex.quote(str(reference))}\n" +
            "prep -top reference -flatten\nmemory_map\nopt -full\nrename reference gold\ndesign -stash gold\n" +
            f"read_slang --top candidate {options} {shlex.quote(str(candidate))}\n" +
            "prep -top candidate -flatten\nmemory_map\nopt -full\nrename candidate gate\n" +
            "design -copy-from gold -as gold gold\n" + proof)
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        text = log.read_text()
        success = "Equivalence successfully proven!" if cache else "Induction step proven: SUCCESS!"
        if success not in text:
            raise RuntimeError(f"CPU 桥接器证明未完成：{log}")
        match = re.search(r"Found (\d+) \\$equiv cells", text)
        item = dict(parameters=params, passed=True, log_sha256=digest(log))
        if match:
            item["equivalent_bits"] = int(match[1])
        report["profiles"].append(item)
        print(json.dumps(item), flush=True)
    report["registered_response"] = registered_properties(current, out)
    if current != (ROOT / SOURCE).read_text():
        raise RuntimeError("验证期间 CPU 桥接器源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
