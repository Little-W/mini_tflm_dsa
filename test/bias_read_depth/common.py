"""固定偏置加载器的实际源码和同步存储比较接口。"""
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'
BUFFER = 'rtl/npu/loaders/bias_loader_buffer.sv'
WRAPPER = 'rtl/npu/loaders/bias_loader.sv'
CONTROL = 'rtl/npu/loaders/bias_loader_ctrl.sv'
SOURCES = [WRAPPER, CONTROL, BUFFER]
MEMORY = 'rtl/common/regfile.v'
HELPER = 'rtl/common/parallel_prefix_add.sv'
HELPERS = [HELPER, 'rtl/common/parallel_unsigned_compare.sv', 'rtl/common/add_equal.sv']
PARAMETERS = {'SIZE': 16, 'BUS_WIDTH': 64, 'DATA_WIDTH': 32, 'REG_WIDTH': 32,
              'COUNT_WIDTH': 29, 'GROUP_BLOCKS_MAX': 32}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(out, reference):
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for source in SOURCES + [MEMORY] + HELPERS:
        current = (ROOT / source).read_bytes()
        original = (current if source in [CONTROL] + HELPERS else
                    read_rtl_source(f'{reference}:{source}', cwd=ROOT))
        if source not in (BUFFER, WRAPPER):
            assert original == current, source
        for label, data in [('reference', original), ('current', current)]:
            target = out / label / source
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        records.append({'source': source,
                        'reference_sha256': hashlib.sha256(original).hexdigest(),
                        'current_sha256': hashlib.sha256(current).hexdigest()})
    return {'reference_commit': reference, 'reference_scope': [BUFFER, WRAPPER],
            'shared_current_sources': [CONTROL] + HELPERS, 'sources': records}


def abstract_storage(source):
    """保存实际控制、缓存及存储端口，存储返回改为两侧共用的任意输入。"""
    marker = '    input  wire logic clk,'
    assert source.count(marker) == 1
    source = source.replace(marker, '    input logic [63:0] i_formal_read_data,\n' + marker)
    pattern = re.compile(r'  regfile #\(.*?\n  \);', re.S)
    found = pattern.findall(source)
    assert len(found) == 1 and ') u_storage (' in found[0]
    source = pattern.sub('  assign storage_o_rd_data = i_formal_read_data;', source)
    for name in ['storage_i_wr_en', 'storage_i_rd_en', 'storage_i_wr_addr',
                 'storage_i_rd_addr', 'storage_i_wr_data', 'storage_i_wr_mask']:
        pattern = re.compile(r'^(  logic[^;\n]*\b' + name + r'\b[^;\n]*;)', re.M)
        assert len(pattern.findall(source)) == 1, name
        source = pattern.sub(r'  (* keep *)\n\1', source)
    return source


def abstract_wrapper(source):
    marker = '    input logic clk,'
    assert source.count(marker) == 1
    source = source.replace(marker, '    input logic [63:0] i_formal_read_data,\n' + marker)
    marker = '.group_data_scalar (buffer_group_data_scalar)'
    assert source.count(marker) == 1
    return source.replace(marker, marker + ',\n        .i_formal_read_data(i_formal_read_data)')
