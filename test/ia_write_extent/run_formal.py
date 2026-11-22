#!/usr/bin/env python3
"""证明写入范围编码的完整 IA 状态及公开端口对应关系。"""
import argparse
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--tool-root', type=Path, default=ROOT)
args, remaining = parser.parse_known_args()
source = args.tool_root/'test/ia_slot_stage/run_formal.py'
spec = importlib.util.spec_from_file_location('ia_state_formal', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.CASES['production']['p_register_dma_request'] = 1
module.CASES['generic']['p_register_dma_request'] = 1
module.CASES['small']['SIZE'] = 8
sys.argv = [sys.argv[0], *remaining]
module.main()
