"""读取实际工具链中的 Xilinx 组合原语功能模型。"""
import hashlib
from pathlib import Path
import re


def prepare_models(out, names=('LUT6', 'LUT6_2', 'DSP48E1')):
    import pyosys
    library = Path(pyosys.__file__).resolve().parent / 'share/xilinx/cells_sim.v'
    content = library.read_text()
    modules = []
    for name in names:
        match = re.search(r'^module ' + name + r'\b.*?^endmodule', content, re.M | re.S)
        if match is None:
            raise RuntimeError('Missing Xilinx primitive model: ' + name)
        modules.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', match[0], flags=re.S))
    path = out / ('xilinx_' + '_'.join(names).lower() + '.sv')
    path.write_text('\n\n'.join(modules) + '\n')
    return path, dict(library=str(library),
        library_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
        models=list(names), models_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        scope='Functional models with specify timing annotations removed')
