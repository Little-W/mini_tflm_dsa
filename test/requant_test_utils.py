"""量化测试共用的源码集合与控制模块提取。"""
from pathlib import Path
import re

RTL_SOURCES = (
    "rtl/npu/writeback/requant_pkg.sv",
    "rtl/npu/writeback/requant_shift_pipeline.sv",
    "rtl/npu/writeback/requant_compute_lane.sv",
    "rtl/npu/writeback/requant_group_buffer.sv",
    "rtl/npu/writeback/vec_requant.sv",
    "rtl/npu/conv/registered_multiplier_s32.sv",
    "rtl/common/parallel_prefix_add.sv",
    "rtl/common/regfile.v",
)

def controller_module(source):
    """按量化控制状态选取完整模块，允许读取不同文件组织的参考源码。"""
    modules = re.findall(r"^module\s+\w+\b.*?^endmodule", source, re.M | re.S)
    matches = [text for text in modules if "logic s16_mode;" in text and "load_phase" in text]
    if len(matches) != 1:
        raise ValueError("量化源码需要包含一个完整控制模块")
    return matches[0]
