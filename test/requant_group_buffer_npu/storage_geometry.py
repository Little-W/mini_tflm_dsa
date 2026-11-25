"""核对完整 NPU 中 Kernel、Bias 和量化移位参数的实际存储几何。"""
from collections import Counter

MACRO_BITS = {"RAMTP128X16": 128 * 16, "RAMTP1024X16": 1024 * 16}


def expected_macros(width, depth, unit, masked, force_sram=False):
    """按公共 regfile 的同步单读端资源条件计算固定配置的宏数量。"""
    macro_depth = 128 if depth <= 384 else 1024
    segment_width = width if masked else unit
    per_segment = ((segment_width + 15) // 16) * ((depth + macro_depth - 1) // macro_depth)
    minimum_bits = 1024 if macro_depth == 128 else 4096
    if depth < 32 or (not force_sram and depth * segment_width < per_segment * minimum_bits):
        return {}
    segments = 1 if masked else width // unit
    return {f"RAMTP{macro_depth}X16": segments * per_segment}


def inspect_selected_storage(rows, memories, capacity, profile):
    """分别验证三类存储的逻辑容量、公共端口和物理资源。"""
    selected = {}

    def roots(module):
        matches = [row for row in rows if row["module"] == module]
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one {module}")
        return matches[0]["path"]

    def check(name, registers, count, width, depth, unit, masked, logical_width, logical_depth, force_sram=False):
        if len(registers) != count:
            raise RuntimeError(f"{name}: register-file instance count differs")
        expected = expected_macros(width, depth, unit, masked, force_sram)
        details = []
        all_macros = Counter()
        total_register_bits = 0
        for register in registers:
            port_widths = register["port_widths"]
            address_width = max(1, (depth - 1).bit_length())
            ports = {"i_wr_data": width, "o_rd_data": width,
                     "i_wr_addr": address_width, "i_rd_addr": address_width,
                     "i_wr_mask": width // unit, "i_wr_en": 1, "i_rd_en": 1, "clk": 1}
            if any(port_widths.get(key) != value for key, value in ports.items()):
                raise RuntimeError(f"{name}: public storage geometry differs at {register['path']}")
            prefix = register["path"] + "/"
            macros = Counter(row["module"] for row in rows
                             if row["path"].startswith(prefix) and row["module"] in MACRO_BITS)
            arrays = [row for row in memories if row["path"].startswith(prefix)]
            if macros != expected:
                raise RuntimeError(f"{name}: expected macros {expected}, found {dict(macros)}")
            if expected:
                if arrays:
                    raise RuntimeError(f"{name}: SRAM storage also contains inferred arrays")
                register_bits = 0
                kind = "sram_macro"
            else:
                if len(arrays) != 1:
                    raise RuntimeError(f"{name}: expected one inferred data array per column or bank")
                geometry = arrays[0]["geometry"]
                # proc/memory_collect 保留数组外的同步读取寄存器，不执行 memory_dff 吸收。
                required = {"WIDTH": width, "SIZE": depth, "RD_PORTS": 1, "WR_PORTS": 1,
                            "RD_CLK_ENABLE": 0, "WR_CLK_ENABLE": 1}
                if any(geometry.get(key) != value for key, value in required.items()):
                    raise RuntimeError(f"{name}: inferred storage dimensions or ports differ")
                register_bits = width * depth
                kind = "register_array"
            all_macros.update(macros)
            total_register_bits += register_bits
            macro_bits = sum(MACRO_BITS[key] * value for key, value in macros.items())
            logical_bits = logical_width * logical_depth
            physical_bits = macro_bits + register_bits
            details.append({"path": register["path"], "implementation": kind,
                            "logical_width": logical_width, "logical_depth": logical_depth,
                            "storage_width": width, "storage_depth": depth,
                            "write_unit": unit, "read_ports": 1, "logical_storage_bits": logical_bits,
                            "macro_instances": dict(macros), "physical_macro_storage_bits": macro_bits,
                            "register_array_storage_bits": register_bits,
                            "physical_storage_bits": physical_bits,
                            "padding_bits": physical_bits - logical_bits,
                            "capacity_utilization": logical_bits / physical_bits})
        logical_bits = count * logical_width * logical_depth
        macro_bits = sum(MACRO_BITS[key] * value for key, value in all_macros.items())
        physical_bits = macro_bits + total_register_bits
        selected[name] = {"storage_instances": count, "logical_storage_bits": logical_bits,
                          "physical_macro_storage_bits": macro_bits,
                          "register_array_storage_bits": total_register_bits,
                          "physical_storage_bits": physical_bits,
                          "padding_bits": physical_bits - logical_bits,
                          "capacity_utilization": logical_bits / physical_bits,
                          "macro_instances": dict(all_macros), "instances": details}

    kernel = roots("kernel_loader_buffer")
    kernel_files = [row for row in rows if row["module"] == "regfile" and
                    row["path"].startswith(kernel + "/")]
    check("kernel_columns", kernel_files, 16, 16, 48, 16, False, 16, 48,
          force_sram=profile["kernel_force_sram"])

    bias = roots("bias_loader_buffer")
    bias_files = [row for row in rows if row["module"] == "regfile" and
                  row["path"].startswith(bias + "/")]
    bias_depth = capacity["bias_logical_depth"]
    check("bias", bias_files, 1, 64, bias_depth, 8, profile["bias_full_word_mask"],
          capacity["bias_logical_width"], capacity["bias_logical_depth"])

    requant = roots("vec_requant")
    amount_files = [row for row in rows if row["module"] == "regfile" and
                    row["path"].startswith(requant + "/") and
                    row["path"].endswith(".u_product_amount")]
    amount_depth = capacity["product_amount_rows_per_bank"]
    minimum_depth = profile["amount_pair_min_depth"]
    per_word = 2 if minimum_depth is not None and amount_depth >= minimum_depth else 1
    check("product_amount", amount_files, 2, 7 * per_word, amount_depth // per_word,
          7 * per_word, False, 7, amount_depth)
    return selected
