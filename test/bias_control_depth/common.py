"""偏置控制器准备阶段的源码与参数。"""
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'
CONTROL = 'rtl/npu/loaders/bias_loader_ctrl.sv'
HELPER = 'rtl/common/parallel_prefix_add.sv'
SOURCES = ['rtl/npu/loaders/bias_loader.sv', CONTROL, 'rtl/npu/loaders/bias_loader_buffer.sv']
PARAMETERS = {'SIZE': 16, 'BUS_WIDTH': 64, 'DATA_WIDTH': 32, 'REG_WIDTH': 32,
              'COUNT_WIDTH': 29, 'GROUP_BLOCKS_MAX': 32}
PROFILES = [(4, 32, 32, 1, 1), (8, 32, 32, 8, 3), (12, 64, 32, 12, 5),
            (16, 32, 32, 12, 4), (16, 64, 32, 29, 32), (16, 64, 32, 32, 64),
            (16, 128, 16, 12, 16), (32, 64, 40, 35, 1)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(out, reference=REFERENCE):
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for name in SOURCES + ['rtl/common/regfile.v']:
        current = (ROOT / name).read_bytes()
        original = read_rtl_source(f'{reference}:{name}', cwd=ROOT) if name == CONTROL else current
        for label, data in [('reference', original), ('current', current)]:
            path = out / label / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        records.append({'source': name, 'reference_sha256': hashlib.sha256(original).hexdigest(),
                        'current_sha256': hashlib.sha256(current).hexdigest()})
    path = out / HELPER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((ROOT / HELPER).read_bytes())
    return {'reference_commit': reference, 'reference_scope': CONTROL, 'sources': records,
            'common_helper': {'source': HELPER, 'sha256': digest(path)}}
