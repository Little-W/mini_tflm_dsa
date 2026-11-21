"""提取实际 RAM 地址推进函数并保存两份实现的源码摘要。"""
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

REFERENCE = 'dde5e7c9'
SOURCES = ['rtl/soc/soc_axi_ram.sv', 'test/models/soc_axi_ram.sv']
FUNCTION = re.compile(r'    function automatic logic \[AW:0\] axi_next_addr\(.*?    endfunction', re.S)
BYTE_FUNCTION = re.compile(r'    // 高位字节独立递增[^\n]*\n'
                           r'    function automatic logic \[AW:0\] axi_increment_high_bytes\(.*?    endfunction\n\n', re.S)
BYTE_SIGNALS = re.compile(r'    \(\* keep = "true" \*\) logic \[AW:0\] rd_high_bytes_incremented;\n'
                          r'    (?:\(\* keep = "true" \*\) )?logic \[AW:0\] wr_high_bytes_incremented;\n'
                          r'    assign rd_high_bytes_incremented = axi_increment_high_bytes\(rd_byte_addr_q\);\n'
                          r'    assign wr_high_bytes_incremented = axi_increment_high_bytes\(wr_byte_addr_q\);\n\n')
READ_BOUND = re.compile(r'    (?:wire|logic) rd_issue_oob.*?(?=    wire rd_issue_fault)', re.S)
WRITE_LANES = re.compile(r'    (?:wire|logic) wr_active_oob.*?(?=    wire wr_strobe_error)', re.S)
REGIONS = [FUNCTION, READ_BOUND, WRITE_LANES]
WIDTHS = [1, 3, 7, 8, 9, 16, 24, 32, 40, 65]
HELPER_PROFILES = [(aw, dw, dp) for aw, dw in
                   [(8, 8), (8, 32), (8, 64), (16, 24), (16, 128), (32, 32), (32, 64), (40, 1024)]
                   for dp in [1, 2, 3, 7, 8, 15, 16, 31, 32, 63, 64, 65, 1024, 1031, 32768, 32769]]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def address_functions(source):
    helper = BYTE_FUNCTION.search(source)
    return (helper[0] if helper else '') + FUNCTION.search(source)[0]


def without_byte_boundary(source):
    """只消去经过单独比较的字节递增函数及其连接，不隐藏时序逻辑。"""
    source = BYTE_FUNCTION.sub('', source)
    source = BYTE_SIGNALS.sub('', source)
    return re.sub(r',(rd|wr)_high_bytes_incremented\)', ')', source)


def snapshot(out, reference, source_root=ROOT, reference_root=None):
    out.mkdir(parents=True, exist_ok=True)
    rows, functions, helpers = [], [], []
    for source in SOURCES:
        current = (source_root / source).read_text()
        original = ((reference_root / source).read_text() if reference_root else
                    read_rtl_source(f'{reference}:{source}', cwd=ROOT, text=True))
        reference_other, current_other = without_byte_boundary(original), without_byte_boundary(current)
        for index, region in enumerate(REGIONS):
            assert len(region.findall(current)) == len(region.findall(original)) == 1
            reference_other = region.sub(f'<region{index}>', reference_other)
            current_other = region.sub(f'<region{index}>', current_other)
        assert reference_other == current_other, source
        functions.append((address_functions(original), address_functions(current)))
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
    return functions[0], {'reference_commit': str(reference_root) if reference_root else reference,
                          'sources': rows,
                          'production_and_model_functions_identical': True}


def miter(original, current):
    def implementation(source, label):
        return source.replace('axi_next_addr', 'address_' + label).replace(
            'axi_increment_high_bytes', 'increment_high_bytes_' + label)

    def call(source, label):
        extra = (', increment_high_bytes_' + label + '(byte_addr)'
                 if 'axi_increment_high_bytes' in source else '')
        return 'address_' + label + '(byte_addr, size, burst' + extra + ')'

    return '''module address_miter #(parameter AW=32)(
    input [AW:0] byte_addr, input [2:0] size, input [1:0] burst,
    output [AW:0] reference_address, current_address, output correct);
''' + implementation(original, 'reference') + '\n' + implementation(current, 'current') + f'''
    assign reference_address = {call(original, 'reference')};
    assign current_address = {call(current, 'current')};
    assign correct = reference_address == current_address;
endmodule
'''


def helper_miter(reference, source_root=ROOT, reference_root=None):
    original = ((reference_root / SOURCES[0]).read_text() if reference_root else
                read_rtl_source(f'{reference}:{SOURCES[0]}', cwd=ROOT, text=True))
    current = (source_root / SOURCES[0]).read_text()
    sections = []
    for label, source in [('reference', original), ('current', current)]:
        body = READ_BOUND.search(source)[0] + WRITE_LANES.search(source)[0]
        for name in ['rd_issue_oob', 'wr_active_oob', 'wr_lane_first', 'wr_lane_end',
                     'wr_transfer_block', 'wr_legal_lanes']:
            body = re.sub(r'\b' + name + r'\b', label + '_' + name, body)
        body = re.sub(r'\bg_read_(power|arbitrary|predicted)_bound\b',
                      lambda match: label + '_' + match[0], body)
        sections.append(body)
    return '''module helper_miter #(parameter AW=32,DW=64,DP=32768)(
    input [AW-((DW/8)<=1 ? 0 : $clog2(DW/8)):0] rd_issue_word_addr,wr_word_addr_q,
    input [AW:0] wr_byte_addr_q, input [2:0] wr_size_active_q,
    output [DW/8+1:0] reference_result,current_result, output correct);
    localparam BYTEW=DW/8;
    localparam ADDR_LSB=BYTEW<=1 ? 0 : $clog2(BYTEW);
    localparam WORD_ADDR_BITS=AW-ADDR_LSB;
    // 本模型检查静止地址的完整容量范围，地址推进由地址模型单独检查。
    wire [AW:0] rd_byte_addr_q=(AW+1)'(rd_issue_word_addr) << ADDR_LSB;
    wire [AW:0] rd_pipe_cmd_byte_addr='0;
    wire rd_pipe_cmd=1'b0,rd_pipe_beat=1'b0;
    wire [2:0] rd_size_active_q=3'd0;
    wire [1:0] rd_burst_active_q=2'd0;
''' + '\n'.join(sections) + '''
    assign reference_result={reference_rd_issue_oob,reference_wr_active_oob,reference_wr_legal_lanes};
    assign current_result={current_rd_issue_oob,current_wr_active_oob,current_wr_legal_lanes};
    assign correct=reference_result==current_result;
endmodule
'''
