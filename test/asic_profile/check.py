#!/usr/bin/env python3
"""检查生产配置准备、不同端点导出和 SRAM 诊断脚本，不调用 DC。"""
from pathlib import Path
import argparse
import csv
import hashlib
import importlib.util
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, default=ROOT/'build/asic_profile_test')
args = parser.parse_args()
OUT = args.out.resolve()
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT/'scripts/asic'))
spec = importlib.util.spec_from_file_location('npu_synthesis_profile', ROOT/'scripts/asic/run_ps_synthesis.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)
checks = []


def checked(name, condition):
    assert condition, name
    checks.append(name)


prepared = OUT/'prepared'
run = subprocess.run([sys.executable, str(ROOT/'scripts/asic/run_ps_synthesis.py'),
    '--profile', 'npu_r16_150', '--prepare-only', '--out', str(prepared)],
    cwd=ROOT, text=True, capture_output=True)
(OUT/'prepare.log').write_text(run.stdout+run.stderr)
checked('prepare_only_exit', run.returncode == 0)
manifest = json.loads((prepared/'run.json').read_text())
parameters = manifest['parameters']
for name, value in {'SIZE':16,'BUS_WIDTH':64,'ADDR_WIDTH':19,'SHARED_BANK_BYTES':8192,
    'SHARED_BANK_COUNT':7,'IA_CACHE_BLOCKS':4,'IM2COL_CACHE_BYTES':4096,'PS_FRAME_COUNT':16,
    'AXI_READ_OUTSTANDING':4,'AXI_WRITE_OUTSTANDING':4,'DW_PE_COUNT':16,
    'VECTOR_PE_COUNT':16,'WINDOW_LANES':16}.items():
    checked('parameter_'+name, parameters[name] == value)
checked('dc_not_executed', manifest['dc_executed'] is False and manifest['execution_status']=='NOT_RUN'
        and manifest['passed'] is None)
checked('area_frequency_raw', manifest['area_target']==3500000 and manifest['frequency_mhz']==150
        and manifest['force_raw'] is True and manifest['ps_pool_bytes']==49152)
checked('requested_paths', manifest['setup_path_count']>=5000 and manifest['hold_path_count']>=5000)
checked('snapshot_hashes', all(hashlib.sha256((prepared/name).read_bytes()).hexdigest()==digest
        for name,digest in manifest['snapshot_sha256'].items()))
checked('constraints_unchanged', (prepared/'flow/constraints/npu_top.sdc').read_bytes()==
        (ROOT/'asic/synthesis/constraints/npu_top.sdc').read_bytes())
checked('common_compare_in_filelist', 'rtl/common/unsigned_compare.sv' in (prepared/'sources/sources.f').read_text())
checked('sram_wrapper_copied', (prepared/'sources/asic/rtl/smic40_sram_1r1w.sv').is_file())
environment = json.loads((prepared/'environment.json').read_text())
checked('compile_defines', 'GEMMORA_PS_POOL_BYTES=49152' in environment['DESIGN_RTL_DEFINES'] and
        '+GEMMORA_PS_FORCE_RAW' in environment['DESIGN_RTL_DEFINES'])
roundtrip = OUT/'tcl_roundtrip.tcl'
special = 'directory with $literal [square] {brace} "quote" \\ slash\nnext'
roundtrip.write_text('set value '+flow.tcl_string(special)+'\nputs -nonewline $value\n')
result = subprocess.run(['tclsh',str(roundtrip)],capture_output=True,text=True)
checked('tcl_literal_roundtrip', result.returncode==0 and result.stdout==special)
wrapper = OUT/'prepared_tcl.tcl'
wrapper.write_text('rename source actual_source\nproc source {args} {return}\nactual_source '+
    flow.tcl_string(prepared/'run.tcl')+'\nputs $::env(DESIGN_PARAMETERS)\nputs $::env(DESIGN_TARGET_FREQ_MHZ)\n')
result = subprocess.run(['tclsh',str(wrapper)],capture_output=True,text=True)
checked('prepared_tcl_execution', result.returncode==0 and 'SHARED_BANK_BYTES=8192' in result.stdout and
        result.stdout.rstrip().endswith('150'))

mock = r'''
proc getenv_default {name default} {if {[info exists ::env($name)]} {return $::env($name)};return $default}
proc sizeof_collection {collection} {return [llength $collection]}
proc index_collection {collection index} {return [lindex $collection $index]}
proc foreach_in_collection {variable collection body} {uplevel 1 [list foreach $variable $collection $body]}
proc get_object_name {object} {return $object}
proc get_timing_paths {args} {
    if {[lsearch -exact $args -nworst] < 0 || [lindex $args [expr {[lsearch -exact $args -nworst]+1}]] != 1} {
        error "Expected one path per endpoint"
    }
    set limit [lindex $args [expr {[lsearch -exact $args -max_paths]+1}]]
    set mode [lindex $args [expr {[lsearch -exact $args -delay_type]+1}]]
    set paths {}
    for {set i 0} {$i < 6005} {incr i} {
        lappend paths path_${mode}_${i}_a
        if {$i % 200 == 0} {lappend paths path_${mode}_${i}_b}
    }
    return [lrange $paths 0 [expr {$limit-1}]]
}
proc get_attribute {object name} {
    if {[regexp {^path_(max|min)_([0-9]+)_([ab])$} $object match mode number suffix]} {
        switch -- $name {
            slack {return [expr {$number/1000.0-0.125+($suffix eq "b"?0.0001:0.0)}]}
            startpoint {return src_$number}
            endpoint {return dst_$number}
            path_group {return CORE_CLK}
            logic_depth {return 2}
            cell_delay {return 0.12}
            net_delay {return 0.01}
            points {return [list point_$number]}
        }
    }
    if {[string match point_* $object]} {
        switch -- $name {
            object {return pin_$object}
            arrival {return 0.13}
            delay {return 0.12}
        }
    }
    if {$object eq "macro" && $name eq "ref_name"} {return RAMTP128X16}
    if {[string match arc_* $object]} {
        if {$name eq "timing_type"} {return hold_rising}
        if {$name eq "when"} {return {!COLLDISN}}
    }
    if {$name eq "case_value"} {return 1}
    error "Unavailable attribute $name on $object"
}
proc get_cells {args} {if {[lsearch -exact $args -hierarchical]>=0} {return macro};return {}}
proc get_libs {args} {return RAMTP128X16_tt}
proc get_lib_cells {args} {return RAMTP128X16_tt/RAMTP128X16}
proc get_lib_pins {args} {return [lindex $args end]}
proc get_lib_timing_arcs {args} {return arc_hold}
proc get_pins {args} {return [lindex $args end]}
proc get_nets {args} {return clk}
proc get_clocks {args} {return CORE_CLK}
proc redirect {args} {
    set path [lindex $args [expr {[lsearch -exact $args -file]+1}]]
    set handle [open $path w];puts $handle "Mock library timing report";close $handle
}
proc report_timing {args} {
    set path [lindex $args [expr {[lsearch -exact $args >]+1}]]
    set handle [open $path w];puts $handle "Mock detailed timing report";close $handle
}
'''
mock_out = OUT/'mock_reports'
mock_out.mkdir(exist_ok=True)
mock += '\nset PROJ_TEMP '+flow.tcl_string(mock_out)+'\n'
mock += 'set PROJ_PATH '+flow.tcl_string(ROOT/'asic/synthesis')+'\nset DESIGN_TOP npu_top\n'
mock += 'set ::env(DESIGN_SETUP_PATH_COUNT) 5000\nset ::env(DESIGN_HOLD_PATH_COUNT) 5000\n'
mock += 'source '+flow.tcl_string(ROOT/'asic/synthesis/scripts/8_endpoint_paths.tcl')+'\n'
mock_file = OUT/'mock_reports.tcl'
mock_file.write_text(mock)
result = subprocess.run(['tclsh',str(mock_file)],capture_output=True,text=True)
(OUT/'mock_reports.log').write_text(result.stdout+result.stderr)
checked('tcl_report_execution', result.returncode==0)
for name in ('setup','hold'):
    with (mock_out/f'npu_top_{name}_paths.csv').open() as source:
        rows=list(csv.DictReader(source))
    checked(name+'_5000_distinct', len(rows)==5000 and len({row['endpoint'] for row in rows})==5000)
    checked(name+'_slack_order', all(float(left['slack_ns'])<=float(right['slack_ns'])
            for left,right in zip(rows,rows[1:])))
    checked(name+'_point_details', 'pin_point_' in (mock_out/f'npu_top_{name}_paths.rpt').read_text())
arc_rows=list(csv.DictReader((mock_out/'npu_top_sram_clock_arcs.tsv').open(),delimiter='\t'))
checked('both_clock_arc_directions', {(row['from_pin'],row['to_pin']) for row in arc_rows}==
        {('CLKA','CLKB'),('CLKB','CLKA')})
checked('conditional_arc_export', all(row['timing_type']=='hold_rising' and row['when']=='!COLLDISN'
        and row['status']=='EXPORTED' for row in arc_rows))
checked('same_net_diagnostic', 'CLKA/CLKB same net = 1' in
        (mock_out/'npu_top_sram_clock_diagnostics.rpt').read_text())
fallback_out = OUT/'mock_fallback'
fallback_out.mkdir(exist_ok=True)
fallback_file = OUT/'mock_fallback.tcl'
fallback_file.write_text(mock+'\nrename get_lib_timing_arcs {}\nset PROJ_TEMP '+
    flow.tcl_string(fallback_out)+'\nsource '+
    flow.tcl_string(ROOT/'asic/synthesis/scripts/9_sram_clock_arcs.tcl')+'\n')
result = subprocess.run(['tclsh',str(fallback_file)],capture_output=True,text=True)
checked('unsupported_arc_query_fallback', result.returncode==0 and 'SEE_LIBRARY_REPORT' in
        (fallback_out/'npu_top_sram_clock_arcs.tsv').read_text())

(mock_out/'npu_top_area.rpt').write_text('Total cell area: 4188765.246236\n')
(mock_out/'npu_top_summary.rpt').write_text('setup_result: PASS\nhold_result: FAIL\n')
targets=flow.report_targets(mock_out,3500000,5000,True)
checked('area_and_hold_failures_visible', targets['area_met'] is False and targets['hold_met'] is False
        and targets['setup_met'] is True and targets['setup_coverage_met'] is True
        and targets['hold_coverage_met'] is True)
checked('hold_coverage_requirement', flow.report_targets(mock_out,3500000,5000,True,5001)['hold_coverage_met'] is False)
(mock_out/'synthesis.log').write_text('Warning: Undriven port. (LINT-3)\n  net_name\n\n')
checked('warning_context', flow.collect_diagnostics(mock_out)[0]['text'].endswith('net_name'))
legacy_out = OUT/'legacy_prepared'
result = subprocess.run([sys.executable,str(ROOT/'scripts/asic/run_ps_synthesis.py'),
    '--prepare-only','--out',str(legacy_out)],capture_output=True,text=True)
checked('legacy_prepare', result.returncode==0)
legacy = json.loads((legacy_out/'run.json').read_text())
checked('legacy_defaults', legacy['parameters']['SHARED_BANK_BYTES']==2048 and
        legacy['parameters']['SHARED_BANK_COUNT']==9 and legacy['parameters']['IA_CACHE_BLOCKS']==2 and
        legacy['parameters']['PS_FRAME_COUNT']==4 and legacy['frequency_mhz']==50 and not legacy['force_raw'])
result = subprocess.run([sys.executable,str(ROOT/'scripts/asic/run_ps_synthesis.py'),
    '--profile','npu_r16_150','--prepare-only','--setup-paths','4999','--out',str(OUT/'invalid')],
    capture_output=True,text=True)
checked('production_endpoint_count_validation', result.returncode!=0 and
        'at least 5000 setup endpoints' in result.stderr)
prior_out=OUT/'existing_results'
prior_out.mkdir(exist_ok=True)
prior_report=prior_out/'npu_top_summary.rpt'
prior_report.write_text('Completed synthesis summary\n')
result=subprocess.run([sys.executable,str(ROOT/'scripts/asic/run_ps_synthesis.py'),
    '--profile','npu_r16_150','--prepare-only','--out',str(prior_out)],capture_output=True,text=True)
checked('existing_results_preserved', result.returncode!=0 and 'contains DC results' in result.stderr
        and prior_report.read_text()=='Completed synthesis summary\n' and not (prior_out/'run.json').exists())
for name in ('8_endpoint_paths.tcl','9_sram_clock_arcs.tcl'):
    text=(ROOT/'asic/synthesis/scripts'/name).read_text()
    checked(name+'_read_only_constraints', not any(command in text for command in
        ('set_false_path','set_disable_timing','set_clock_uncertainty','remove_clock')))
summary=dict(passed=True,dc_executed=False,check_count=len(checks),checks=checks,
    scope='Python prepare-only and Tcl command-model tests; no DC or technology library execution.',
    production_prepare=str(prepared))
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary))
