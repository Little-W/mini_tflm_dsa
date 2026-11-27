"""读取前端完整算术及预取模块，并保存可重复运行的源码副本。"""
from pathlib import Path
import hashlib
import json
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = 'e28e9d3fe5b530337238d7915c4a8606918b240a'
FILES = (
    'rtl/npu/conv/conv_group_base_address.sv',
    'rtl/npu/conv/conv_full_address_add.sv',
    'rtl/npu/conv/conv_im2col_prefetch.sv',
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log, timeout=900):
    with log.open('w') as handle:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=handle,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)
    return log.read_text()


def worker(commands, folder, name):
    script = folder / (name + '.ys')
    script.write_text('\n'.join(commands) + '\n')
    return execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
                    '--worker', script], folder/(name+'.log'))


def prepare(source, out, revision):
    """完整模块副本沿用各自依赖，新增组合模块只参与当前实现。"""
    revision = subprocess.check_output(['git', 'rev-parse', revision+'^{commit}'],
                                       cwd=source, text=True).strip()
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    originals = resolve([source/name for name in FILES], source)
    snapshots, hashes = {}, {}
    for label in ('reference', 'current'):
        snapshots[label], hashes[label] = [], {}
        for original in originals:
            relative = original.relative_to(source)
            if label == 'reference' and original.name == 'conv_group_base_address.sv':
                continue
            data = (subprocess.check_output(['git', 'show', revision+':'+str(relative)], cwd=source)
                    if label == 'reference' else original.read_bytes())
            target = out/'sources'/label/relative.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            snapshots[label].append(target)
            hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
    return revision, snapshots, hashes


def unchanged(source, hashes):
    if hashes['current'] != {name: digest(source/name) for name in hashes['current']}:
        raise RuntimeError('算术验证期间源码发生变化')


def save(path, result):
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')


def combinational_names(module):
    """内部对应只采用真实寄存器输出，公开端口始终参与比较。"""
    registered=set()
    for cell in module['cells'].values():
        if re.fullmatch(r'\$(?:[a-z]*dff[a-z]*|[a-z]*latch[a-z]*|ff)',cell['type']):
            registered.update(bit for bit in cell['connections'].get('Q',[]) if isinstance(bit,int))
    excluded=set(module['cells']);retained=[]
    for name,wire in module['netnames'].items():
        if name in module['ports']:continue
        bits={bit for bit in wire['bits'] if isinstance(bit,int)}
        if bits and bits<=registered:retained.append(name)
        else:excluded.add(name)
    return excluded,retained


UNIT = '''// 完整组基址、像素和预取纵坐标的公开定宽关系。
module arithmetic_model(
 input logic [31:0] base, // 字节基址
 input logic [31:0] product, // 像素与通道的完整模乘积
 input logic [15:0] offset, // 通道组偏移
 input logic sample_s16, // 两字节元素标志
 input logic [34:0] coordinate, // 有符号输入坐标的位表示
 input logic [16:0] displacement, // 窗口的非负纵向增量
 output logic [130:0] actual, // 当前实现的全部结果
 output logic [130:0] expected, // 完整定宽算术结果
 output logic equal // 全部二态结果相等
);
 logic [34:0] window_sum,window_result;
 logic unused_carry;
 conv_group_base_address u_group(.i_input_base(base),.i_channel_product(product),
  .i_group_offset(offset),.i_input_s16(sample_s16),.o_address(actual[31:0]));
 conv_full_address_add u_pixel(.i_a(product),.i_b(32'(coordinate)),.o_sum(actual[63:32]));
 conditional_increment #(.p_width(32),.p_group_width(4)) u_increment(
  .i_value(32'(coordinate)),.i_enable(1'b1),.o_result(actual[95:64]));
 parallel_prefix_add #(.p_width(35),.p_group_width(8),.p_preserve_groups(1'b1),
  .p_dsp_split_width(16),.p_parallel_high_prefix(1'b1),.p_keep_carry(1'b0)) u_window(
  .i_a(coordinate),.i_b(35'(displacement)),.i_carry(1'b0),
  .o_sum(window_sum),.o_carry(unused_carry));
 always_comb begin
  window_result=$signed(coordinate)+$signed(35'(displacement));
  case(^{coordinate,displacement})
   1'b0,1'b1:window_result=window_sum;
   default:;
  endcase
 end
 assign actual[130:96]=window_result;
 assign expected={($signed(coordinate)+$signed(35'(displacement))),
  (32'(coordinate)+32'd1),(product+32'(coordinate)),
  (base+((product+32'(offset))<<sample_s16))};
 assign equal=actual==expected;
endmodule
'''
