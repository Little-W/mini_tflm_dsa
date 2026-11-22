#!/usr/bin/env python3
"""生成 IA 请求寄存版本的生产参数独立综合配置。"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
parameters = dict(SIZE=16, BUS_WIDTH=64, COUNT_WIDTH=29, CACHE_BLOCKS=32,
                  EXTERNAL_RAM=1, ORDERED_JOB=1, RAM_WORD_ADDR_WIDTH=12,
                  PS_FRAME_COUNT=16, p_dma_source_layout=1, p_shared_write_stage=1,
                  p_register_dma_request=1)
case = dict(top='ia_loader', parameters=parameters,
            sources=['rtl/npu/loaders/' + name + '.sv' for name in
                     ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr')] +
                    ['rtl/npu/compute/select_add.sv'],
            options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                    ['-G' + key + '=' + str(value) for key, value in parameters.items()],
            configuration='生产 IA 参数与寄存 DMA 仲裁请求')
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(dict(ia_request_stage=case), indent=2) + '\n')
