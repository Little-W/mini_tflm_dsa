"""生成逐周期对照模块，比较向量引擎的全部公开输出。"""
from pathlib import Path
import hashlib
import re


def _split_values(text):
    values = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            values.append(text[start:index].strip())
            start = index + 1
    values.append(text[start:].strip())
    return values


def prepare_reference(reference_path, current_path, out):
    reference_path = Path(reference_path).resolve()
    current_path = Path(current_path).resolve()
    reference = reference_path.read_text()
    current = current_path.read_text()
    declaration = re.search(r"module vector_engine\s*#\((.*?)\)\s*\((.*?)\n\);", current, re.S)
    if declaration is None:
        raise ValueError("找不到向量引擎的参数和端口声明")
    parameters, header = declaration.groups()
    header = re.sub(r"//[^\n]*|/\*.*?\*/", " ", header, flags=re.S)
    parameter_names = re.findall(r"parameter\s+(?:int|bit)\s+(\w+)", parameters)
    ports = []
    for match in re.finditer(
        r"\b(input|output)\s+((?:logic|\w+::\w+)(?:\s+signed)?"
        r"(?:\s*\[[^\]]+\])*)\s+(.+?)(?=,\s*(?:input|output)\b|\Z)",
        header.strip(), re.S
    ):
        direction, dtype, values = match.groups()
        for value in _split_values(values.strip().rstrip(",")):
            variable = re.fullmatch(r"(\w+)(\s*(?:\[[^\]]+\]\s*)*)(?:\s*=.*)?", value, re.S)
            if variable is None:
                raise ValueError("无法读取向量引擎端口：" + value)
            ports.append((direction, dtype, variable[1], variable[2].strip()))
    reference_declaration = re.search(r"module vector_engine\s*#\((.*?)\)\s*\((.*?)\n\);", reference, re.S)
    if reference_declaration is None:
        raise ValueError("找不到参考引擎的公开接口")
    reference_header = re.sub(r"//[^\n]*|/\*.*?\*/", " ", reference_declaration[2], flags=re.S)
    if re.sub(r"\s+", "", reference_header) != re.sub(r"\s+", "", header):
        raise ValueError("参考引擎与待测引擎的公开接口不同")
    reference = re.sub(r"\bmodule\s+vector_engine\b", "module vector_engine_reference", reference, count=1)
    ref_file = out / "vector_engine_reference.sv"
    ref_file.write_text(reference)
    observer = [
        "// 参考引擎与待测引擎接收完全相同的公开输入，每周期检查全部输出。\n",
        "module vector_engine_equivalence_observer #(\n", parameters, ") ();\n",
        "  longint unsigned cycles = 0;\n",
    ]
    for direction, dtype, name, dimensions in ports:
        if direction == "output":
            observer.append(f"  {dtype} reference_{name} {dimensions};\n")
    observer.append("  vector_engine_reference #(\n")
    observer.append(",\n".join(f"    .{name}({name})" for name in parameter_names))
    observer.append("\n  ) reference_engine (\n")
    observer.append(",\n".join(
        f"    .{name}({'reference_' + name if direction == 'output' else 'vector_engine.' + name})"
        for direction, _, name, _ in ports))
    observer.append("\n  );\n  always @(negedge vector_engine.clk) if (vector_engine.rst_n) begin\n")
    observer.append("    cycles <= cycles + 1;\n")
    output_ports = 0
    for direction, _, name, dimensions in ports:
        if direction != "output":
            continue
        output_ports += 1
        suffix = ""
        for index, length in enumerate(re.findall(r"\[([^\]]+)\]", dimensions)):
            observer.append(f"    for (int item{index}=0; item{index}<{length}; item{index}++)\n")
            suffix += f"[item{index}]"
        observer.append(
            f"    assert (reference_{name}{suffix} === vector_engine.{name}{suffix})\n"
            f'      else $fatal(1, "向量引擎公开输出不一致：{name}，周期 %0d", cycles);\n')
    observer.append("  end\n")
    observer.append(f'  final $display("VECTOR_ENGINE_EQUIVALENCE_PASS cycles=%0d output_ports={output_ports}", cycles);\n')
    observer.append("endmodule\n\nbind vector_engine vector_engine_equivalence_observer #(\n")
    observer.append(",\n".join(f"  .{name}({name})" for name in parameter_names))
    observer.append("\n) u_cycle_comparison ();\n")
    observer_file = out / "vector_engine_equivalence_observer.sv"
    observer_file.write_text("".join(observer))
    return [ref_file, observer_file], {
        "reference_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "current_sha256": hashlib.sha256(current_path.read_bytes()).hexdigest(),
        "reference_path": str(reference_path),
        "public_ports": len(ports),
        "compared_output_ports": output_ports,
    }
