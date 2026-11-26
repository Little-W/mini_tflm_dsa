#!/usr/bin/env python3
"""证明完整向量引擎在每次 CHECK 清除之后先接收共享数据再使用数据。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--source-root', type=Path, default=ROOT)
args = parser.parse_args()
SOURCE_ROOT = args.source_root.resolve()
OUT = args.out.resolve()
OUT.mkdir(parents=True, exist_ok=True)
source = SOURCE_ROOT/'rtl/npu/conv/vector_engine.sv'
original = source.read_text()
text = original.replace('module vector_engine #(', 'module vector_epoch_property #(', 1)
text = text.replace('endmodule', '''
  // 每次控制器清除任务状态后，记录本任务已接收的共享存储返回。
  logic proof_reset_seen = 1'b0;
  logic proof_seen_ps, proof_seen_weight;
  always_ff @(posedge clk) begin
    if (!rst_n) proof_reset_seen <= 1'b1;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      proof_seen_ps <= 1'b0;
      proof_seen_weight <= 1'b0;
    end else if (state == CHECK) begin
      proof_seen_ps <= 1'b0;
      proof_seen_weight <= 1'b0;
    end else begin
      if (i_ps_read_valid) proof_seen_ps <= 1'b1;
      if (i_weight_read_valid) proof_seen_weight <= 1'b1;
    end
  end
  wire proof_ps_use = dw_quant_start || quant_req_valid ||
      (depthwise && !SHARED_QUANT_ENABLE && state != IDLE &&
       !state_failed && state != DONE && !dw_quant_start && dw_quant_input_active);
  (* keep = 1 *) wire proof_ps_epoch = !proof_reset_seen ||
      ((!proof_ps_use || proof_seen_ps || i_ps_read_valid) &&
       (!g_shared_snapshot.data_valid || proof_seen_ps) &&
       (!dw_quant_input_active || proof_seen_ps));
  (* keep = 1 *) wire proof_weight_epoch = !proof_reset_seen ||
      ((!dw_issue_fire || proof_seen_weight || i_weight_read_valid) &&
       (!u_operand_store.g_shared_weights.saved_valid || proof_seen_weight));
endmodule''', 1)
model = OUT/'vector_epoch_property.sv'
model.write_text(text)
resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
sources = resolve([model], SOURCE_ROOT)
profiles = []
for synthesis in (False, True):
    for shared in (False, True):
        key = ('synthesis' if synthesis else 'generic') + ('_shared' if shared else '_local')
        options = ['-GTILE=16', '-GBUS_WIDTH=64', '-GPE_COUNT=8', '-GWINDOW_LANES=8',
                   '-GSHARED_STORAGE_ENABLE=1', '-GSHARED_QUANT_ENABLE='+str(int(shared)),
                   '-GSHARED_STORAGE_ADDR_WIDTH=12']
        if synthesis:
            options += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        script = OUT/(key+'.ys')
        script.write_text('\n'.join([
            'read_slang --top vector_epoch_property '+shlex.join(options+list(map(str, sources))),
            'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
            'prep -top vector_epoch_property -flatten',
            'delete -output w:*', 'expose w:proof_ps_epoch w:proof_weight_epoch',
            'opt -full', 'memory_map', 'async2sync', 'opt -full',
            'sat -tempinduct -seq 2 -maxsteps 8 -prove proof_ps_epoch 1 -prove proof_weight_epoch 1 -verify',
        ])+'\n')
        log = OUT/(key+'.log')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                           check=True, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
        assert 'Induction step proven' in log.read_text()
        profiles.append({'profile': key, 'passed': True, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print(key+' PASS', flush=True)
report = {'passed': True, 'external_inputs_constrained': False,
          'parameters': 'TILE=16, BUS_WIDTH=64, PE_COUNT=8, WINDOW_LANES=8, SHARED_STORAGE_ENABLE=1',
          'scope': 'After observing reset and after each CHECK state clearing edge',
          'source_sha256': {str(p.relative_to(SOURCE_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sources if p != model and p.is_relative_to(SOURCE_ROOT)},
          'property_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
          'test_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'original_vector_engine_sha256': hashlib.sha256(original.encode()).hexdigest(), 'profiles': profiles}
report['source_sha256']['rtl/npu/conv/vector_engine.sv'] = report['original_vector_engine_sha256']
(OUT/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
