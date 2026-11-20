#!/usr/bin/env python3
"""使用实际 FPGA 模型比较三类逐步解码及窗口接口的逐周期记录。"""
import argparse
import filecmp
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"
MAIN = r'''
int main(int argc,char** argv) {
  Verilated::commandArgs(argc,argv);
  try {
    Simulation s;
    const std::string argument=Verilated::commandArgsPlusMatch("BOUNDARY_TRACE=");
    const std::string prefix="+BOUNDARY_TRACE=";
    check(argument.rfind(prefix,0)==0,"missing boundary trace path");
    s.window_trace.open(argument.substr(prefix.size()));
    check(s.window_trace.good(),"cannot open boundary trace");
    s.trace_enabled=true;
    unsigned scenario=0;
    for(unsigned width : {1u,3u,5u,7u,17u}) {
      for(unsigned kernel : {5u,7u}) {
        for(unsigned channels : {5u,7u,17u}) {
          auto config=configuration(0x2003+scenario*0x1000,channels,kernel);
          config[7]=width;
          s.configure(config);
          s.random_memory=true;
          std::vector<Request> requests;
          requests.push_back({width*8-1,channels*kernel*kernel-1,1,0});
          for(unsigned i=1;i<32;i++)
            requests.push_back({unsigned(s.random()%(width*8)),
              unsigned(s.random()%(channels*kernel*kernel)),1+unsigned(s.random()%16),i%4});
          const auto start=s.cycle,before=s.elements;
          s.run(requests,true);
          std::printf("CASE boundary_decode width=%u kernel=%u channels=%u requests=32 elements=%llu cycles=%llu\n",
            width,kernel,channels,static_cast<unsigned long long>(s.elements-before),
            static_cast<unsigned long long>(s.cycle-start));
          scenario++;
        }
      }
    }
    check(s.accepted==s.completed && s.expected.empty() && !s.top.busy,"boundary requests did not drain");
    s.trace_enabled=false;s.window_trace.close();
    std::printf("DECODE_BOUNDARY_PASS scenarios=%u accepted=%llu completed=%llu elements=%llu cycles=%llu\n",
      scenario,static_cast<unsigned long long>(s.accepted),static_cast<unsigned long long>(s.completed),
      static_cast<unsigned long long>(s.elements),static_cast<unsigned long long>(s.cycle));
    s.top.final();return 0;
  } catch(const std::exception& e) {std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}
}
'''


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for data in iter(lambda: source.read(1 << 20), b""):
            result.update(data)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--reference-model", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--verilator-include", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text())
    if not proof["passed"] or not proof["unchanged_outside_decode_boundaries"]:
        raise RuntimeError("Source-linked decode comparison must pass first")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = (ROOT / "test/window_dma/main.cpp").read_text()
    cpp = out / "boundary_main.cpp"
    cpp.write_text(original[:original.index("int main(int argc,char** argv)")] + MAIN)
    results = {}
    model_sources = {}
    for name, model, source_hash in (("reference", args.reference_model, proof["reference_sha256"]),
                                      ("current", args.model, proof["source_sha256"])):
        model = model.resolve()
        previous = json.loads((model / "summary.json").read_text())
        if not previous["passed"] or not previous["fpga"]:
            raise RuntimeError("A complete actual FPGA window test is required")
        hashes = previous["source_sha256"]
        if [sha for path, sha in hashes.items() if path.endswith("/" + SOURCE)] != [source_hash]:
            raise RuntimeError("Formal and numeric model sources differ")
        if hashes[str(ROOT / "test/window_dma/main.cpp")] != digest(ROOT / "test/window_dma/main.cpp"):
            raise RuntimeError("Window numeric model source changed")
        model_sources[name] = {path: sha for path, sha in hashes.items() if "/rtl/" in path}
        if name == "current" and any(digest(Path(path)) != sha for path, sha in hashes.items()):
            raise RuntimeError("Current FPGA model inputs changed")
        obj, folder = model / "obj", out / name
        folder.mkdir(parents=True, exist_ok=True)
        dependencies = [obj / filename for filename in
            ("verilated.o", "verilated_timing.o", "verilated_threads.o", "Vwindow_dma_top__ALL.a")]
        binary, trace = folder / "boundary_windows", folder / "cycles.csv"
        command = ["g++", "-std=c++20", "-O1", "-fcoroutines", "-DVERILATOR=1", "-DVM_TIMING=1",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-pthread", "-I" + str(obj),
            "-I" + str(args.verilator_include), "-I" + str(args.verilator_include / "vltstd"),
            str(cpp), *map(str, dependencies), "-latomic", "-o", str(binary)]
        with (folder / "compile.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        run = subprocess.run([str(binary), "+BOUNDARY_TRACE=" + str(trace)], cwd=ROOT,
                             capture_output=True, text=True)
        (folder / "run.log").write_text(run.stdout + run.stderr)
        run.check_returncode()
        if "DECODE_BOUNDARY_PASS" not in run.stdout:
            raise RuntimeError("Boundary numeric checks incomplete")
        with trace.open() as stream:
            cycles = sum(1 for _ in stream)
        results[name] = dict(passed=True, model_summary_sha256=digest(model / "summary.json"),
            model_objects_sha256={path.name: digest(path) for path in dependencies},
            binary_sha256=digest(binary), trace_sha256=digest(trace), trace_cycles=cycles,
            log_sha256=digest(folder / "run.log"), tests=run.stdout.splitlines())
    differing = [path for path, sha in model_sources["current"].items()
                 if model_sources["reference"].get(path) != sha]
    if differing != [str(ROOT / SOURCE)]:
        raise RuntimeError("Additional RTL model differences require verification")
    if not filecmp.cmp(out / "current/cycles.csv", out / "reference/cycles.csv", shallow=False):
        raise RuntimeError("Boundary window cycle records differ")
    if results["current"]["tests"] != results["reference"]["tests"]:
        raise RuntimeError("Boundary scenario statistics differ")
    report = dict(passed=True, cycle_identical=True, source_sha256=proof["source_sha256"],
        reference_sha256=proof["reference_sha256"], proof_summary_sha256=digest(args.proof),
        main_sha256=digest(cpp), cases=results)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print("\n".join(results["current"]["tests"]), flush=True)
    print("DECODE_BOUNDARY_CYCLE_COMPARE_PASS cycles=" + str(results["current"]["trace_cycles"]), flush=True)


if __name__ == "__main__":
    main()
