#!/usr/bin/env python3
"""使用已验证的实际 FPGA 模型，检查队列满载后的连续短窗口。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
MAIN = r'''
int main(int argc,char** argv) {
  Verilated::commandArgs(argc,argv);
  try {
    Simulation s;s.configure(configuration());s.run({{0,0,16,0}});
    for(unsigned cols : {1u,2u,3u,4u,5u,7u,8u,12u,15u,16u}) {
      const size_t first=s.response_cycles.size();
      const auto before=s.elements;
      s.top.rsp_ready=0;
      for(unsigned i=0;i<4;) {
        Request request{0,0,cols,i};s.drive(request);if(s.tick(&request))i++;
      }
      s.top.req_valid=0;
      for(unsigned i=0;i<8;i++)s.tick();
      check(s.expected.size()==4,"short window queue did not retain four requests");
      std::vector<Request> rest;
      for(unsigned i=4;i<64;i++)rest.push_back({0,0,cols,i%4});
      s.run(rest);
      const auto last=s.response_cycles.size();
      const auto expected_beats=64*((cols+3)/4);
      check(last-first==expected_beats && s.elements-before==64*cols,
            "short window response count differs");
      uint64_t maximum_interval=0;
      for(size_t i=first+1;i<last;i++)
        maximum_interval=std::max(maximum_interval,s.response_cycles[i]-s.response_cycles[i-1]);
      std::printf("CASE short_resident cols=%u requests=64 beats=%llu elements=%u maximum_interval=%llu cycles=%llu\n",
        cols,static_cast<unsigned long long>(last-first),64*cols,
        static_cast<unsigned long long>(maximum_interval),
        static_cast<unsigned long long>(s.response_cycles.back()-s.response_cycles[first]+1));
    }
    check(s.accepted==s.completed && s.expected.empty() && !s.top.busy,"short requests did not drain");
    std::printf("SHORT_WINDOW_PASS accepted=%llu completed=%llu elements=%llu cycles=%llu\n",
      static_cast<unsigned long long>(s.accepted),static_cast<unsigned long long>(s.completed),
      static_cast<unsigned long long>(s.elements),static_cast<unsigned long long>(s.cycle));
    s.top.final();return 0;
  } catch(const std::exception& e) {std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}
}
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator-include", type=Path, required=True)
    args = parser.parse_args()
    model_dir = args.model_dir.resolve()
    prior = json.loads((model_dir / "summary.json").read_text())
    if not prior["passed"] or not prior["fpga"]:
        raise RuntimeError("The FPGA window model must pass its complete numeric test")
    for name, expected in prior["source_sha256"].items():
        if digest(Path(name)) != expected:
            raise RuntimeError("Window model input changed: " + name)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cpp = out / "short_main.cpp"
    original = (ROOT / "test/window_dma/main.cpp").read_text()
    cpp.write_text(original[:original.index("int main(int argc,char** argv)")] + MAIN)
    obj = model_dir / "obj"
    dependencies = [obj / name for name in ("verilated.o", "verilated_timing.o", "verilated_threads.o",
                                           "Vwindow_dma_top__ALL.a")]
    binary = out / "short_windows"
    command = ["g++", "-std=c++20", "-O1", "-fcoroutines", "-DVERILATOR=1", "-DVM_TIMING=1",
               "-fsanitize=undefined", "-fno-sanitize-recover=all", "-pthread",
               "-I" + str(obj), "-I" + str(args.verilator_include),
               "-I" + str(args.verilator_include / "vltstd"), str(cpp),
               *map(str, dependencies), "-latomic", "-o", str(binary)]
    with (out / "compile.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    run = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True)
    (out / "run.log").write_text(run.stdout + run.stderr)
    run.check_returncode()
    if "SHORT_WINDOW_PASS" not in run.stdout:
        raise RuntimeError("Short window checks did not complete")
    report = dict(passed=True, source_sha256=prior["source_sha256"],
                  input_model_summary_sha256=digest(model_dir / "summary.json"),
                  model_objects_sha256={path.name: digest(path) for path in dependencies},
                  main_sha256=digest(cpp), binary_sha256=digest(binary),
                  log_sha256=digest(out / "run.log"), compile_command=command,
                  results=run.stdout.splitlines())
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(run.stdout, end="", flush=True)


if __name__ == "__main__":
    main()
