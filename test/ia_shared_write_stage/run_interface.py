#!/usr/bin/env python3
"""逐周期比较 IA 缓存与共享存储的写入、读出、复位和容量故障行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from helpers import ROOT, PARAMETERS, SOURCES, make_wrapper


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_testbench(path, ports):
    lines = ['module tb_shared_write_stage;']
    lines += [f'    localparam int {name}={value};' for name, value in PARAMETERS.items()]
    for direction, kind, name, array in ports:
        names = [name] if direction == 'input' else ['reference_' + name, 'current_' + name]
        lines += [f'    {kind} {signal} {array};' for signal in names]
    for label, enabled in [('reference', 0), ('current', 1)]:
        lines += [f'    cache_shared #(.p_shared_write_stage({enabled})) u_{label} (',
                  ',\n'.join(f'        .{name}({label + "_" if direction == "output" else ""}{name})'
                             for direction, _, name, _ in ports), '    );']
    lines += ['    longint cycles=0, comparisons=0, ia_writes=0, ps_writes=0, ia_reads=0, ps_reads=0;',
              '    int banks, active_slots, columns_per_command, ps_limit;',
              '    task automatic step;', '        clk=0; #2;',
              '        if (u_current.u_memory.ia_bank_write_en[1]) begin',
              '            assert (u_current.ram_shared_wr_data === u_current.u_memory.ia_bank_write_data[1])',
              '                else $fatal(1, "Shared IA write data differs before memory edge");',
              '        end',
              '        ia_writes += $countones(u_current.u_memory.ia_bank_write_en);',
              '        ps_writes += $countones(u_current.u_memory.ps_write_fire);',
              '        ia_reads += $countones(u_current.u_memory.ia_bank_read_en);',
              '        ps_reads += $countones(u_current.u_memory.ps_read_fire);',
              '        clk=1; #2; cycles++;']
    outputs = [name for direction, _, name, _ in ports if direction == 'output']
    for name in outputs:
        lines += [f'        assert (reference_{name} === current_{name}) else',
                  f'            $fatal(1, "Shared memory output differs: {name}, cycle=%0d", cycles);']
    original = ['ram_port_wr_en', 'ram_port_wr_addr', 'ram_port_wr_data', 'ram_port_wr_mask',
                'ram_port_rd_en', 'ram_port_rd_addr']
    for name in original:
        lines += [f'        assert (u_reference.{name} === u_current.{name}) else',
                  f'            $fatal(1, "Cache command differs: {name}, cycle=%0d", cycles);']
    lines += [f'        comparisons += {len(outputs) + len(original)};', '    endtask',
              '    task automatic idle;',
              "        i_cfg_valid=0; i_ps_read_en=0; i_ps_write_en=0; l1_start=0;",
              '        for(int lane=0;lane<8;lane++) wr_valid[lane]=0;', '    endtask',
              '    task automatic ps_activity;',
              '        for(int channel=0;channel<4;channel++) begin',
              '            i_ps_read_en[channel]=$urandom_range(0,1);',
              '            i_ps_write_en[channel]=$urandom_range(0,1);',
              "            i_ps_read_addr[channel]=12'($urandom_range(0,ps_limit-1));",
              "            i_ps_write_addr[channel]=12'($urandom_range(0,ps_limit-1));",
              '            if(i_ps_read_addr[channel]==i_ps_write_addr[channel])',
              "                i_ps_write_addr[channel]=12'((int'(i_ps_write_addr[channel])+1)%ps_limit);",
              '            i_ps_write_data[channel]={$urandom,$urandom,$urandom,$urandom};',
              '        end', '    endtask',
              '    initial begin',
              '        clk=0; rst_n=0; compact_mode=0; compact_offset=0; cfg_cache_blocks=16;',
              '        slot_base=0; wr_slot=0; wr_row=0; wr_col_base=0; wr_use_16bits=0;',
              '        l1_slot_start=0; l1_slot_end=0; l1_is_init=0; l1_calc_done=0; i_cfg_ia_banks=1;',
              "        for(int lane=0;lane<8;lane++) wr_data[lane]=0;",
              '        for(int slot_index=0;slot_index<SLOT_BLOCKS;slot_index++) slot_rows[slot_index]=16;',
              '        for(int channel=0;channel<4;channel++) begin',
              '            i_ps_read_addr[channel]=0; i_ps_write_addr[channel]=0; i_ps_write_data[channel]=0;',
              '        end', '        idle(); step(); step();',
              '        for(int round=0;round<12;round++) begin',
              '            idle(); repeat(4) step();',
              '            if(round%4==0) begin rst_n=0; step(); step(); end',
              '            rst_n=1;',
              '            banks=round%4==0 ? 1 : 2;',
              '            compact_mode=round%4<2;',
              '            wr_use_16bits=round%4==2;',
              '            compact_offset=16\'($signed($urandom_range(0,255))-127);',
              '            cfg_cache_blocks=16*banks;',
              '            active_slots=16*banks*(compact_mode ? 2 : 1);',
              '            columns_per_command=wr_use_16bits ? 4 : 8;',
              '            ps_limit=(7-banks)*128;',
              "            i_cfg_ia_banks=3'(banks); i_cfg_valid=1; step(); i_cfg_valid=0; step();",
              '            assert(!current_o_capacity_fault) else $fatal(1,"Configuration failed");',
              '            for(int command=0;command<active_slots*16*(16/columns_per_command);command++) begin',
              "                wr_slot=6'(command/(16*(16/columns_per_command)));",
              "                wr_row=4'((command/(16/columns_per_command))%16);",
              "                wr_col_base=4'((command%(16/columns_per_command))*columns_per_command);",
              "                if(wr_use_16bits && command%13==0) wr_col_base=4'($urandom_range(0,15));",
              '                for(int lane=0;lane<8;lane++) begin',
              "                    wr_data[lane]=16'($urandom);",
              '                    wr_valid[lane]=$urandom_range(0,7)!=0 && (lane<4 || !wr_use_16bits);',
              '                end', '                ps_activity(); step();',
              '                assert(!current_o_capacity_fault) else $fatal(1,"Write phase capacity fault");',
              '            end',
              '            idle(); repeat(4) step();',
              "            l1_slot_start=0; l1_slot_end=6'(active_slots-1);",
              '            l1_is_init=round[0]; l1_calc_done=round[1]; l1_start=1; step(); l1_start=0;',
              '            for(int read_cycle=0;read_cycle<active_slots*16+8;read_cycle++) begin',
              '                ps_activity(); step();',
              '                assert(!current_o_capacity_fault) else $fatal(1,"Read phase capacity fault");',
              '            end',
              '            idle(); repeat(4) step();',
              "            i_ps_read_en=1; i_ps_write_en=1; i_ps_read_addr[0]=0; i_ps_write_addr[0]=0; step();",
              '            assert(current_o_capacity_fault) else $fatal(1,"Expected collision fault");',
              '            repeat(4) begin ps_activity(); step(); end',
              '            idle(); repeat(2) step(); i_cfg_valid=1; step(); i_cfg_valid=0; step();',
              '            assert(!current_o_capacity_fault) else $fatal(1,"Configuration did not clear fault");',
              '        end',
              '        assert(ia_writes>10000 && ia_reads>5000 && ps_writes>10000 && ps_reads>10000)',
              '            else $fatal(1,"Insufficient active memory operations");',
              '        $display("IA_SHARED_WRITE_STAGE_PASS cycles=%0d comparisons=%0d ia_writes=%0d ia_reads=%0d ps_writes=%0d ps_reads=%0d",',
              '                 cycles,comparisons,ia_writes,ia_reads,ps_writes,ps_reads);',
              '        $finish;', '    end', 'endmodule']
    path.write_text('\n'.join(lines) + '\n')
    return outputs, original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    wrapper, tb = out / 'cache_shared.sv', out / 'tb_shared_write_stage.sv'
    ports = make_wrapper(wrapper)
    outputs, commands = make_testbench(tb, ports)
    sources = [ROOT / path for path in SOURCES] + [ROOT / 'rtl/common/regfile.v',
               ROOT / 'rtl/common/pseudo_dual_port_ram.v', wrapper, tb]
    hashes = {str(path): digest(path) for path in sources}
    command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal', '-j', '1',
               '--top-module', 'tb_shared_write_stage', '--Mdir', str(out / 'obj'), *map(str, sources)]
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(out / 'obj/Vtb_shared_write_stage')], cwd=ROOT, capture_output=True, text=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    match = re.search(r'IA_SHARED_WRITE_STAGE_PASS (.*)', result.stdout)
    if result.returncode or not match:
        raise RuntimeError(result.stdout + result.stderr)
    if hashes != {str(p): digest(p) for p in sources}:
        raise RuntimeError('Sources changed during verification')
    report = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match[1])}
    report.update(passed=True, source_sha256=hashes, compared_outputs=outputs,
                  compared_cache_commands=commands, binary_sha256=digest(out / 'obj/Vtb_shared_write_stage'))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
