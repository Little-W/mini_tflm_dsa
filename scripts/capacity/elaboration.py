"""Measure instantiated state and read-only arrays with Verilator's JSON elaboration."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from . import model
from scripts.rtl.source_files import input_files

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "build/capacity/state_cache"
READ_ONLY_ARRAY_SCHEMAS = {
    ("vector_engine", "avg_reciprocal"): "vector_pool_reciprocal_rom",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_files():
    filelist = ROOT / "veri/flist/dut_axil.f"
    files = []
    for line in filelist.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//", "+")):
            continue
        path = (filelist.parent / line).resolve()
        if not path.is_file():
            raise ValueError(f"missing RTL source: {path}")
        if path not in files:
            files.append(path)
    return files


def sources_sha256():
    files = input_files(source_files(), ROOT, [ROOT / "rtl/npu/ps_compact"])
    files += [ROOT / "veri/flist/dut_axil.f", ROOT / "scripts/capacity/model.py",
              ROOT / "scripts/capacity/im2col_cache.py",
               ROOT / "scripts/capacity/elaboration.py", ROOT / "scripts/rtl/source_files.py",
               ROOT / "asic/rtl/smic40_sram_1r1w.sv"]
    return {str(p.relative_to(ROOT)): digest(p) for p in files}


def hardware_config(values):
    result = {key: values[key] for key in ("PCR_ENGINE", "SIZE", "IA_CACHE_BLOCKS",
            "PS_FRAME_COUNT", "AXI_READ_OUTSTANDING", "PS_POOL_BYTES", "PS_FORCE_RAW")}
    result["NPU_AXI_DATA_WIDTH"] = values.get("NPU_AXI_DATA_WIDTH", 64)
    result["IA_COMPACT_ENABLE"] = values.get("IA_COMPACT_ENABLE", 0)
    if type(result["IA_COMPACT_ENABLE"]) is not int or result["IA_COMPACT_ENABLE"] not in (0, 1):
        raise ValueError("IA_COMPACT_ENABLE must be 0 or 1")
    result["SHARED_BANK_BYTES"] = values.get("SHARED_BANK_BYTES", 2048)
    result["SHARED_BANK_COUNT"] = values.get("SHARED_BANK_COUNT", 7)
    result["IM2COL_CACHE_BYTES"] = values.get("IM2COL_CACHE_BYTES", 4096)
    result["CONV_LOW_LATENCY"] = values.get("CONV_LOW_LATENCY", 0)
    if type(result["CONV_LOW_LATENCY"]) is not int or result["CONV_LOW_LATENCY"] not in (0, 1):
        raise ValueError("CONV_LOW_LATENCY must be 0 or 1")
    result["CONV_LINE_BYTES"] = model.im2col_cache.LINE_BYTES
    result["CONV_CACHE_WAYS"] = model.im2col_cache.WAYS
    result["VECTOR_PE_COUNT"] = values.get("VECTOR_PE_COUNT", min(values["SIZE"], 16))
    result["WINDOW_LANES"] = 16 if result["VECTOR_PE_COUNT"] >= 16 else result["NPU_AXI_DATA_WIDTH"] // 8
    shared = bool(values["PCR_ENGINE"] and values["SIZE"] == 16 and
                  6 <= result["SHARED_BANK_COUNT"] <= 9)
    result["SHARED_STORAGE_ENABLE"] = int(shared)
    result["SHARED_QUANT_ENABLE"] = int(not (shared and result["SHARED_BANK_COUNT"] < 8))
    result["QUANT_LANES"] = values["SIZE"] if result["SHARED_QUANT_ENABLE"] else 1
    return result


def identity(values, source_hashes=None, *, target="asic"):
    payload = {"hardware": hardware_config(values), "source_sha256": source_hashes or sources_sha256(),
               "elaboration_target": target}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def current_report(values, report, *, target="asic"):
    return bool(report and report.get("passed") and
                report.get("elaboration_target", "asic") == target and
                report.get("hardware_configuration") == hardware_config(values) and
                report.get("source_sha256") == sources_sha256())


def find_cached(values, cache_dir=CACHE, *, target="asic"):
    path = Path(cache_dir) / identity(values, target=target) / "result.json"
    if path.is_file():
        report = json.loads(path.read_text())
        if current_report(values, report, target=target):
            return report
    return None


def children(node):
    for value in node.values():
        if isinstance(value, list):
            yield from (child for child in value if isinstance(child, dict))
        elif isinstance(value, dict):
            yield value


def constant_parameters(tree, original, names):
    modules = [item for item in tree["modulesp"]
               if item.get("origName", item.get("name")) == original]
    if len(modules) != 1:
        raise ValueError(f"expected one {original} module")
    found = {}

    def visit(node):
        if node.get("type") == "VAR" and node.get("isParam") and node.get("name") in names:
            value = node.get("valuep", [])
            if len(value) != 1 or value[0].get("type") != "CONST":
                raise ValueError(f"{original}.{node['name']} is not constant after elaboration")
            match = re.fullmatch(r"\d+'s?([hodb])([0-9a-fA-F]+)", value[0]["name"])
            if match is None:
                raise ValueError("unsupported Verilator constant: " + value[0]["name"])
            if node["name"] in found:
                raise ValueError(f"duplicate {original}.{node['name']} parameter")
            found[node["name"]] = int(match[2], {"h": 16, "o": 8, "d": 10, "b": 2}[match[1]])
        for child in children(node):
            visit(child)
    visit(modules[0])
    return found


def elaboration_types(tree):
    refs = {}

    def index(node):
        if "addr" in node:
            refs[node["addr"]] = node
        for child in children(node):
            index(child)
    index(tree)

    @lru_cache(None)
    def width(ref):
        node = refs[ref]
        kind = node["type"]
        if kind == "BASICDTYPE":
            if "range" not in node:
                return 1
            left, right = map(int, node["range"].split(":"))
            return abs(left - right) + 1
        if kind in ("UNPACKARRAYDTYPE", "PACKARRAYDTYPE"):
            left, right = map(int, node["declRange"].strip("[]").split(":"))
            return (abs(left - right) + 1) * width(node["refDTypep"])
        if kind in ("REFDTYPE", "ENUMDTYPE", "CONSTDTYPE"):
            return width(node["refDTypep"])
        if kind == "STRUCTDTYPE" and node.get("packed"):
            return sum(width(member["refDTypep"]) for member in node["membersp"])
        raise ValueError("unsupported Verilator dtype: " + kind)
    return refs, width


def array_category(origin, name, ancestors, instance_path=""):
    declaration_name = name
    name = name.rsplit(".", 1)[-1]
    if origin == "regfile" and name == "mem":
        if "requant_group_buffer" in ancestors:
            return "requant_input_rows"
        if "vec_requant" in ancestors and ".g_ws_bank_write." in instance_path:
            return None
        if "vector_engine" in ancestors and instance_path.rsplit(".", 1)[-1] == "u_bias_storage":
            return "vector_buffers"
        if "vector_weight_store" in ancestors:
            return "vector_buffers"
        if instance_path.rsplit(".", 1)[-1] in (
                "u_prefetch_keys", "u_prefetch_selected", "u_prefetch_payload", "u_prefetch_retire", "u_prefetch_index"):
            return "conv_prefetch_queue"
        if "vec_s8_fifo_row_ram" in ancestors:
            return "oa_s16_fifo" if "vec_s16_to_fifo" in ancestors else "oa_s8_fifo"
        for owner, category in (
                ("ia_ps_shared_ram", "ia_ps_shared_ram"),
                ("ia_ps_channel_ram", "ia_ps_shared_ram"),
                ("conv_sdp_ram", "conv_data_cache"),
                ("conv_windowed_cache", "conv_cache_metadata"),
                ("ia_loader_cache_mgr", "ia_cache"),
                ("ia_buffer_wrapper", "ia_cache"),
                ("kernel_loader_buffer", "kernel_cache"),
                ("bias_loader_buffer", "bias_cache"),
                ("vector_quant_params", "vector_buffers"),
                ("vec_requant", "requant_is_cache"),
                ("ps_frame_store", "ps_decoded_fifo"),
                ("ps_buffer_exact_ram", "ps_payload")):
            if owner in ancestors:
                return category
    if origin == "ia_ps_shared_ram" and name == "ram":
        return "ia_ps_shared_ram"
    if origin == "ia_loader" and name in ("cache_tags", "cache_tags_valid"):
        return "ia_cache_tags"
    if origin == "ia_loader_ctrl" and name in ("slot_rows_reg", "blk_valid", "blk_busy"):
        return "ia_slot_metadata"
    if origin == "ia_loader_cache_mgr" and name == "slot_written_cols":
        return "ia_slot_metadata"
    if origin == "pseudo_dual_port_ram" and name == "ram" and "ia_loader_cache_mgr" in ancestors:
        return "ia_cache"
    if origin == "ia_buffer_wrapper" and name == "mem":
        return "ia_cache"
    if origin in ("kernel_loader_row_ram", "kernel_loader_column_ram") and name == "mem":
        return "kernel_cache"
    if origin == "bias_loader_buffer" and name in ("bank0_words", "bank1_words", "bias_words"):
        return "bias_cache"
    if origin == "vec_requant" and name in ("ch_multiplier_is_r", "ch_shift_is_r",
                                                 "ch_lshift_is_r", "ch_rshift_is_r", "multiplier_mem",
                                                 "shift_mem", "left_mem", "right_mem",
                                                 "product_multiplier_mem", "product_amount_mem"):
        return "requant_is_cache"
    if origin == "vec_s8_fifo_row_ram" and name == "mem":
        return "oa_s16_fifo" if "vec_s16_to_fifo" in ancestors else "oa_s8_fifo"
    if origin == "conv_sdp_ram" and name == "mem":
        return "conv_data_cache"
    if origin == "conv_windowed_cache":
        if name == "prefetch_key_entries":
            return "conv_prefetch_queue"
        if name in ("valid", "lookup_tag_ram", "pf_tag_ram", "incoming_tag_ram",
                    "next_tag_ram", "hint_tag_ram", "incoming_hold_ram", "next_hold_ram",
                    "fill_epoch_ram", "hit_epoch_ram", "fill_rank_ram", "hit_rank_ram",
                    "hint_rank_ram", "epoch_is_hit", "rank_source"):
            return "conv_cache_metadata"
        if name.startswith("pf_queue_"):
            return "conv_prefetch_queue"
        if name == "request_queue":
            return "conv_request_queue"
        if name in ("response_queue_data", "response_queue_error"):
            return "conv_response_queue"
    if origin == "vector_engine":
        if name in ("input_buf", "rhs_buf", "weight_buf", "bias_buf",
                    "mult_buf", "shift_buf", "right_shift_buf", "acc_buf", "result_buf", "soft_exp_memory"):
            return "vector_buffers"
        if name == "dw_snapshot":
            return "vector_dw_snapshot"
        if name == "dw_result_bytes":
            return "vector_dw_result_queue"
    if origin == "vector_engine_operand_store":
        if name in ("input_buf", "rhs_buf", "acc_buf") or \
                name == "mem" and (declaration_name.startswith("g_input_memory.") or
                                   ".g_input_memory." in instance_path):
            return "vector_buffers"
    if origin == "vector_banked_writeback" and name == "memory":
        return "vector_write_queue"
    if origin == "vector_writeback" and name in ("pending_data", "payload_data"):
        return "vector_write_queue"
    if origin == "vector_weight_bank" and name == "data":
        return "vector_buffers"
    if origin == "ps_frame_store":
        return {"payload_ram": "ps_payload", "directory": "ps_directory",
                "frame_lengths": "ps_frame_lengths", "frame_valid": "ps_frame_valid",
                "frame_max_record_words": "ps_frame_max_record_words",
                "free_bitmap": "ps_free_bitmap", "bank_free_count": "ps_bank_free_count",
                "resident_words": "ps_resident_words",
                "decoded_ram": "ps_decoded_fifo", "decoded_first_mem": "ps_decoded_first"}.get(name)
    if origin == "ps_buffer_exact_ram" and name == "ram":
        return "ps_payload"
    if origin == "ps_buffer_wide_fifo" and name == "frame_len_fifo":
        return "ps_frame_lengths"
    return None


def register_array_category(origin, name, ancestors=(), instance_path=""):
    if origin == "regfile" and name.rsplit(".", 1)[-1] == "mem" and \
            "vec_requant" in ancestors and ".g_ws_bank_write." in instance_path:
        return "requant_ws_parameters"
    if origin == "vec_requant" and name in (
            "ch_multiplier_lane_r", "ch_shift_lane_r", "ch_product_multiplier_lane_r",
            "ch_product_amount_lane_r"):
        return "requant_ws_parameters"
    if origin == "compute_core" and name in (
            "row_valid_pipe", "row_final_pipe", "row_init_pipe", "row_last_pipe",
            "final_group_complete_q"):
        return "core_row_metadata"
    if origin == "ps_adaptive_encoder" and name in ("s1_nonzero_mask", "s1_sparse_width"):
        return "ps_sparse_metadata"
    if origin == "ps_buffer" and ".g_replay_skew[" in "." + name and name.endswith(".values"):
        return "ps_replay_skew"
    if (origin == "ia_loader_cache_mgr" and ".g_external_ram.g_diagonal[" in "." + name
            and name.endswith(".values")):
        return "ia_diagonal_skew"
    return None


def vector_storage_inventory(state, shared_enabled, size=16, max_taps=49):
    """核对向量数据的实际存储位置，保留同步读输出和工作寄存器的完整计数。"""
    counts = state["module_instances"]
    declarations = state["sequential_declarations"]
    weights = [item for item in declarations
               if item["module"] == "vector_weight_bank" or
               ".u_weights." in item["path"] and item["name"].rsplit(".", 1)[-1] == "mem" or
               item["module"] == "vector_engine" and
               item["name"].rsplit(".", 1)[-1] == "weight_buf"]
    snapshots = [item for item in declarations
                 if item["buffer_category"] == "vector_dw_snapshot"]
    accumulators = [item for item in declarations
                    if item["module"] in ("vector_engine", "vector_engine_operand_store") and
                    item["name"].rsplit(".", 1)[-1] == "acc_buf"]
    adapter_count = counts.get("vector_shared_store", 0)
    adapter_state = [item for item in declarations if item["module"] == "vector_shared_store"]
    private_weight_modules = counts.get("vector_weight_store", 0) + counts.get("vector_weight_bank", 0)
    shared_ram_count = counts.get("ia_ps_shared_ram", 0) + counts.get("ia_ps_channel_ram", 0)
    if shared_enabled:
        passed = (adapter_count == 1 and shared_ram_count == 1 and
                  private_weight_modules == 0 and not weights and not snapshots)
    else:
        passed = (adapter_count == 0 and private_weight_modules > 0 and
                  sum(item["bits"] for item in weights) == size * max_taps * 8 and
                  sum(item["bits"] for item in snapshots) == size * 32)
    passed = passed and sum(item["bits"] for item in accumulators) == size * 32
    return dict(passed=passed, shared_storage_enabled=bool(shared_enabled),
                adapter_instances=adapter_count, shared_ram_instances=shared_ram_count,
                adapter_state_bits=sum(item["bits"] for item in adapter_state),
                adapter_state_declarations=adapter_state,
                private_weight_module_instances=private_weight_modules,
                private_weight_declarations=weights, private_snapshot_declarations=snapshots,
                working_accumulator_declarations=accumulators)


def read_only_arrays(node, refs, width, variable_names):
    """按明确的数组类别和实际常量写入、同步读取结构识别只读存储。"""
    origin = node.get("origName", node["name"])
    selected = {ref: READ_ONLY_ARRAY_SCHEMAS[(origin, name)]
                for ref, name in variable_names.items()
                if (origin, name) in READ_ONLY_ARRAY_SCHEMAS}
    if not selected:
        return {}
    writes = {ref: [] for ref in selected}
    registered_reads = set()

    def scan(child, context=None, clocked=False, assignment=None):
        kind = child.get("type")
        if kind == "CELL":
            return
        if kind == "INITIAL":
            context, clocked = "initial", False
        elif kind == "ALWAYS":
            context = "continuous" if child.get("keyword") == "cont_assign" else None
            clocked = any(item.get("edgeType") in ("POS", "NEG")
                          for tree in child.get("sentreep", [])
                          for item in tree.get("sensesp", []))
        elif kind in ("IF", "CASE", "WHILE", "FOR", "FOREACH", "DELAY", "WAIT"):
            context = None
        if kind in ("ASSIGN", "ASSIGNW", "ASSIGNDLY"):
            assignment = (child, context, clocked)
        if kind == "VARREF" and child.get("varp") in selected:
            ref = child["varp"]
            if child.get("access") in ("WR", "RW"):
                writes[ref].append(assignment)
            if child.get("access") in ("RD", "RW") and assignment and \
                    assignment[0]["type"] == "ASSIGNDLY" and assignment[2]:
                registered_reads.add(ref)
        for descendant in children(child):
            scan(descendant, context, clocked, assignment)
    scan(node)

    def constant(value):
        if value.get("type") != "CONST":
            raise ValueError("只读表的地址和内容必须在展开后为常量")
        match = re.fullmatch(r"\d+'s?([hodb])([0-9a-fA-F]+)", value["name"])
        if match is None:
            raise ValueError("只读表包含未定义的常量位")
        return int(match[2], {"h": 16, "o": 8, "d": 10, "b": 2}[match[1]])

    result = {}
    for ref, category in selected.items():
        var = refs[ref]
        dtype = refs[var["dtypep"]]
        if dtype.get("type") != "UNPACKARRAYDTYPE":
            raise ValueError(f"{origin}.{variable_names[ref]} 必须为只读数组")
        left, right = map(int, dtype["declRange"].strip("[]").split(":"))
        words = abs(left-right)+1
        word_bits = width(dtype["refDTypep"])
        initialized, contexts = set(), set()
        for assignment in writes[ref]:
            if assignment is None:
                raise ValueError("只读表存在非赋值形式的写入")
            statement, context, _ = assignment
            if (statement["type"], context) not in (("ASSIGN", "initial"), ("ASSIGNW", "continuous")):
                raise ValueError("只读表存在运行期写入或条件初始化")
            if statement.get("timingControlp"):
                raise ValueError("只读表初始化包含延迟控制")
            lhs, rhs = statement.get("lhsp", []), statement.get("rhsp", [])
            if len(lhs) != 1 or len(rhs) != 1 or lhs[0].get("type") != "ARRAYSEL":
                raise ValueError("只读表需要完整数组元素的常量赋值")
            source, index = lhs[0].get("fromp", []), lhs[0].get("bitp", [])
            if len(source) != 1 or source[0].get("type") != "VARREF" or \
                    source[0].get("varp") != ref or len(index) != 1:
                raise ValueError("只读表的数组元素选择形式不受支持")
            address, value = constant(index[0]), constant(rhs[0])
            # ARRAYSEL 使用从零开始的展开后元素偏移。
            if address not in range(words) or address in initialized:
                raise ValueError("只读表初始化地址超出数组范围或重复")
            if value >= 1 << word_bits:
                raise ValueError("只读表常量超出元素位宽")
            initialized.add(address)
            contexts.add(context)
        if initialized != set(range(words)):
            raise ValueError("只读表未逐项初始化完整数组")
        if ref not in registered_reads:
            raise ValueError("只读表缺少时钟边沿的同步读取")
        result[ref] = dict(category=category, words=words, word_bits=word_bits,
                           initialized_words=len(initialized),
                           initialization_kinds=sorted(contexts), read_latency_cycles=1)
    return result


def inventory(tree):
    refs, width = elaboration_types(tree)
    module_bits, instances, arrays, array_counts, declarations = {}, {}, {}, {}, []
    register_arrays = {}
    read_only_bits, read_only_declarations = {}, []
    ps_storage_bits = 0
    shared_ram_bits = 0

    def written_variables(node, targets):
        if node.get("type") == "VARREF" and node.get("access") in ("WR", "RW"):
            variable = refs[node["varp"]]
            if variable.get("lifetime") != "VAUTOM":
                targets.add(node["varp"])
        for child in children(node):
            written_variables(child, targets)

    def module(node, path, ancestors):
        nonlocal ps_storage_bits, shared_ram_bits
        origin = node.get("origName", node["name"])
        targets = set()
        variable_names = {}

        def scan(child, scope=""):
            if child.get("type") == "GENBLOCK" and child.get("name"):
                scope += child["name"] + "."
            if child.get("type") == "VAR":
                variable_names[child["addr"]] = scope + child["name"]
            if child.get("type") == "CELL":
                module(refs[child["modp"]], path + "." + scope + child["name"], ancestors + (origin,))
                return
            if child.get("type") == "ASSIGNDLY":
                for lhs in child.get("lhsp", []):
                    written_variables(lhs, targets)
            elif child.get("type") == "ALWAYS" and child.get("keyword") == "always_latch":
                for statement in child.get("stmtsp", []):
                    written_variables(statement, targets)
            for descendant in children(child):
                scan(descendant, scope)
        scan(node)
        read_only = read_only_arrays(node, refs, width, variable_names)
        total = 0
        for ref in sorted(targets | set(read_only)):
            var = refs[ref]
            name = variable_names.get(ref, var["name"])
            bits = width(var["dtypep"])
            total += bits
            category = read_only[ref]["category"] if ref in read_only else \
                array_category(origin, name, ancestors, path)
            if category:
                arrays[category] = arrays.get(category, 0) + bits
                array_counts[category] = array_counts.get(category, 0) + 1
            register_category = register_array_category(origin, name, ancestors, path)
            if register_category:
                register_arrays[register_category] = register_arrays.get(register_category, 0) + bits
            if origin == "ps_buffer" or "ps_buffer" in ancestors:
                ps_storage_bits += bits
            if origin in ("ia_ps_shared_ram", "ia_ps_channel_ram") or any(
                    owner in ancestors for owner in ("ia_ps_shared_ram", "ia_ps_channel_ram")):
                shared_ram_bits += bits
            declaration = dict(path=path + "." + name, module=origin,
                               name=name, bits=bits, buffer_category=category,
                               register_array_category=register_category)
            if ref in read_only:
                read_only_bits[category] = read_only_bits.get(category, 0) + bits
                read_only_declarations.append(dict(declaration, **read_only[ref]))
            else:
                declarations.append(declaration)
        module_bits[origin] = module_bits.get(origin, 0) + total
        instances[origin] = instances.get(origin, 0) + 1
    top = next(node for node in tree["modulesp"] if node.get("name") == "npu_axil_top")
    module(top, top["name"], ())
    return dict(total_bits=sum(module_bits.values()), module_bits=module_bits,
                sequential_bits=sum(item["bits"] for item in declarations),
                read_only_bits=sum(read_only_bits.values()),
                module_instances=instances, buffer_arrays_bits=arrays, declaration_counts=array_counts,
                register_arrays_bits=register_arrays,
                read_only_arrays_bits=read_only_bits,
                read_only_declarations=sorted(read_only_declarations, key=lambda x: x["path"]),
                ps_storage_and_codec_bits=ps_storage_bits,
                shared_ram_and_port_state_bits=shared_ram_bits,
                sequential_declarations=sorted(declarations, key=lambda x: x["path"]))


def measure(values, *, verilator="verilator", output_dir=None, cache_dir=CACHE, keep_tree=False,
            target="asic"):
    if target not in ("asic", "generic"):
        raise ValueError("Elaboration target must be asic or generic")
    hashes = sources_sha256()
    key = identity(values, hashes, target=target)
    cache_file = Path(cache_dir) / key / "result.json"
    cached = find_cached(values, cache_dir, target=target)
    if cached is not None:
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / "result.json").write_text(json.dumps(cached, indent=2) + "\n")
        return cached
    executable = shutil.which(str(verilator)) or str(verilator)
    out = Path(output_dir).resolve() if output_dir else cache_file.parent
    out.mkdir(parents=True, exist_ok=True)
    tree_path = out / "elaborated.tree.json"
    # 通用目标与周期仿真采用相同参数分支，独立测试观察器不参加容量统计。
    target_defines = ["-DSYNTHESIS", "-DASIC_SYNTHESIS"] if target == "asic" else []
    command = [executable, "--json-only", "--assert", *target_defines, "-Wno-fatal",
               "--top-module", "npu_axil_top", "--json-only-output", str(tree_path),
               "--Mdir", str(out / "obj"), "-GDATA_WIDTH=16", "-GWEIGHT_WIDTH=16",
               f'-GBUS_WIDTH={hardware_config(values)["NPU_AXI_DATA_WIDTH"]}',
               f'-GIA_COMPACT_ENABLE={hardware_config(values)["IA_COMPACT_ENABLE"]}',
               f'-GSHARED_BANK_BYTES={hardware_config(values)["SHARED_BANK_BYTES"]}',
               f'-GSHARED_BANK_COUNT={hardware_config(values)["SHARED_BANK_COUNT"]}',
               f'-GIM2COL_CACHE_BYTES={hardware_config(values)["IM2COL_CACHE_BYTES"]}',
               f'-GCONV_LOW_LATENCY={hardware_config(values)["CONV_LOW_LATENCY"]}',
               "-GENABLE_VECTOR_ENGINE=1", f'-GVECTOR_PE_COUNT={hardware_config(values)["VECTOR_PE_COUNT"]}',
               f'-GSIZE={values["SIZE"]}', f'-GIA_CACHE_BLOCKS={values["IA_CACHE_BLOCKS"]}',
               f'-GPS_FRAME_COUNT={values["PS_FRAME_COUNT"]}',
               f'-GAXI_READ_OUTSTANDING={values["AXI_READ_OUTSTANDING"]}',
               "-I" + str(ROOT / "rtl/npu/ps_compact"), "-I" + str(ROOT / "include")]
    if values["PCR_ENGINE"]:
        command += ["-DGEMPACT_PS_COMPRESS=1", f'-DGEMMORA_PS_POOL_BYTES={values["PS_POOL_BYTES"]}']
        if values["PS_FORCE_RAW"]:
            command.append("-DGEMMORA_PS_FORCE_RAW=1")
    command += list(map(str, source_files()))
    start = time.monotonic()
    with (out / "elaboration.log").open("w") as log:
        run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if run.returncode:
        raise ValueError(f"Verilator elaboration failed; see {out / 'elaboration.log'}")
    try:
        tree = json.loads(tree_path.read_text())
        state = inventory(tree)
        capabilities = {
            "npu_axil_top": constant_parameters(tree, "npu_axil_top", (
                "IA_COMPACT_ENABLE", "PS_CAPS", "SHARED_CAPABLE", "MATRIX_S8_BANKS", "MATRIX_S16_BANKS",
                "IM2COL_CACHE_BYTES", "CONV_CACHE_SETS", "CONV_CACHE_WAYS", "CONV_LINE_BYTES", "CONV_LOW_LATENCY")),
            "npu_axil_reg_if": constant_parameters(tree, "npu_axil_reg_if", (
                "PS_CAPS", "PS_POOL_BYTES", "IA_CACHE_BYTES", "SHARED_TOTAL_BYTES",
                "SHARED_BANK_BYTES", "SHARED_IA_BANK_MASK", "PS_DIRECTORY_ROWS", "SHARED_CAPABLE",
                "MATRIX_S8_BANKS", "MATRIX_S16_BANKS", "CONV_CACHE_BYTES")),
            "npu_top": constant_parameters(tree, "npu_top", (
                "IA_COMPACT_ENABLE", "SHARED_RAM_ENABLED", "IA_MAX_CACHE_BLOCKS",
                "IM2COL_CACHE_BYTES", "CONV_CACHE_SETS", "CONV_CACHE_WAYS", "CONV_LINE_BYTES", "CONV_LOW_LATENCY",
                "VECTOR_PE_COUNT", "WINDOW_LANES", "MATRIX_INPUT_LANES",
                "REQUANT_COMPUTE_LANES", "DW_SHARED_QUANT_ENABLE")),
            "npu_matrix_engine": constant_parameters(tree, "npu_matrix_engine", (
                "IA_REUSE_NUM_MAX", "OA_FIFO_BANKS", "OA_S16_FIFO_BANKS")),
            "vector_engine": constant_parameters(tree, "vector_engine", (
                "TILE", "MAX_TAPS", "PE_COUNT", "WINDOW_LANES", "QUANT_LANES",
                "SHARED_QUANT_ENABLE", "SHARED_STORAGE_ENABLE")),
            "conv_im2col_frontend": constant_parameters(tree, "conv_im2col_frontend", (
                "LANES", "NARROW_LANES", "p_cache_read_width", "REGISTER_DESCRIPTOR",
                "REGISTER_ROW_ADDRESS", "REGISTER_CACHE_REQUEST", "CACHE_RESPONSE_DEPTH")),
        }
    finally:
        if not keep_tree:
            tree_path.unlink(missing_ok=True)
    geometry_options=dict(bank_bytes=values.get("SHARED_BANK_BYTES",2048),
                          bank_count=values.get("SHARED_BANK_COUNT",7) if values["PCR_ENGINE"] else None,
                          ia_compact_enable=bool(hardware_config(values)["IA_COMPACT_ENABLE"]))
    expected = model.buffer_arrays_bits(values["IA_CACHE_BLOCKS"], values["PS_FRAME_COUNT"],
                                         values["PS_POOL_BYTES"], values["SIZE"], bool(values["PCR_ENGINE"]),
                                         im2col_cache_bytes=hardware_config(values)["IM2COL_CACHE_BYTES"],
                                         bus_width=hardware_config(values)["NPU_AXI_DATA_WIDTH"],
                                         vector_pe_count=hardware_config(values)["VECTOR_PE_COUNT"],
                                         conv_low_latency=bool(hardware_config(values)["CONV_LOW_LATENCY"]),
                                         target=target,
                                         **geometry_options)
    expected_registers = model.register_arrays_bits(values["IA_CACHE_BLOCKS"], values["PS_FRAME_COUNT"],
                                                     values["PS_POOL_BYTES"], values["SIZE"], bool(values["PCR_ENGINE"]),
                                                     **geometry_options)
    unchanged = hashes == sources_sha256()
    counts = state["module_instances"]
    architecture = (counts.get("compute_core", 0) == 1 and counts.get("ws_systolic_array", 0) == 1
                    and counts.get("de_diagonalizer", 0) == 0
                    and counts.get("vector_engine", 0) == 1
                    and counts.get("vector_pe", 0) == hardware_config(values)["VECTOR_PE_COUNT"])
    vector_parameters = capabilities["vector_engine"]
    frontend_parameters = capabilities["conv_im2col_frontend"]
    architecture = architecture and \
        vector_parameters["PE_COUNT"] == hardware_config(values)["VECTOR_PE_COUNT"] and \
        vector_parameters["QUANT_LANES"] == hardware_config(values)["QUANT_LANES"] and \
        vector_parameters["SHARED_QUANT_ENABLE"] == hardware_config(values)["SHARED_QUANT_ENABLE"] and \
        capabilities["npu_top"]["DW_SHARED_QUANT_ENABLE"] == hardware_config(values)["SHARED_QUANT_ENABLE"] and \
        vector_parameters["WINDOW_LANES"] == hardware_config(values)["WINDOW_LANES"] and \
        capabilities["npu_top"]["WINDOW_LANES"] == hardware_config(values)["WINDOW_LANES"] and \
        frontend_parameters["LANES"] == hardware_config(values)["WINDOW_LANES"] and \
        frontend_parameters["p_cache_read_width"] == 8 * hardware_config(values)["WINDOW_LANES"]
    conv_low_latency = hardware_config(values)["CONV_LOW_LATENCY"]
    architecture = architecture and \
        capabilities["npu_axil_top"]["CONV_LOW_LATENCY"] == conv_low_latency and \
        capabilities["npu_top"]["CONV_LOW_LATENCY"] == conv_low_latency and \
        all(frontend_parameters[key] == 1 - conv_low_latency for key in (
            "REGISTER_DESCRIPTOR", "REGISTER_ROW_ADDRESS", "REGISTER_CACHE_REQUEST")) and \
        frontend_parameters["CACHE_RESPONSE_DEPTH"] == (1 if conv_low_latency else 2)
    layout = model.memory_geometry(values["IA_CACHE_BLOCKS"], values["PS_FRAME_COUNT"],
                                   values["PS_POOL_BYTES"], values["SIZE"], bool(values["PCR_ENGINE"]),
                                   **geometry_options)
    vector_storage = vector_storage_inventory(state, layout["shared_ia_ps_enabled"],
                                              values["SIZE"], 49)
    architecture = architecture and vector_storage["passed"] and \
        vector_parameters["SHARED_STORAGE_ENABLE"] == int(layout["shared_ia_ps_enabled"]) and \
        vector_parameters["TILE"] == values["SIZE"] and vector_parameters["MAX_TAPS"] == 49
    shared_data = None
    if layout["shared_ia_ps_enabled"]:
        banks = layout["shared_physical_bank_count"]
        bank_bytes = layout["shared_bank_bytes"]
        fixed_channels = counts.get("ia_ps_channel_ram", 0) == 1
        memory_declarations = [item for item in state["sequential_declarations"]
                               if item["buffer_category"] == "ia_ps_shared_ram"]
        if fixed_channels:
            maximum_ia = 4 if banks >= 8 else 2
            rows = bank_bytes // 16
            chunk_rows = rows // 4
            expected_memory_bits = ([128 * rows] + [128 * chunk_rows] * (4 * (maximum_ia - 1)) +
                                    [128 * (banks - maximum_ia) * chunk_rows] * 4)
            architecture = architecture and counts.get("ia_ps_shared_ram", 0) == 0 and \
                sorted(item["bits"] for item in memory_declarations) == sorted(expected_memory_bits)
            shared_data = dict(layout="fixed_ps_channels", bank_count=banks,
                               logical_bytes=layout["shared_total_bytes"],
                               memory_declaration_bits=sorted(expected_memory_bits),
                               physical_capacity=None)
        else:
            architecture = architecture and counts.get("ia_ps_shared_ram") == 1 and \
                state["declaration_counts"].get("ia_ps_shared_ram") == banks and \
                all(item["bits"] == bank_bytes * 8 for item in memory_declarations)
            macro_count = banks * 8 * ((bank_bytes + 2047) // 2048)
            shared_data = dict(layout="rotating_ps_banks", bank_count=banks,
                               bank_width_bits=128, bank_depth=bank_bytes//16,
                               logical_bytes=layout["shared_total_bytes"],
                               asic_macro="RAMTP128X16", asic_macro_count=macro_count,
                               mapped_sram_bytes=macro_count * 128 * 16 // 8,
                               mapping_source="asic/rtl/smic40_sram_1r1w.sv",
                               physical_capacity=model.physical_shared_memory(bank_bytes, banks))
        architecture = architecture and "ia_cache" not in state["buffer_arrays_bits"] and \
            "ps_payload" not in state["buffer_arrays_bits"]
    else:
        architecture = architecture and counts.get("ia_ps_shared_ram", 0) == 0 and \
            counts.get("ia_ps_channel_ram", 0) == 0
    registers = capabilities["npu_axil_reg_if"]
    expected_caps = (0x01000003 | (hardware_config(values)["IA_COMPACT_ENABLE"] << 2) |
                     (values["PS_FRAME_COUNT"] << 16) |
                     (int(layout["shared_ia_ps_enabled"]) << 4) | (values["PS_FORCE_RAW"] << 3)) \
                    if values["PCR_ENGINE"] else 0
    capabilities_match = capabilities["npu_axil_top"]["PS_CAPS"] == expected_caps and \
        registers["PS_CAPS"] == expected_caps and \
        capabilities["npu_axil_top"]["IA_COMPACT_ENABLE"] == hardware_config(values)["IA_COMPACT_ENABLE"] and \
        capabilities["npu_top"]["IA_COMPACT_ENABLE"] == hardware_config(values)["IA_COMPACT_ENABLE"] and \
        capabilities["npu_matrix_engine"]["IA_REUSE_NUM_MAX"] == layout["max_r_s8"] and \
        capabilities["npu_matrix_engine"]["OA_FIFO_BANKS"] == layout["output_banks_s8"] and \
        capabilities["npu_matrix_engine"]["OA_S16_FIFO_BANKS"] == layout["output_banks_s16"] and \
        capabilities["npu_axil_top"]["MATRIX_S8_BANKS"] == layout["output_banks_s8"] and \
        capabilities["npu_axil_top"]["MATRIX_S16_BANKS"] == layout["output_banks_s16"] and \
        registers["MATRIX_S8_BANKS"] == layout["output_banks_s8"] and \
        registers["MATRIX_S16_BANKS"] == layout["output_banks_s16"] and \
        registers["CONV_CACHE_BYTES"] == hardware_config(values)["IM2COL_CACHE_BYTES"] and \
        registers["SHARED_CAPABLE"] == int(layout["shared_ia_ps_enabled"]) and \
        registers["SHARED_TOTAL_BYTES"] == layout["shared_total_bytes"] and \
        registers["SHARED_BANK_BYTES"] == layout["shared_bank_bytes"] and \
        registers["SHARED_IA_BANK_MASK"] == layout["shared_ia_bank_mask"] and \
        registers["PS_DIRECTORY_ROWS"] == (model.SHARED_DIRECTORY_ROWS if layout["shared_ia_ps_enabled"] else 0)
    for module_name in ("npu_axil_top", "npu_top"):
        cache=capabilities[module_name]
        capabilities_match = capabilities_match and \
            cache["CONV_LINE_BYTES"] == hardware_config(values)["CONV_LINE_BYTES"] and \
            cache["CONV_CACHE_WAYS"] == hardware_config(values)["CONV_CACHE_WAYS"]
        capabilities_match = capabilities_match and cache["IM2COL_CACHE_BYTES"] == \
            cache["CONV_CACHE_SETS"]*cache["CONV_CACHE_WAYS"]*cache["CONV_LINE_BYTES"] == \
            hardware_config(values)["IM2COL_CACHE_BYTES"]
    passed = (unchanged and expected == state["buffer_arrays_bits"] and
              expected_registers == state["register_arrays_bits"] and architecture and capabilities_match)
    report = dict(passed=passed, model_version=model.MODEL_VERSION, elaboration_target=target,
                  scope="Instantiated sequential declarations and verified read-only arrays, including RAM, ROM, metadata, PE state, pipeline registers and clock-gate latch.",
                  configuration=values, hardware_configuration=hardware_config(values),
                  source_sha256=hashes, sources_unchanged=unchanged, cache_identity=key,
                  verilator=subprocess.check_output([executable, "--version"], text=True).strip(),
                  command=command, elapsed_seconds=time.monotonic() - start,
                  expected_buffer_arrays_bits=expected, elaborated_state=state,
                  expected_register_arrays_bits=expected_registers,
                  memory_geometry=layout, shared_data_memory=shared_data,
                  capability_parameters=capabilities, capabilities_match=capabilities_match,
                  vector_storage=vector_storage,
                  single_array_and_vector_pe_count=architecture)
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    if passed:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(report, indent=2) + "\n")
    return report
