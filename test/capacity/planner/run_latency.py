#!/usr/bin/env python3
"""Measure planner calls on PicoRV32 and check every result against native C."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
FIELDS = [
    'tiling.ia_reuse', 'tiling.w_reuse', 'tiling.row_groups', 'tiling.row_tail_tiles',
    'tiling.col_groups', 'tiling.col_tail_tiles', 'raw_safe.ia_reuse', 'raw_safe.w_reuse',
    'raw_safe.row_groups', 'raw_safe.row_tail_tiles', 'raw_safe.col_groups', 'raw_safe.col_tail_tiles',
    'is_mode', 'frame_rows', 'adaptive_active', 'reduction', 'lhs_element_bytes', 'bus_bytes',
    'payload_bound_bytes', 'lhs_read_rounds', 'rhs_read_rounds', 'operand_read_bytes',
    'frame_count', 'array_stream_cycles', 'service_estimate', 'ps_control', 'ia_slots',
    'slice_rows', 'predicted_resident_frames', 'estimated_record_bytes', 'literal_record_bytes',
    'candidates_evaluated', 'micro_commands', 'weight_shift_rows',
    'ia_bank_count', 'ia_bytes', 'pool_bytes', 'raw_safe_is_mode', 'raw_safe_ps_control',
    'raw_safe_slice_rows', 'raw_safe_ia_bank_count', 'raw_safe_ia_bytes', 'raw_safe_pool_bytes',
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log, timeout=1800):
    with Path(log).open('w') as output:
        result = subprocess.run([str(x) for x in command], stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
    result.check_returncode()


def requests(args):
    shapes = json.loads((TESTS / 'shapes.json').read_text())
    manifests, hashes, rows = {}, {}, []
    for policy in (0, 1):
        for shape in shapes:
            model = shape['model']
            if model not in manifests:
                path = args.prepared / model / 'manifest.json'
                manifests[model] = json.loads(path.read_text())
                hashes[str(path.resolve())] = sha(path)
            graph = manifests[model]['graph']
            node = next(n for n in graph['nodes'] if n['index'] == shape['operator'])
            tensors = {t['index']: t for t in graph['tensors']}
            lhs, rhs = [tensors[node['inputs'][i]] for i in (0, 1)]
            assert rhs['dtype'] == 'int8'
            assert len(set(rhs['zero_points'])) == 1
            source_s8 = lhs['dtype'] == 'int8'
            assert source_s8 or lhs['dtype'] == 'int16'
            lhs_offset, rhs_offset = -lhs['zero_points'][0], -rhs['zero_points'][0]
            m, k, n = [shape['shape'][name] for name in ('M', 'K', 'N')]
            lhs_bound = 32768 if not source_s8 else 128 if lhs_offset == 0 else 256 if -128 <= lhs_offset <= 128 else 32768
            rhs_bound = 128 if rhs_offset == 0 else 256 if -128 <= rhs_offset <= 128 else 32768
            product = lhs_bound * rhs_bound
            literal = 48 if product < 2**23 and ((k - 1) & ~15) * product < 2**23 else 64
            element_bytes = 2 if shape['kind'] == 'conv' or not source_s8 else 1
            q = [m, k, n, 16, args.ia_bytes, args.frames, args.pool_bytes, 0, 0, 2,
                 1, int(shape['kind'] == 'conv'), element_bytes, 3 if source_s8 else 2, 1, policy,
                 32 if source_s8 else 64, literal, 32, 0, 0, 0, 0, 0, 0,0,0]
            geometry = [0] * 8
            if shape['kind'] == 'conv':
                source_bytes = 1 if source_s8 else 2
                _, ih, iw, ic = lhs['shape']
                _, kh, kw, gc = rhs['shape']
                geometry = [ih * iw * ic * source_bytes, ic, gc, kh, kw,
                            node['options']['stride_w'], source_bytes, args.image_cache_bytes]
            rows.append({**shape, 'adaptive': policy, 'source_s8': source_s8,
                         'lhs_offset': lhs_offset, 'rhs_offset': rhs_offset, 'request': q, 'geometry': geometry,
                         'shared_memory': [args.shared_total_bytes, args.bank_bytes, args.ia_bank_mask, args.directory_rows]})
    return rows, hashes


def source(rows, host, fields, request_count, shared_supported):
    geometry=request_count>=24
    word_count=len(fields)+2
    table = ',\n'.join('{' + ','.join(f'{v}u' for v in row['request'][:request_count]) + '}' for row in rows)
    common = '#include "gempact_tiling.h"\n' + 'static const gempact_device_request_t requests[]={\n' + table + '\n};\n'
    if geometry:
        geometry_table = ',\n'.join('{' + ','.join(f'{v}u' for v in row['geometry']) + '}' for row in rows)
        common += 'static const gempact_im2col_geometry_t geometry[]={\n' + geometry_table + '\n};\n'
    if shared_supported:
        shared = rows[0]['shared_memory']
        common += 'static const gempact_shared_memory_t shared={' + ','.join(f'{v}u' for v in shared) + '};\n'
    plan = ('(shared.total_bytes?gempact_plan_shared(&q,&shared,&p):gempact_plan_device(&q,&p))'
            if shared_supported else 'gempact_plan_device(&q,&p)')
    prepare = ('int valid=!geometry[i].source_bytes || gempact_set_im2col_geometry(&q,&geometry[i]);\n'
               if geometry else 'int valid=1;\n')
    if host:
        values = ','.join('(unsigned long long)p.' + field for field in fields)
        fmt = '%d,' + ','.join('%llu' for _ in fields)
        return common + '#include <stdio.h>\nint main(void){\n' + (
            'for(unsigned i=0;i<sizeof(requests)/sizeof(requests[0]);++i){\n'
            'gempact_device_request_t q=requests[i];gempact_dispatch_t p={0};\n' + prepare +
            f'int ok=valid && {plan};\n'
            f'printf("[{fmt}]\\n",ok,{values});\n'
            'if(!ok)return 1;\n}\nreturn 0;}\n')
    stores = '\n'.join(f'result[base+{i+2}u]=(uint32_t)p.{field};' for i, field in enumerate(fields))
    return common + '''static inline uint32_t clock_cycles(void){uint32_t v;__asm__ volatile("rdcycle %0":"=r"(v));return v;}
void *memcpy(void *dst,const void *src,unsigned long n){unsigned char *d=dst;const unsigned char *s=src;while(n--)*d++=*s++;return dst;}
void *memset(void *dst,int value,unsigned long n){unsigned char *d=dst;while(n--)*d++=(unsigned char)value;return dst;}
int main(void){
 volatile uint32_t *marker=(volatile uint32_t *)0x2000000c;
 volatile uint32_t *result=(volatile uint32_t *)0x001f0000;
 *marker=0xc0f10001u;
 for(uint32_t i=0;i<sizeof(requests)/sizeof(requests[0]);++i){
   gempact_device_request_t q=requests[i];gempact_dispatch_t p={0};
   *marker=0xd1000000u+i;
   uint32_t start=clock_cycles();''' + prepare + 'int ok=valid && '+plan+''';uint32_t end=clock_cycles();
   *marker=0xd2000000u+i;
   uint32_t base=i*''' + str(word_count) + '''u;
   result[base]=end-start;result[base+1u]=(uint32_t)ok;
''' + stores + '''
   if(!ok)return 1;
 }
 *marker=0xc0f10002u;return 0;
}
'''


def measure(name, include, rows, args, gcc, host_cc, simulator_hash):
    out = args.out / name
    out.mkdir(parents=True, exist_ok=True)
    header_hash = sha(include / 'gempact_tiling.h')
    host_source, rv_source = out / 'native.c', out / 'planner.c'
    header=(include / 'gempact_tiling.h').read_text()
    geometry='im2col_source_bytes' in header
    shared_supported='gempact_plan_shared(' in header
    fields=FIELDS if shared_supported else FIELDS[:34]
    request_count=27 if shared_supported else 24 if geometry else 19
    word_count=len(fields)+2
    host_source.write_text(source(rows, True, fields, request_count, shared_supported))
    rv_source.write_text(source(rows, False, fields, request_count, shared_supported))
    host_binary = out / 'native'
    host_command = [str(host_cc), '-std=c11', '-O1', '-g0', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I' + str(include),
                    str(host_source), '-o', str(host_binary)]
    run(host_command, out / 'native_compile.log')
    run([host_binary], out / 'native.log')
    expected = [json.loads(line) for line in (out / 'native.log').read_text().splitlines()]
    assert len(expected) == len(rows)
    for record in expected:
        assert len(record) == len(fields)+1 and record[0] == 1 and all(0 <= x <= 0xffffffff for x in record)
    elf, raw, memory, result_file = [out / f'planner.{ext}' for ext in ('elf', 'bin', 'hex', 'result')]
    command = [str(gcc), '-O3', '-g0', '-march=rv32im_zicsr', '-mabi=ilp32', '-ffreestanding',
               '-fno-builtin', '-ffunction-sections', '-fdata-sections', '-fno-unwind-tables',
               '-nostartfiles', '-nostdlib', '-I' + str(include), '-Wl,--gc-sections',
               '-Wl,-T,' + str(TESTS / 'link.ld'), str(TESTS / 'start.S'), str(rv_source), '-lgcc', '-o', str(elf)]
    run(command, out / 'compile.log')
    objcopy = gcc.with_name(gcc.name[:-3] + 'objcopy')
    subprocess.run([str(objcopy), '-O', 'binary', str(elf), str(raw)], check=True)
    data = raw.read_bytes()
    data += b'\0' * (-len(data) % 4)
    memory.write_text('\n'.join(f'{x[0]:08x}' for x in struct.iter_unpack('<I', data)) + '\n')
    run_command = [str(args.simulator), '+SOC_CPU_MEM=' + str(memory), '+RESULT_ADDR=001f0000',
                   '+RESULT_WORDS=' + str(len(rows) * word_count), '+RESULT_FILE=' + str(result_file),
                   '+TIMEOUT_CYCLES=600000000']
    run(run_command, out / 'run.log')
    log = (out / 'run.log').read_text()
    assert 'SOC_NETWORK_PASS status=0' in log and '%Error' not in log
    words = [x[0] for x in struct.iter_unpack('<I', result_file.read_bytes())]
    assert len(words) == len(rows) * word_count
    result_rows = []
    for index, row in enumerate(rows):
        record = words[index * word_count:(index + 1) * word_count]
        assert record[1:] == expected[index], (name, index, record[1:], expected[index])
        result_rows.append({**row, 'cycles': record[0], 'ok': record[1],
                            'plan': dict(zip(fields, record[2:]))})
    assert header_hash == sha(include / 'gempact_tiling.h')
    assert simulator_hash == sha(args.simulator)
    totals = {str(policy): sum(r['cycles'] for r in result_rows if r['adaptive'] == policy) for policy in (0, 1)}
    return {'passed': True, 'rows': result_rows, 'totals': totals, 'max_cycles': max(r['cycles'] for r in result_rows),
            'include': str(include), 'geometry_enabled': geometry, 'geometry_preparation_in_timing': geometry, 'header_sha256': header_hash, 'compile_command': command,
            'native_compile_command': host_command, 'native_binary_sha256': sha(host_binary),
            'run_command': run_command, 'elf_sha256': sha(elf), 'result_sha256': sha(result_file),
            'memory_sha256': sha(memory), 'generated_source_sha256': sha(rv_source),
            'fields_per_request':len(fields),'all_fields_match_native': True, 'native_undefined_behavior_sanitizer': True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--include', type=Path, default=ROOT / 'drivers')
    p.add_argument('--compare-include', type=Path)
    p.add_argument('--require-equivalent', action='store_true', help='Require every shared decision/cost field to match the comparison implementation.')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--gcc', default='riscv64-unknown-elf-gcc')
    p.add_argument('--host-cc', default='cc')
    p.add_argument('--simulator', type=Path, required=True)
    p.add_argument('--pool-bytes', type=int, default=12288)
    p.add_argument('--ia-bytes', type=int, default=2048)
    p.add_argument('--frames', type=int, default=16)
    p.add_argument('--image-cache-bytes', type=int, default=1024)
    p.add_argument('--shared-total-bytes', type=int, default=0)
    p.add_argument('--bank-bytes', type=int, default=2048)
    p.add_argument('--ia-bank-mask', type=lambda x:int(x,0), default=0x16)
    p.add_argument('--directory-rows', type=int, default=1024)
    args = p.parse_args()
    if args.require_equivalent and not args.compare_include:
        p.error('--require-equivalent requires --compare-include')
    for name in ('prepared', 'include', 'out', 'simulator'):
        setattr(args, name, getattr(args, name).resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    gcc = Path(shutil.which(args.gcc) or args.gcc).resolve()
    host_cc = Path(shutil.which(args.host_cc) or args.host_cc).resolve()
    rows, hashes = requests(args)
    for path in (Path(__file__).resolve(), TESTS / 'shapes.json', TESTS / 'start.S', TESTS / 'link.ld'):
        hashes[str(path)] = sha(path)
    simulator_hash = sha(args.simulator)
    started = time.monotonic()
    reports = {'current': measure('current', args.include, rows, args, gcc, host_cc, simulator_hash)}
    if args.compare_include:
        reports['comparison'] = measure('comparison', args.compare_include.resolve(), rows, args, gcc, host_cc, simulator_hash)
    assert hashes == {path: sha(path) for path in hashes}
    result = {'passed': True, 'requests': len(rows), 'fields_per_request':len(FIELDS),
              'scope': 'Cold geometry preparation and device/shared planner calls on PicoRV32. Requests use original tensor formats and quantization offsets; no inference timing is measured.',
              'reports': reports, 'input_sha256': hashes, 'compiler_sha256': sha(gcc),
              'host_compiler_sha256': sha(host_cc), 'simulator_sha256': simulator_hash,
              'elapsed_seconds': time.monotonic() - started}
    if 'comparison' in reports:
        equivalent = all(all(a['plan'][field] == b['plan'][field] for field in a['plan'].keys() & b['plan'].keys() if field != 'candidates_evaluated')
                         for a, b in zip(reports['current']['rows'], reports['comparison']['rows']))
        if args.require_equivalent:
            assert equivalent
            assert all(0 < a['plan']['candidates_evaluated'] <= b['plan']['candidates_evaluated']
                       for a, b in zip(reports['current']['rows'], reports['comparison']['rows']))
        result['comparison'] = {
            'equivalent_decision_and_cost_fields': equivalent,
            'decision_and_cost_fields_per_request':len(reports['current']['rows'][0]['plan'].keys() & reports['comparison']['rows'][0]['plan'].keys())-1,
            'changed_selections': sum(any(a['plan'][f] != b['plan'][f] for f in ('is_mode', 'tiling.ia_reuse', 'tiling.w_reuse', 'ps_control'))
                                      for a, b in zip(reports['current']['rows'], reports['comparison']['rows'])),
            'cycles_ratio_comparison_over_current': {str(policy): reports['comparison']['totals'][str(policy)] / reports['current']['totals'][str(policy)] for policy in (0, 1)},
        }
    (args.out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': True, 'totals': {name: r['totals'] for name, r in reports.items()}, 'report': str(args.out / 'summary.json')}))


if __name__ == '__main__':
    main()
