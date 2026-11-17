#!/usr/bin/env python3
"""Verify physical AXI RAM inference and FPGA firmware initialization."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
RAM = ROOT/'rtl/soc/soc_axi_ram.sv'
CONVERTER = ROOT/'fpga/vivado/tflm_ai_dsa_soc/scripts/cpu_memory.tcl'
CPU_WORDS = 1024


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log, *, success=True):
    result = subprocess.run(list(map(str, command)), cwd=ROOT, text=True,
                            capture_output=True, timeout=180)
    log.write_text(result.stdout + result.stderr)
    if (result.returncode == 0) != success:
        raise RuntimeError(f'Unexpected command status {result.returncode}: {log}')
    return result


def memories(netlist):
    rows = []
    for module, body in netlist['modules'].items():
        for name, cell in body.get('cells', {}).items():
            if cell['type'] != '$mem_v2':
                continue
            parameters = cell['parameters']
            rows.append(dict(module=module, name=name,
                width=int(parameters['WIDTH'], 2), size=int(parameters['SIZE'], 2),
                read_ports=int(parameters['RD_PORTS'], 2),
                write_ports=int(parameters['WR_PORTS'], 2),
                read_clock_mask=int(parameters['RD_CLK_ENABLE'], 2),
                write_clock_mask=int(parameters['WR_CLK_ENABLE'], 2),
                initialization=parameters['INIT']))
    return rows


def decode_words(bits, width):
    return [int(bits[len(bits)-(index+1)*width:len(bits)-index*width], 2)
            for index in range(len(bits)//width)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--yosys', default='yosys')
    parser.add_argument('--tclsh', default='tclsh')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_paths = [RAM, CONVERTER, Path(__file__).resolve(),
                    ROOT/'fpga/vivado/tflm_ai_dsa_soc/rtl/fpga_top.sv']
    before = {str(path.relative_to(ROOT)): digest(path) for path in source_paths}
    ports = RAM.read_text().split(') (', 1)[1].split('\n);', 1)[0]
    original = [((index * 0x10204081) ^ 0xa5c3e109) & 0xffffffff
                for index in range(CPU_WORDS)]
    full = out/'firmware32.mem'
    full.write_text(''.join(f'{word:08x}\n' for word in original))
    directed = out/'firmware32_directives.mem'
    directed.write_text(full.read_text() + '/* replace CPU words */\n'
        '@0\n0102_0304 8899_aabb\n@3\n7654_3210 fedc_ba98\n'
        '@3fe\naabb_ccdd 1234_5678 // final physical RAM row\n')
    replaced = list(original)
    for address, value in {0:0x01020304, 1:0x8899aabb, 3:0x76543210,
                           4:0xfedcba98, 1022:0xaabbccdd, 1023:0x12345678}.items():
        replaced[address] = value
    convert = out/'convert.tcl'
    convert.write_text('source [lindex $argv 0]\n'
                       'puts [cpu_memory::write_images {*}[lrange $argv 1 end]]\n')
    cases = [('axi32', 32, 32, full, original, 1),
             ('axi64', 64, 64, full, original, 1),
             ('axi64_address_directives', 64, 64, directed, replaced, 1),
             ('initialization_disabled', 64, 32, full, None, 0),
             ('no_initialization_file', 64, 32, None, None, 1)]
    reports = []
    for name, width, image_width, source_image, expected_cpu, init in cases:
        directory = out/name
        directory.mkdir(exist_ok=True)
        image = directory/'native.mem'
        conversion = []
        if source_image is not None:
            conversion = [args.tclsh, convert, CONVERTER, source_image,
                          directory/'cpu32.mem', image, CPU_WORDS, width]
            execute(conversion, directory/'conversion.log')
        image_path = str(image) if source_image is not None else ''
        wrapper = directory/'ram_init_check.sv'
        wrapper.write_text(f'module ram_init_check #(parameter int DW={width}, AW=32) (' + ports + '\n);\n'
            f'soc_axi_ram #(.DP({CPU_WORDS*32//width}), .DW(DW), .AW(AW), '
            f'.MEM_PATH("{image_path}"), .MEM_WORD_WIDTH({image_width}), .INIT_EN({init})) '
            'u_ram (.*);\nendmodule\n')
        script = directory/'infer.ys'
        script.write_text(f'read_slang --top ram_init_check -D SYNTHESIS {RAM} {wrapper}\n'
            'opt\nmemory_dff\nmemory_share\nopt_clean\nmemory_collect\ncheck -assert\nstat\n'
            f'write_json {directory/"inferred.json"}\n')
        command = [args.yosys, '-Q', '-T', '-s', script]
        execute(command, directory/'inference.log')
        inventory = memories(json.loads((directory/'inferred.json').read_text()))
        data = [row for row in inventory if row['name'].endswith('mem_r')]
        assert len(data) == 1
        data = data[0]
        assert (data['width'], data['size']) == (width, CPU_WORDS*32//width)
        assert data['read_ports'] == data['write_ports'] == 1
        assert data['read_clock_mask'] == data['write_clock_mask'] == 1
        assert not any('initial_words' in row['name'] for row in inventory)
        initialized_words = 0
        expected = None
        if expected_cpu is None:
            assert set(data['initialization']) == {'x'}
        else:
            expected = expected_cpu if width == 32 else [
                expected_cpu[index] | expected_cpu[index+1] << 32
                for index in range(0, CPU_WORDS, 2)]
            assert decode_words(data['initialization'], width) == expected
            initialized_words = len(expected)
        for row in inventory:
            row['initialization_sha256'] = hashlib.sha256(row.pop('initialization').encode()).hexdigest()
        reports.append(dict(name=name, passed=True, data_bits=width,
            image_word_bits=image_width, init_en=init, command=list(map(str, command)),
            conversion_command=list(map(str, conversion)), memories=inventory,
            initialization_words_checked=initialized_words,
            first_words=[f'{word:0{width//4}x}' for word in expected[:4]] if expected else [],
            image_sha256=digest(image) if source_image is not None else None))
        print(f'{name}: PASS ({initialized_words} physical initialization words)', flush=True)

    invalid = out/'invalid_image_width'
    invalid.mkdir(exist_ok=True)
    wrapper = invalid/'ram_init_check.sv'
    wrapper.write_text((out/'axi64/ram_init_check.sv').read_text().replace(
        '.MEM_WORD_WIDTH(64)', '.MEM_WORD_WIDTH(32)'))
    command = [args.yosys, '-Q', '-T', '-p',
               f'read_slang --top ram_init_check -D SYNTHESIS {RAM} {wrapper}']
    rejected = execute(command, invalid/'inference.log', success=False)
    assert 'Synthesis memory image width' in rejected.stdout + rejected.stderr

    mapping = out/'xilinx7'
    mapping.mkdir(exist_ok=True)
    script = mapping/'map.ys'
    script.write_text(f'read_json {out/"axi64/inferred.json"}\n'
        'synth_xilinx -top ram_init_check -family xc7 -noiopad -noclkbuf\n'
        'check -assert\nstat\n' + f'write_json {mapping/"mapped.json"}\n')
    command = [args.yosys, '-Q', '-T', '-s', script]
    execute(command, mapping/'mapping.log')
    mapped = json.loads((mapping/'mapped.json').read_text())['modules']['ram_init_check']['cells']
    brams = {name: cell for name, cell in mapped.items()
             if cell['type'].startswith(('RAMB18', 'RAMB36'))}
    assert len(brams) == 1
    bram = next(iter(brams.values()))
    assert bram['type'] == 'RAMB36E1'
    initialization = ''.join(bram['parameters'][f'INIT_{index:02X}']
                             for index in reversed(range(128)))
    expected64 = [original[index] | original[index+1] << 32
                  for index in range(0, CPU_WORDS, 2)]
    assert decode_words(initialization, 64) == expected64
    unchanged = all(digest(ROOT/path) == value for path, value in before.items())
    assert unchanged
    summary = dict(passed=True, source_sha256=before, sources_unchanged=unchanged,
        yosys=args.yosys, cases=reports, rejected_mismatched_image_width=True,
        total_physical_initialization_words_checked=sum(row['initialization_words_checked'] for row in reports),
        xilinx7=dict(command=list(map(str, command)), physical_ram='RAMB36E1',
            block_ram_cells=1, logical_data_ram_bits=32768, allocated_block_ram_bits=36864,
            initialization_words_checked=512, temporary_initialization_ram_cells=0),
        word_order='physical_word[i] = (cpu_word[2*i+1] << 32) | cpu_word[2*i]')
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({'passed':True, 'cases':len(reports), 'mapped_ram':'1 RAMB36E1',
                      'mapped_initialization_words_checked':512}), flush=True)


if __name__ == '__main__':
    main()
