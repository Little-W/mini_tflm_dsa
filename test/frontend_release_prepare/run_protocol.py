#!/usr/bin/env python3
"""复用完整窗口协议回归，并逐周期比较行释放参数组合。"""
import argparse
import filecmp
import gzip
import json
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys

from run_formal import ROOT, SOURCE, REFERENCE, digest, sources
EXPECTED_SCENARIOS = 48
EXPECTED_REQUESTS = 1152


MAIN = r'''
int main(int argc,char** argv) {
  Verilated::commandArgs(argc,argv);
  try {
    Simulation s;
    const std::string argument=Verilated::commandArgsPlusMatch("RELEASE_TRACE=");
    const std::string prefix="+RELEASE_TRACE=";
    check(argument.rfind(prefix,0)==0,"missing release trace path");
    s.window_trace.open(argument.substr(prefix.size()));
    check(s.window_trace.good(),"cannot open release trace");
    s.trace_enabled=true;
    unsigned scenario=0;
    for(unsigned output_h : {1u,3u,8u,17u}) {
      for(unsigned stride : {1u,2u,4u}) {
        for(unsigned pad : {0u,3u}) {
          for(unsigned channels : {3u,16u}) {
            auto config=configuration(0x2003+scenario*0x1000,channels,3);
            config[1]=19;config[6]=output_h;config[8]=stride;
            config[10]=pad;config[14]=1;
            s.configure(config);s.random_memory=true;
            std::vector<Request> requests;
            requests.push_back({output_h*8-1,channels*9-1,1,0});
            requests.push_back({0,0,16,1});
            for(unsigned i=2;i<24;i++)
              requests.push_back({unsigned(s.random()%(output_h*8)),
                unsigned(s.random()%(channels*9)),1+unsigned(s.random()%16),i%4});
            const auto start=s.cycle,before=s.elements;
            s.run(requests,true);
            std::printf("CASE release output_h=%u stride=%u pad=%u channels=%u requests=24 elements=%llu cycles=%llu\n",
              output_h,stride,pad,channels,static_cast<unsigned long long>(s.elements-before),
              static_cast<unsigned long long>(s.cycle-start));
            scenario++;
          }
        }
      }
    }
    check(s.accepted==s.completed && s.expected.empty() && !s.top.busy,"release requests did not drain");
    s.trace_enabled=false;s.window_trace.close();
    std::printf("RELEASE_PREPARE_PASS scenarios=%u accepted=%llu completed=%llu elements=%llu cycles=%llu\n",
      scenario,static_cast<unsigned long long>(s.accepted),static_cast<unsigned long long>(s.completed),
      static_cast<unsigned long long>(s.elements),static_cast<unsigned long long>(s.cycle));
    s.top.final();return 0;
  } catch(const std::exception& e) {std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}
}
'''


def run(command, log):
    with log.open('w') as stream:
        stream.write('$ ' + shlex.join(map(str, command)) + '\n')
        stream.flush()
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--reuse-window', action='store_true', help='复用源码摘要一致的窗口模型与协议结果')
    parser.add_argument('--keep-objects', action='store_true', help='保留可重新生成的 C++ 编译中间文件')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    content, _ = sources(args.reference_ref)
    window = out / 'window'
    if not args.reuse_window:
        program = runpy.run_path(str(ROOT / 'test/window_dma/run.py'))
        original_reader = program['read_rtl_source']

        def reference_reader(revision_file, *, cwd, text=False):
            path = revision_file.split(':', 1)[1]
            if path == SOURCE:
                return original_reader(revision_file, cwd=cwd, text=text)
            return (ROOT / path).read_text() if text else (ROOT / path).read_bytes()

        # 两次编译共用全部依赖，仅前端文件使用指定历史版本。
        entry = program['main']
        entry.__globals__['read_rtl_source'] = reference_reader
        previous = sys.argv
        try:
            sys.argv = ['window_dma/run.py', '--out', str(window), '--verilator', args.verilator,
                        '--jobs', '1', '--fpga', '--reference-ref', args.reference_ref]
            entry()
        finally:
            sys.argv = previous
    window_results = {label: json.loads((folder / 'summary.json').read_text()) for label, folder in
                      (('current', window), ('reference', window / 'reference'))}
    model_hashes = {}
    for label, summary in window_results.items():
        if not summary['passed'] or not summary['fpga']:
            raise RuntimeError('完整 FPGA 窗口回归未通过')
        hashes = summary['source_sha256']
        if [value for path, value in hashes.items() if path.endswith('/' + SOURCE)] != [digest(content[label])]:
            raise RuntimeError('协议测试与行释放源码不一致')
        if any(digest(Path(path).read_bytes()) != value for path, value in hashes.items()):
            raise RuntimeError('窗口模型源码已经变化')
        model_hashes[label] = {'rtl/' + path.split('/rtl/', 1)[1]: value
                              for path, value in hashes.items() if '/rtl/' in path}
    differing = {path for path, value in model_hashes['current'].items()
                 if model_hashes['reference'].get(path) != value}
    if differing != {SOURCE}:
        raise RuntimeError('窗口参考模型存在其他 RTL 差异')
    if window_results['current']['tests'] != window_results['reference']['tests']:
        raise RuntimeError('窗口协议场景统计不同')
    if not window_results['current']['resident_stream_cycle_equivalent']:
        raise RuntimeError('连续窗口逐周期比较未通过')

    version = subprocess.check_output([args.verilator, '-V'], text=True)
    roots = re.findall(r'^\s*VERILATOR_ROOT\s*=\s*(\S+)\s*$', version, re.M)
    include = next((Path(root) / 'include' for root in reversed(roots)
                    if (Path(root) / 'include/verilated.h').exists()), None)
    if include is None:
        raise RuntimeError('无法确定 Verilator 头文件目录')
    original = (ROOT / 'test/window_dma/main.cpp').read_text()
    cpp = out / 'release_main.cpp'
    cpp.write_text(original[:original.index('int main(int argc,char** argv)')] + MAIN)
    results = {}
    for label, folder in (('current', window), ('reference', window / 'reference')):
        destination = out / label
        destination.mkdir(exist_ok=True)
        obj = folder / 'obj'
        dependencies = [obj / name for name in
            ('verilated.o', 'verilated_timing.o', 'verilated_threads.o', 'Vwindow_dma_top__ALL.a')]
        binary, trace = destination / 'release_windows', destination / 'cycles.csv'
        command = ['g++', '-std=c++20', '-O1', '-fcoroutines', '-DVERILATOR=1', '-DVM_TIMING=1',
            '-fsanitize=undefined', '-fno-sanitize-recover=all', '-pthread', '-I' + str(obj),
            '-I' + str(include), '-I' + str(include / 'vltstd'), str(cpp),
            *map(str, dependencies), '-latomic', '-o', str(binary)]
        run(command, destination / 'compile.log')
        run([binary, '+RELEASE_TRACE=' + str(trace)], destination / 'run.log')
        log = (destination / 'run.log').read_text()
        completion = (f'RELEASE_PREPARE_PASS scenarios={EXPECTED_SCENARIOS} '
                      f'accepted={EXPECTED_REQUESTS} completed={EXPECTED_REQUESTS}')
        if completion not in log:
            raise RuntimeError('行释放参数测试未完成')
        results[label] = dict(passed=True, binary_sha256=digest(binary.read_bytes()),
            trace_sha256=digest(trace.read_bytes()), trace_cycles=sum(1 for _ in trace.open()),
            log_sha256=digest(log),
            tests=[line for line in log.splitlines() if line.startswith(('CASE ', 'RELEASE_PREPARE_PASS'))],
            model_objects_sha256={path.name: digest(path.read_bytes()) for path in dependencies})
    if not filecmp.cmp(out / 'current/cycles.csv', out / 'reference/cycles.csv', shallow=False):
        raise RuntimeError('行释放参数测试的周期记录不同')
    if results['current']['tests'] != results['reference']['tests']:
        raise RuntimeError('行释放参数测试的场景统计不同')
    report = dict(passed=True, cycle_identical=True, reference_ref=args.reference_ref,
        source_sha256={name: digest(text) for name, text in content.items()},
        unchanged_dependencies=True, bus_width=32, scenarios=EXPECTED_SCENARIOS, requests=EXPECTED_REQUESTS,
        cpp_sha256=digest(cpp.read_bytes()), window=window_results, release=results)
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for folder in (out / 'current', out / 'reference'):
        path = folder / 'cycles.csv'
        with path.open('rb') as src, gzip.open(str(path) + '.gz', 'wb', compresslevel=2) as dst:
            shutil.copyfileobj(src, dst)
        path.unlink()
    if not args.keep_objects:
        for folder in (window, window / 'reference'):
            shutil.copy2(folder / 'obj/Vwindow_dma_top', folder / 'window_dma')
            shutil.rmtree(folder / 'obj')
    print(results['current']['tests'][-1], flush=True)
    print('RELEASE_PREPARE_CYCLE_COMPARE_PASS cycles=' + str(results['current']['trace_cycles']), flush=True)


if __name__ == '__main__':
    main()
