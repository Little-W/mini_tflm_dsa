"""从生产参数声明与顶层连接计算比较实验的资源配置。"""
from pathlib import Path
import re


def expression(text, name, *, local=False):
    keyword = r"localparam" if local else r"parameter"
    match = re.search(r"\b" + keyword + r"\b[^=,;\n]*\b" + name +
                      r"\s*=\s*([^,;]+)", text)
    return re.sub(r"\s+", "", match[1]) if match else None


def resolve_vector_configuration(repo, *, pe_count, bank_count, bus_width=64, shared_enabled=True):
    """仅接受可明确解释的生产参数表达式；未知表达式要求更新解析规则。"""
    repo = Path(repo)
    top = (repo / "rtl/npu/top/npu_top.sv").read_text()
    engine = (repo / "rtl/npu/conv/vector_engine.sv").read_text()
    top = re.sub(r"//[^\n]*|/\*.*?\*/", "", top, flags=re.S)
    engine = re.sub(r"//[^\n]*|/\*.*?\*/", "", engine, flags=re.S)
    window = expression(top, "WINDOW_LANES")
    quant = expression(engine, "QUANT_LANES")
    shared = expression(engine, "SHARED_QUANT_ENABLE")
    if window is None:
        standalone = expression(engine, "WINDOW_LANES")
        if standalone is None or not standalone.isdigit():
            raise ValueError("无法解释独立向量模块的窗口并行参数")
        window_lanes = int(standalone)
    elif window == "BUS_WIDTH/8":
        window_lanes = bus_width // 8
    else:
        match = re.fullmatch(r"VECTOR_PE_COUNT>=(\d+)\?(\d+):BUS_WIDTH/8", window)
        if not match:
            raise ValueError("无法解释窗口并行参数：" + window)
        window_lanes = int(match[2]) if pe_count >= int(match[1]) else bus_width // 8
    shared_quant_enable = 0
    if shared is not None:
        if not re.search(r"\.SHARED_QUANT_ENABLE\s*\(\s*DW_SHARED_QUANT_ENABLE\s*\)", top):
            raise ValueError("顶层需要明确连接 DW 共享量化参数")
        condition = expression(top, "DW_SHARED_QUANT_ENABLE", local=True)
        lanes = expression(top, "REQUANT_COMPUTE_LANES", local=True)
        if condition != "REQUANT_COMPUTE_LANES==SIZE":
            raise ValueError("无法解释共享量化选择条件：" + str(condition))
        match = re.fullmatch(r"SHARED_RAM_ENABLED&&SHARED_PHYSICAL_BANKS<(\d+)&&"
                             r"SIZE>(\d+)&&\(SIZE%(\d+)\)==0\?(\d+):SIZE", lanes or "")
        if not match:
            raise ValueError("无法解释矩阵量化并行参数：" + str(lanes))
        reduced = shared_enabled and bank_count < int(match[1]) and 16 > int(match[2]) and 16 % int(match[3]) == 0
        matrix_lanes = int(match[4]) if reduced else 16
        shared_quant_enable = int(matrix_lanes == 16)
        if quant != "SHARED_QUANT_ENABLE?TILE:1":
            raise ValueError("无法解释共享 DW 量化并行参数：" + str(quant))
        quantization_lanes = 16 if shared_quant_enable else 1
    elif quant is None:
        quantization_lanes = 1
    elif quant.isdigit():
        quantization_lanes = int(quant)
    else:
        match = re.fullmatch(r"\(?PE_COUNT>=(\d+)\)?\?(\d+):(\d+)", quant)
        if not match:
            raise ValueError("无法解释 DW 量化并行参数：" + quant)
        quantization_lanes = int(match[2] if pe_count >= int(match[1]) else match[3])
    return dict(vector_pe_count=pe_count, quantization_lanes=quantization_lanes,
                window_lanes=window_lanes, shared_quant_enable=shared_quant_enable,
                top_window_parameter=window is not None, quantization_parameter=quant is not None,
                shared_quant_parameter=shared is not None)


def resolve_cache_configuration(repo, cache_bytes):
    """使用生产默认行长及路数，核对集合数对应的实际数据容量。"""
    top = (Path(repo) / "rtl/npu/top/npu_top.sv").read_text()
    top = re.sub(r"//[^\n]*|/\*.*?\*/", "", top, flags=re.S)
    line = expression(top, "CONV_LINE_BYTES")
    ways = expression(top, "CONV_CACHE_WAYS")
    sets = expression(top, "CONV_CACHE_SETS")
    if line is None or ways is None or not line.isdigit() or not ways.isdigit():
        raise ValueError("缓存默认行长与路数需要可明确读取的整数参数")
    line_bytes, cache_ways = int(line), int(ways)
    span = line_bytes * cache_ways
    if span <= 0 or cache_bytes % span:
        raise ValueError("缓存数据容量必须包含完整的组与路")
    if sets == "IM2COL_CACHE_BYTES/(CONV_CACHE_WAYS*CONV_LINE_BYTES)":
        cache_sets = cache_bytes // span
    else:
        match = re.fullmatch(r"IM2COL_CACHE_BYTES/(\d+)", sets or "")
        if not match or int(match[1]) != span:
            raise ValueError("缓存集合数声明与实际行长、路数不一致：" + str(sets))
        cache_sets = cache_bytes // int(match[1])
    return dict(cache_line_bytes=line_bytes, cache_sets=cache_sets, cache_ways=cache_ways)
