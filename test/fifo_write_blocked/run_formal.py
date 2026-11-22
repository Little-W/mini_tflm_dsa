#!/usr/bin/env python3
"""证明 FIFO 完整状态、存储端口和写入阻塞寄存关系逐周期相同。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'fifo_complete_proof', ROOT / 'test/fifo_read_qualification/run_formal.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
extract_source = base.observed_source


def observed_source(source: str) -> str:
    text = extract_source(source)
    marker = '    output wire [BANKS*$clog2(VLEN+1)-1:0] formal_bank_counts'
    if text.count(marker) != 1:
        raise RuntimeError('Expected one FIFO state observation port')
    text = text.replace(marker, '    output wire [5:0] formal_saved_state,\n' + marker)
    if 'logic write_bank_blocked_q, next_write_bank_blocked_q;' in source:
        checks = '''
    // 新增状态关系作为待证明的输出，与完整时序状态共同执行归纳检查。
    assign formal_saved_state[0] = write_bank_blocked_q ==
        (|(bank_ready & write_bank_mask_q));
    assign formal_saved_state[1] = next_write_bank_blocked_q ==
        (|(bank_ready & next_write_bank_mask));
    assign formal_saved_state[2] = read_row_limit_q ==
        (COUNT_WIDTH'(read_ptr) + COUNT_WIDTH'(1));
    assign formal_saved_state[3] = transpose_row_count_q ==
        (COUNT_WIDTH'(vec_valid_num_row_tmp) + COUNT_WIDTH'(1));
    assign formal_saved_state[4] = write_bank_mask_q == (BANKS'(1) << write_bank);
    assign formal_saved_state[5] = int'(write_bank) < BANKS;
'''
    else:
        checks = "    assign formal_saved_state = 6'b111111;\n"
    return text.replace('endmodule', checks + '\nendmodule', 1)


if __name__ == '__main__':
    base.observed_source = observed_source
    base.main()
