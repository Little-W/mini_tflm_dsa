#!/usr/bin/env python3
"""Verify RV32 command submission, DMA results, fence and accelerator reset."""
import argparse
import json
from pathlib import Path
import struct
import subprocess

from build_sim import ROOT, HERE, common, run_sim


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--simulator',type=Path,required=True)
    p.add_argument('--case-dir',type=Path,required=True)
    p.add_argument('--gcc',required=True)
    p.add_argument('--out',type=Path,required=True)
    a = p.parse_args()
    out, case = a.out.resolve(), a.case_dir.resolve()
    out.mkdir(parents=True,exist_ok=True)
    meta = json.loads((case/'metadata.json').read_text())
    profile=json.loads((a.simulator.resolve().parents[1]/'build.json').read_text())['profile']
    dma_max_bytes=profile['dma_max_bytes']
    for key, checksum in [('memory_file','memory_sha256'),('commands_file','commands_sha256'),
                          ('expected_output_file','expected_output_sha256')]:
        if common.digest(case/meta[key]) != meta[checksum]:
            raise ValueError('Command test input differs from its metadata')
    data = (case/meta['memory_file']).read_bytes()
    expected = (case/meta['expected_output_file']).read_bytes()
    address = meta['tensors']['output']['address']
    calls = []
    for line in (case/meta['commands_file']).read_text().splitlines():
        if line == 'FENCE':
            calls.append('gemmini_mmio_fence();')
        elif line:
            funct, rs1, rs2 = map(lambda word:int(word,0),line.split())
            calls.append(f'gemmini_mmio_command({funct},UINT64_C({rs1}),UINT64_C({rs2}));')
    source = out/'transport.c'
    source.write_text('''#include <stdint.h>
#include "mmio.h"
static const uint8_t input_image[] = {'''+','.join(map(str,data))+'''};
static const uint8_t expected[] = {'''+','.join(map(str,expected))+'''};
int main(void) {
    volatile uint32_t *const control=(volatile uint32_t *)0x20000000u;
    volatile uint32_t *const device=(volatile uint32_t *)GEMMINI_MMIO_BASE;
    volatile uint8_t *const memory=(volatile uint8_t *)'''+str(meta['memory_base'])+'''u;
    volatile uint8_t *const output=(volatile uint8_t *)'''+str(address)+'''u;
    if (device[8]!=0x474d0003u || device[9]!='''+str(dma_max_bytes)+'''u) return 1;
    control[3]=0xc0f10001u;
    for (unsigned iteration=0;iteration<2;iteration++) {
        for (unsigned i=0;i<sizeof(input_image);i++) memory[i]=input_image[i];
        '''+'\n        '.join(calls)+'''
        for (unsigned i=0;i<sizeof(expected);i++) if(output[i]!=expected[i]) return 2;
        device[10]=1u;
        if (device[0]&2u) return 3;
    }
    control[3]=0xc0f10002u;
    return 0;
}
''')
    elf, binary, mem = out/'transport.elf', out/'transport.bin', out/'transport.mem'
    command = [a.gcc,'-O3','-march=rv32im_zicsr','-mabi=ilp32','-ffreestanding',
               '-fno-builtin','-nostdlib','-nostartfiles','-I',str(HERE),
               str(ROOT/'veri/soc_csrc/start.S'),str(source),
               '-T',str(ROOT/'veri/soc_csrc/link.ld'),'-lgcc','-o',str(elf)]
    subprocess.run(command,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    objcopy = a.gcc.removesuffix('gcc')+'objcopy'
    subprocess.run([objcopy,'-O','binary',str(elf),str(binary)],check=True)
    raw = binary.read_bytes()
    if len(raw)>=meta['memory_base']:
        raise ValueError('Transport firmware overlaps accelerator test memory')
    raw += b'\0'*((-len(raw))%4)
    mem.write_text('\n'.join(f'{word[0]:08x}' for word in struct.iter_unpack('<I',raw))+'\n')
    report = run_sim(a.simulator,out/'run',mem,result_words=0,output_addr=address,
                     output_bytes=len(expected),output_addr_word=-1,output_bytes_word=-1,
                     timeout_cycles=2000000,timeout_seconds=120)
    observed = out/'run/output.bin'
    report['output_matches'] = observed.is_file() and observed.read_bytes()==expected
    report['passed'] &= report['output_matches']
    report['compile_command'] = command
    report['firmware_sha256'] = common.digest(binary)
    report['test_source_sha256'] = common.digest(source)
    report['transport_header_sha256'] = common.digest(HERE/'mmio.h')
    report['case_metadata_sha256'] = common.digest(case/'metadata.json')
    common.write_json(out/'summary.json',report)
    print(json.dumps({'passed':report['passed'],'output_bytes':len(expected),
                      'runs_with_accelerator_reset':2,'summary':str(out/'summary.json')},indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
