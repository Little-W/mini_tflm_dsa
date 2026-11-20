"""提取实际 RAM 地址推进函数并保存两份实现的源码摘要。"""
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'
SOURCES = ['rtl/soc/soc_axi_ram.sv', 'test/models/soc_axi_ram.sv']
FUNCTION = re.compile(r'    function automatic logic \[AW:0\] axi_next_addr\(.*?    endfunction', re.S)
READ_BOUND = re.compile(r'    (?:wire|logic) rd_issue_oob.*?(?=    wire rd_issue_fault)', re.S)
WRITE_LANES = re.compile(r'    (?:wire|logic) wr_active_oob.*?(?=    wire wr_strobe_error)', re.S)
REGIONS = [FUNCTION, READ_BOUND, WRITE_LANES]
WIDTHS = [1, 3, 7, 8, 9, 16, 24, 32, 40, 65]
HELPER_PROFILES = [(aw, dw, dp) for aw, dw in
                   [(8, 8), (8, 32), (8, 64), (16, 24), (16, 128), (32, 32), (32, 64), (40, 1024)]
                   for dp in [1, 2, 3, 7, 8, 15, 16, 31, 32, 63, 64, 65, 1024, 1031, 32768, 32769]]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(out, reference):
    out.mkdir(parents=True, exist_ok=True)
    rows, functions, helpers = [], [], []
    for source in SOURCES:
        current = (ROOT / source).read_text()
        original = read_rtl_source(f'{reference}:{source}', cwd=ROOT, text=True)
        reference_other, current_other = original, current
        for index, region in enumerate(REGIONS):
            assert len(region.findall(current)) == len(region.findall(original)) == 1
            reference_other = region.sub(f'<region{index}>', reference_other)
            current_other = region.sub(f'<region{index}>', current_other)
        assert reference_other == current_other, source
        functions.append((FUNCTION.search(original)[0], FUNCTION.search(current)[0]))
        helpers.append([(region.search(original)[0], region.search(current)[0]) for region in REGIONS[1:]])
        label = 'production' if source.startswith('rtl/') else 'model'
        for version, text in [('reference', original), ('current', current)]:
            folder = out / label / version
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'soc_axi_ram.sv').write_text(text)
        rows.append({'source': source,
                     'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
                     'current_sha256': hashlib.sha256(current.encode()).hexdigest(),
                     'only_combinational_address_and_lane_logic_changed': True})
    assert functions[0] == functions[1], 'Production and simulation address functions differ'
    assert helpers[0] == helpers[1], 'Production and simulation address checks differ'
    return functions[0], {'reference_commit': reference, 'sources': rows,
                          'production_and_model_functions_identical': True}


def miter(original, current):
    return '''module address_miter #(parameter AW=32)(
    input [AW:0] byte_addr, input [2:0] size, input [1:0] burst,
    output [AW:0] reference_address, current_address, output correct);
''' + original.replace('axi_next_addr', 'address_reference') + '\n' + current.replace(
        'axi_next_addr', 'address_current') + '''
    assign reference_address = address_reference(byte_addr, size, burst);
    assign current_address = address_current(byte_addr, size, burst);
    assign correct = reference_address == current_address;
endmodule
'''


def helper_miter(reference):
    original = read_rtl_source(f'{reference}:{SOURCES[0]}', cwd=ROOT, text=True)
    current = (ROOT / SOURCES[0]).read_text()
    sections = []
    for label, source in [('reference', original), ('current', current)]:
        body = READ_BOUND.search(source)[0] + WRITE_LANES.search(source)[0]
        for name in ['rd_issue_oob', 'wr_active_oob', 'wr_lane_first', 'wr_lane_end',
                     'wr_transfer_block', 'wr_legal_lanes']:
            body = re.sub(r'\b' + name + r'\b', label + '_' + name, body)
        sections.append(body)
    return '''module helper_miter #(parameter AW=32,DW=64,DP=32768)(
    input [AW-((DW/8)<=1 ? 0 : $clog2(DW/8)):0] rd_issue_word_addr,wr_word_addr_q,
    input [AW:0] wr_byte_addr_q, input [2:0] wr_size_active_q,
    output [DW/8+1:0] reference_result,current_result, output correct);
    localparam BYTEW=DW/8;
    localparam ADDR_LSB=BYTEW<=1 ? 0 : $clog2(BYTEW);
    localparam WORD_ADDR_BITS=AW-ADDR_LSB;
''' + '\n'.join(sections) + '''
    assign reference_result={reference_rd_issue_oob,reference_wr_active_oob,reference_wr_legal_lanes};
    assign current_result={current_rd_issue_oob,current_wr_active_oob,current_wr_legal_lanes};
    assign correct=reference_result==current_result;
endmodule
'''
