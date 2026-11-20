#!/usr/bin/env python3
"""从实际时序过程提取通道写入，证明配置和描述符接收的全部优先级。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

SOURCE = 'rtl/npu/conv/conv_im2col_frontend.sv'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def uncomment(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


class Statements:
    """保持 begin、if 和 case 结构，只去除不写 ch_q 的语句。"""
    def __init__(self, text):
        self.text = uncomment(text)
        self.pos = 0

    def space(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def word(self, value):
        self.space()
        return re.match(re.escape(value) + r'\b', self.text[self.pos:]) is not None

    def take(self, value):
        assert self.word(value), self.text[self.pos:self.pos+100]
        self.pos += len(value)

    def balanced(self):
        self.space()
        assert self.text[self.pos] == '('
        start = self.pos
        depth = 0
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            depth += (char == '(') - (char == ')')
            if depth == 0:
                return self.text[start:self.pos]
        raise RuntimeError('表达式括号未闭合')

    def parse(self):
        self.space()
        if self.word('begin'):
            self.take('begin')
            items = []
            while not self.word('end'):
                items.append(self.parse())
            self.take('end')
            selected = [item for item in items if item]
            return 'begin\n' + '\n'.join(selected) + '\nend' if selected else ''
        if self.word('if'):
            self.take('if')
            cond = self.balanced()
            yes = self.parse()
            no = ''
            if self.word('else'):
                self.take('else')
                no = self.parse()
            if not yes and not no:
                return ''
            return 'if ' + cond + ' ' + (yes or 'begin end') + (' else ' + no if no else '')
        if self.word('case'):
            self.take('case')
            expr = self.balanced()
            items = []
            while not self.word('endcase'):
                self.space()
                start = self.pos
                self.pos = self.text.index(':', start) + 1
                label = self.text[start:self.pos]
                value = self.parse()
                if value:
                    items.append(label + ' ' + value)
            self.take('endcase')
            return 'case ' + expr + '\n' + '\n'.join(items) + '\ndefault: ;\nendcase' if items else ''
        if self.word('for'):
            self.take('for')
            expr = self.balanced()
            body = self.parse()
            assert not body, '通道写入不应位于循环中'
            return ''
        start = self.pos
        self.pos = self.text.index(';', start) + 1
        raw = self.text[start:self.pos]
        return raw if re.match(r'ch_q\s*<=', raw) else ''


def process(text, channel=False):
    if channel:
        first = text.index('  // 通道位置先完成流式和解码更新，再选择同周期接收的快速描述符。')
        first = text.index('  always_ff', first)
    else:
        first = text.index('  always_ff @(posedge clk or negedge rst_n) begin\n    if (!rst_n) begin\n      state<=IDLE;')
    body = text.index('begin', first)
    parser = Statements(text[body:])
    reduced = parser.parse()
    # 无注释文本的偏移仅用于取得过程原文范围。
    clean = uncomment(text[first:])
    body_clean = clean.index('begin')
    scan = Statements(clean[body_clean:])
    scan.parse()
    raw = clean[:body_clean + scan.pos]
    return raw, reduced


def ready(text):
    start = text.index('  if (p_cfg_idle_use_lut) begin : g_cfg_idle_lut')
    stop = text.index('  assign finishing_tile=', start)
    body = text[start:stop]
    for signal in ('wr_last', 'finishing_tile', 'tile_ready_context', 'tile_ready', 'wr_valid'):
        match = re.search(r'  assign ' + signal + r'\s*=.*?;', text, re.S)
        if match is not None:
            body += match[0] + '\n'
    return body


PORTS = [
    ('rst_n','1'), ('state','5'), ('cfg_valid','1'), ('cache_cfg_ready','1'),
    ('cfg_prepare_phase','2'), ('address_step_phase','2'), ('prefetch_phase','4'),
    ('pred_busy','1'), ('pred_cfg_busy','1'), ('pred_cfg_pending','1'),
    ('cache_cfg_pending','1'), ('cache_hint_pending','1'), ('request_pending','1'),
    ('configured','1'), ('error','1'), ('tile_valid','1'), ('tile_rows','RW'), ('tile_cols','RW'),
    ('tile_q_before_end','1'), ('tile_rows_in_range','1'), ('incoming_fast','1'), ('incoming_ch','32'),
    ('cache_rsp_valid','1'), ('cache_rsp_error','1'), ('wr_ready','1'),
    ('chunk_reaches_end','1'), ('row_last_q','1'), ('ch0_q','16'), ('col_idx','TILE_COUNT_W'),
    ('active_cols_q','TILE_COUNT_W'), ('chunk_count','CHUNK_COUNT_W'), ('active_remaining','TILE_COUNT_W'),
    ('group_end_o_equal','1'), ('next_channel','16'), ('q0','32'), ('group_shape_o_valid','1'),
    ('group_c','16'), ('current_q_remainder','16'), ('decode_index','32'), ('decode_inner','32'), ('prior_channel','16')
]


def unit(text, label, channel=False, registered=False):
    _, body = process(text, channel)
    body = re.sub(r'\bch_q\s*<=', 'channel_nxt =', body)
    state_enum = re.search(r'  typedef enum logic \[4:0\].*?} st_t;', text, re.S)[0]
    header = 'module ' + label + ' #(parameter int SIZE=16, LANES=4, BUS_WIDTH=64, RW=$clog2(SIZE+1),\n'
    header += 'TILE_COUNT_W=$clog2(SIZE+1), CHUNK_COUNT_W=$clog2(LANES+1))(\n'
    fields = [('input logic ['+width+'-1:0] '+('i_' if registered else '')+name) for name,width in PORTS]
    if registered:
        fields.insert(0,'input logic clk')
    fields.append('output logic [18:0] observed')
    header += ',\n'.join(fields) + '\n);\n'
    if registered:
        header += '\n'.join('logic ['+width+'-1:0] '+name+';' for name,width in PORTS)+'\n'
        header += 'always_ff @(posedge clk) begin\n'+ '\n'.join(name+' <= i_'+name+';' for name,_ in PORTS)+'\nend\n'
    header += state_enum + '''
`ifdef XILINX_FPGA
localparam bit p_cfg_idle_use_lut=1'b1;
`else
localparam bit p_cfg_idle_use_lut=1'b0;
`endif
typedef struct packed {logic [15:0] group_c;} config_t;
config_t c;
logic cfg_ready,tile_ready,wr_valid,wr_last,finishing_tile;
logic channel_descriptor_valid,channel_accept_fire,tile_ready_context;
logic [15:0] channel_update,channel_value;
wire [15:0] ch_q=prior_channel;
logic [5:0] channel_accept_i_flags;
logic [15:0] channel_nxt;
wire prefetch_active=prefetch_phase!=4'd0;
wire [31:0] ch0=32'(ch0_q);
assign c.group_c=group_c;
'''
    header += ready(text)
    if channel:
        start = text.index('  // 通道位置先完成流式和解码更新，再选择同周期接收的快速描述符。')
        stop = text.index('  always_ff', start)
        header += text[start:stop]
    header += '\nalways_comb begin\n channel_nxt=prior_channel;\n' + body + '\nend\n'
    header += ('always_ff @(posedge clk) observed<=' if registered else 'assign observed=')
    header += '{cfg_ready,tile_ready,wr_valid,channel_nxt};\nendmodule\n'
    return header


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--reference',default='7ef39f0101ebf39184d11dbdc80a4042faee75c2')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); repo=args.repo.resolve(); out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    reference=read_rtl_source(args.reference+':'+SOURCE, cwd=repo, text=True)
    current=args.candidate.read_text()
    old_raw,_=process(reference); new_raw,_=process(current)
    old_clean=re.sub(r'ch_q\s*<=\s*[^;]+;', '', old_raw)
    assert re.sub(r'\s+', '', old_clean)==re.sub(r'\s+', '', new_raw), '其他主过程内容有变化'
    for signal in ('wr_last', 'wr_valid', 'finishing_tile'):
        assert re.search(r'  assign '+signal+r'\s*=.*?;', reference,re.S)[0] == re.search(r'  assign '+signal+r'\s*=.*?;', current,re.S)[0]
    assert len(re.findall(r'\bch_q\s*<=',old_raw))==9
    _,new_body=process(current,True)
    assert len(re.findall(r'\bch_q\s*<=',new_body))==2
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model='\n'.join(re.search(r'^module '+name+r'\b.*?^endmodule',library.read_text(),re.M|re.S)[0] for name in ('LUT6','LUT6_2'))
    model=re.sub(r'\bspecify\b.*?\bendspecify\b','',model,flags=re.S)
    model_path=out/'official_lut6.sv';model_path.write_text(model+'\n')
    models={}
    for label,text in (('reference',reference),('current',current)):
        models[label]=out/(label+'.sv');models[label].write_text(unit(text,label,label=='current'))
        (out/(label+'_registered.sv')).write_text(unit(text,'channel_write',label=='current',True))
    report={'source_sha256':sha(current.encode()),'reference_sha256':sha(reference.encode()),
            'reference_commit':args.reference,'other_main_process_unchanged_after_removing_channel_assignments':True,
            'reference_channel_assignments':9,'current_channel_assignments':2,'inputs_constrained':False,'observed_channel_bits':16,
            'actual_cfg_ready_tile_ready_write_valid_and_last':True,
            'official_library_sha256':sha(library.read_bytes()),'official_lut_models_sha256':sha(model_path.read_bytes()),'cases':[]}
    for size,lanes,bus in ((16,4,64),(1,1,32),(3,2,64),(32,8,128)):
        for fpga in (False,True):
            name=f'size{size}_lanes{lanes}_bus{bus}_'+('fpga' if fpga else 'generic')
            commands=[]
            for label,path in models.items():
                files=[path]+([model_path] if fpga else [])
                flags=f'-GSIZE={size} -GLANES={lanes} -GBUS_WIDTH={bus} '+('-D XILINX_FPGA -D YOSYS -D VERIFIC ' if fpga else '')
                commands+=['read_slang --top '+label+' '+flags+' '.join(shlex.quote(str(p)) for p in files),
                           'prep -top '+label+' -flatten','opt -full','design -stash '+label]
            commands+=['design -copy-from reference reference','design -copy-from current current',
                       'miter -equiv -flatten reference current comparison','hierarchy -top comparison','opt -full',
                       'sat -verify -prove trigger 0 -show-inputs -show-outputs']
            script,log=out/(name+'.ys'),out/(name+'.log');script.write_text('\n'.join(commands)+'\n')
            cmd=[sys.executable,str(repo/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)]
            with log.open('w') as stream:subprocess.run(cmd,cwd=repo,stdout=stream,stderr=subprocess.STDOUT,check=True)
            assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
            report['cases'].append({'size':size,'lanes':lanes,'bus_width':bus,'fpga':fpga,'passed':True,
                'command':cmd,'script_sha256':sha(script.read_bytes()),'log_sha256':sha(log.read_bytes())})
            print(name+': passed',flush=True)
    assert current==args.candidate.read_text()
    report['passed']=True
    report['script_sha256']=sha(Path(__file__).read_bytes())
    report['model_sha256']={label:sha(path.read_bytes()) for label,path in models.items()}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
