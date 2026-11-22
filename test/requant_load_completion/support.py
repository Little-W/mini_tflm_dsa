"""参数装载命令检查共用的固定参考源码与完整算式提取。"""
from pathlib import Path
import hashlib
import runpy
import shutil

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RTL = Path('rtl/npu/writeback/vec_requant.sv')
HELPER = Path('rtl/common/parallel_prefix_add.sv')
PROFILES = [(1, 32), (3, 32), (16, 32), (32, 32), (256, 32), (1024, 32),
            (16, 1), (16, 4), (16, 8), (16, 24), (16, 40), (16, 64)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_paths(root):
    names = runpy.run_path(str(ROOT / 'test/requant_test_utils.py'))['RTL_SOURCES']
    reader = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    return reader([Path(root) / name for name in names], Path(root))


def reference_root(out, current_root):
    """保留完整依赖，在独立目录恢复固定的参考控制器和进位网络。"""
    out, current_root = Path(out).resolve(), Path(current_root).resolve()
    replacements = {RTL: HERE / 'reference_vec_requant.sv',
                    HELPER: HERE / 'reference_parallel_prefix_add.sv'}
    for source in source_paths(current_root):
        relative = source.relative_to(current_root)
        destination = out / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(replacements.get(relative, source), destination)
    return out


def arithmetic_unit(source, label):
    text = Path(source).read_text()
    first = text.index('  // 完整三十三位差值')
    last = text.index('\n  // ----------------------------', first)
    body = text[first:last]
    result = 'cmd_has_more_prepare' if 'g_load_command_compare' in body else 'load_has_more'
    return f'''module arithmetic_{label} #(parameter REG_WIDTH=32, VLEN=16, BUS_WIDTH=64)(
    input logic [31:0] quant_need_load_r, load_offset,
    output wire result,
    output wire [31:0] chunk
);
    localparam VLEN_CNT_W=(VLEN<=1)?1:$clog2(VLEN+1);
    logic [32:0] remaining_words;
    logic [VLEN_CNT_W-1:0] chunk_words, burst_word_index;
    wire [VLEN_CNT_W-1:0] beats_expect=chunk_words;
    logic [31:0] chunk_need_cur;
    logic [7:0] burst_len_cur;
    logic load_has_more, cmd_has_more_prepare;
{body}
    assign result={result};
    assign chunk=chunk_need_cur;
endmodule
'''
