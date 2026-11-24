"""为 RTL 仿真提供所需 FPGA 查找表的功能模型及文件摘要。"""
from pathlib import Path
import hashlib
import re


def xilinx_lut_models(output: Path, modules=('LUT5', 'LUT6', 'LUT6_2')):
    import pyosys

    requested = set(modules)
    if not requested or not requested <= {'LUT5', 'LUT6', 'LUT6_2'}:
        raise ValueError('查找表功能模型名称无效')
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    content = library.read_text()
    blocks = re.findall(r'^module (LUT5|LUT6|LUT6_2)\b(.*?)^endmodule',
                        content, re.M | re.S)
    selected = {name: 'module ' + name + body + 'endmodule'
                for name, body in blocks if name in requested}
    if set(selected) != requested:
        raise ValueError('仿真库缺少所需查找表的完整功能模型')
    model = output / 'xilinx_luts.sv'
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '',
        '\n'.join(selected[name] for name in sorted(requested)), flags=re.S) + '\n')
    return model, {
        'library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
        'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
        'modules': sorted(requested),
    }
