"""读取工具链提供的 Xilinx LUT 功能模型。"""
import hashlib
from pathlib import Path
import re


def prepare_models(out):
    import pyosys
    vendor = Path(pyosys.__file__).resolve().parent / 'share/xilinx/cells_sim.v'
    text = vendor.read_text()
    modules = []
    for name in ('LUT3', 'LUT6', 'LUT6_2'):
        match = re.search(r'^module ' + name + r'\b.*?^endmodule', text, re.M | re.S)
        if match is None:
            raise RuntimeError('Cannot find Xilinx model: ' + name)
        modules.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', match[0], flags=re.S))
    path = out / 'xilinx_luts.v'
    path.write_text('\n\n'.join(modules) + '\n')
    return path, {
        'vendor_source': str(vendor),
        'vendor_sha256': hashlib.sha256(vendor.read_bytes()).hexdigest(),
        'models_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'removed_sections': 'specify timing annotations',
    }
