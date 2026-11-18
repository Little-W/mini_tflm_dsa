"""Measure instantiated sequential state with Verilator's JSON elaboration."""
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

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "build/capacity/state_cache"


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
    files = source_files() + sorted((ROOT / "rtl/npu").rglob("*.svh"))
    files += [ROOT / "veri/flist/dut_axil.f", ROOT / "scripts/capacity/model.py",
              ROOT / "scripts/capacity/im2col_cache.py",
              ROOT / "scripts/capacity/elaboration.py", ROOT / "asic/rtl/smic40_sram_1r1w.sv"]
    return {str(p.relative_to(ROOT)): digest(p) for p in files}


def hardware_config(values):
    result = {key: values[key] for key in ("PCR_ENGINE", "SIZE", "IA_CACHE_BLOCKS",
            "PS_FRAME_COUNT", "AXI_READ_OUTSTANDING", "PS_POOL_BYTES", "PS_FORCE_RAW")}
    result["NPU_AXI_DATA_WIDTH"] = values.get("NPU_AXI_DATA_WIDTH", 64)
    result["SHARED_BANK_BYTES"] = values.get("SHARED_BANK_BYTES", 2048)
    result["SHARED_BANK_COUNT"] = values.get("SHARED_BANK_COUNT", 7)
    result["IM2COL_CACHE_BYTES"] = values.get("IM2COL_CACHE_BYTES", 4096)
    return result


def identity(values, source_hashes=None):
    payload = {"hardware": hardware_config(values), "source_sha256": source_hashes or sources_sha256()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def current_report(values, report):
    return bool(report and report.get("passed") and
                report.get("hardware_configuration") == hardware_config(values) and
                report.get("source_sha256") == sources_sha256())


def find_cached(values, cache_dir=CACHE):
    path = Path(cache_dir) / identity(values) / "result.json"
    if path.is_file():
        report = json.loads(path.read_text())
        if current_report(values, report):
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


def array_category(origin, name, ancestors):
    name = name.rsplit(".", 1)[-1]
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
    if origin == "bias_loader_buffer" and name in ("bank0_words", "bank1_words"):
        return "bias_cache"
    if origin == "vec_requant_full" and name in ("ch_multiplier_is_r", "ch_shift_is_r",
                                                 "ch_lshift_is_r", "ch_rshift_is_r", "multiplier_mem",
                                                 "shift_mem", "left_mem", "right_mem"):
        return "requant_is_cache"
    if origin == "vec_s8_fifo_row_ram" and name == "mem":
        return "oa_s16_fifo" if "vec_s16_to_fifo" in ancestors else "oa_s8_fifo"
    if origin == "conv_sdp_ram" and name == "mem":
        return "conv_data_cache"
    if origin == "conv_windowed_cache":
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
                    "mult_buf", "shift_buf", "acc_buf", "result_buf"):
            return "vector_buffers"
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


def register_array_category(origin, name):
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


def inventory(tree):
    refs, width = elaboration_types(tree)
    module_bits, instances, arrays, array_counts, declarations = {}, {}, {}, {}, []
    register_arrays = {}
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
        total = 0
        for ref in sorted(targets):
            var = refs[ref]
            name = variable_names.get(ref, var["name"])
            bits = width(var["dtypep"])
            total += bits
            category = array_category(origin, name, ancestors)
            if category:
                arrays[category] = arrays.get(category, 0) + bits
                array_counts[category] = array_counts.get(category, 0) + 1
            register_category = register_array_category(origin, name)
            if register_category:
                register_arrays[register_category] = register_arrays.get(register_category, 0) + bits
            if origin == "ps_buffer" or "ps_buffer" in ancestors:
                ps_storage_bits += bits
            if origin == "ia_ps_shared_ram" or "ia_ps_shared_ram" in ancestors:
                shared_ram_bits += bits
            declarations.append(dict(path=path + "." + name, module=origin,
                                     name=name, bits=bits, buffer_category=category,
                                     register_array_category=register_category))
        module_bits[origin] = module_bits.get(origin, 0) + total
        instances[origin] = instances.get(origin, 0) + 1
    top = next(node for node in tree["modulesp"] if node.get("name") == "npu_axil_top")
    module(top, top["name"], ())
    return dict(total_bits=sum(module_bits.values()), module_bits=module_bits,
                module_instances=instances, buffer_arrays_bits=arrays, declaration_counts=array_counts,
                register_arrays_bits=register_arrays,
                ps_storage_and_codec_bits=ps_storage_bits,
                shared_ram_and_port_state_bits=shared_ram_bits,
                sequential_declarations=sorted(declarations, key=lambda x: x["path"]))


def measure(values, *, verilator="verilator", output_dir=None, cache_dir=CACHE, keep_tree=False):
    hashes = sources_sha256()
    key = identity(values, hashes)
    cache_file = Path(cache_dir) / key / "result.json"
    cached = find_cached(values, cache_dir)
    if cached is not None:
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / "result.json").write_text(json.dumps(cached, indent=2) + "\n")
        return cached
    executable = shutil.which(str(verilator)) or str(verilator)
    out = Path(output_dir).resolve() if output_dir else cache_file.parent
    out.mkdir(parents=True, exist_ok=True)
    tree_path = out / "elaborated.tree.json"
    command = [executable, "--json-only", "--assert", "-DSYNTHESIS", "-DASIC_SYNTHESIS", "-Wno-fatal",
               "--top-module", "npu_axil_top", "--json-only-output", str(tree_path),
               "--Mdir", str(out / "obj"), "-GDATA_WIDTH=16", "-GWEIGHT_WIDTH=16",
               f'-GBUS_WIDTH={hardware_config(values)["NPU_AXI_DATA_WIDTH"]}',
               f'-GSHARED_BANK_BYTES={hardware_config(values)["SHARED_BANK_BYTES"]}',
               f'-GSHARED_BANK_COUNT={hardware_config(values)["SHARED_BANK_COUNT"]}',
               f'-GIM2COL_CACHE_BYTES={hardware_config(values)["IM2COL_CACHE_BYTES"]}',
               "-GENABLE_VECTOR_ENGINE=1", f'-GVECTOR_PE_COUNT={min(values["SIZE"], 8)}',
               f'-GSIZE={values["SIZE"]}', f'-GIA_CACHE_BLOCKS={values["IA_CACHE_BLOCKS"]}',
               f'-GPS_FRAME_COUNT={values["PS_FRAME_COUNT"]}',
               f'-GAXI_READ_OUTSTANDING={values["AXI_READ_OUTSTANDING"]}',
               "-I" + str(ROOT / "rtl/npu/ps_compact")]
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
                "PS_CAPS", "SHARED_CAPABLE", "MATRIX_S8_BANKS", "MATRIX_S16_BANKS",
                "IM2COL_CACHE_BYTES", "CONV_CACHE_SETS", "CONV_CACHE_WAYS", "CONV_LINE_BYTES")),
            "npu_axil_reg_if": constant_parameters(tree, "npu_axil_reg_if", (
                "PS_CAPS", "PS_POOL_BYTES", "IA_CACHE_BYTES", "SHARED_TOTAL_BYTES",
                "SHARED_BANK_BYTES", "SHARED_IA_BANK_MASK", "PS_DIRECTORY_ROWS", "SHARED_CAPABLE",
                "MATRIX_S8_BANKS", "MATRIX_S16_BANKS", "CONV_CACHE_BYTES")),
            "npu_top": constant_parameters(tree, "npu_top", (
                "SHARED_RAM_ENABLED", "IA_MAX_CACHE_BLOCKS", "IA_REUSE_NUM_MAX",
                "OA_FIFO_BANKS", "OA_S16_FIFO_BANKS", "PS_REQUIRE_RAW_CAPACITY",
                "IM2COL_CACHE_BYTES", "CONV_CACHE_SETS", "CONV_CACHE_WAYS", "CONV_LINE_BYTES")),
        }
    finally:
        if not keep_tree:
            tree_path.unlink(missing_ok=True)
    geometry_options=dict(bank_bytes=values.get("SHARED_BANK_BYTES",2048),
                          bank_count=values.get("SHARED_BANK_COUNT",7) if values["PCR_ENGINE"] else None)
    expected = model.buffer_arrays_bits(values["IA_CACHE_BLOCKS"], values["PS_FRAME_COUNT"],
                                         values["PS_POOL_BYTES"], values["SIZE"], bool(values["PCR_ENGINE"]),
                                         im2col_cache_bytes=hardware_config(values)["IM2COL_CACHE_BYTES"],
                                         **geometry_options)
    expected_registers = model.register_arrays_bits(values["IA_CACHE_BLOCKS"], values["PS_FRAME_COUNT"],
                                                     values["PS_POOL_BYTES"], values["SIZE"], bool(values["PCR_ENGINE"]),
                                                     **geometry_options)
    unchanged = hashes == sources_sha256()
    counts = state["module_instances"]
    architecture = (counts.get("compute_core", 0) == 1 and counts.get("ws_systolic_array", 0) == 1
                    and counts.get("de_diagonalizer", 0) == 0
                    and counts.get("vector_engine", 0) == 1
                    and counts.get("vector_pe", 0) == min(values["SIZE"], 8))
    layout = model.memory_geometry(values["IA_CACHE_BLOCKS"], values["PS_FRAME_COUNT"],
                                   values["PS_POOL_BYTES"], values["SIZE"], bool(values["PCR_ENGINE"]),
                                   **geometry_options)
    shared_data = None
    if layout["shared_ia_ps_enabled"]:
        banks = layout["shared_physical_bank_count"]
        architecture = architecture and counts.get("ia_ps_shared_ram") == 1 and \
            state["declaration_counts"].get("ia_ps_shared_ram") == banks and \
            "ia_cache" not in state["buffer_arrays_bits"] and "ps_payload" not in state["buffer_arrays_bits"]
        bank_bytes=layout["shared_bank_bytes"]
        macro_count=banks * 8 * ((bank_bytes+2047)//2048)
        shared_data = dict(bank_count=banks, bank_width_bits=128, bank_depth=bank_bytes//16,
                           logical_bytes=layout["shared_total_bytes"],
                           asic_macro="RAMTP128X16", asic_macro_count=macro_count,
                           mapped_sram_bytes=macro_count * 128 * 16 // 8,
                           mapping_source="asic/rtl/smic40_sram_1r1w.sv",
                           physical_capacity=model.physical_shared_memory(bank_bytes, banks))
    else:
        architecture = architecture and counts.get("ia_ps_shared_ram", 0) == 0
    registers = capabilities["npu_axil_reg_if"]
    expected_caps = (0x01000007 | (values["PS_FRAME_COUNT"] << 16) |
                     (int(layout["shared_ia_ps_enabled"]) << 4) | (values["PS_FORCE_RAW"] << 3)) \
                    if values["PCR_ENGINE"] else 0
    capabilities_match = capabilities["npu_axil_top"]["PS_CAPS"] == expected_caps and \
        registers["PS_CAPS"] == expected_caps and \
        capabilities["npu_top"]["OA_FIFO_BANKS"] == layout["output_banks_s8"] and \
        capabilities["npu_top"]["OA_S16_FIFO_BANKS"] == layout["output_banks_s16"] and \
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
        capabilities_match = capabilities_match and cache["IM2COL_CACHE_BYTES"] == \
            cache["CONV_CACHE_SETS"]*cache["CONV_CACHE_WAYS"]*cache["CONV_LINE_BYTES"] == \
            hardware_config(values)["IM2COL_CACHE_BYTES"]
    passed = (unchanged and expected == state["buffer_arrays_bits"] and
              expected_registers == state["register_arrays_bits"] and architecture and capabilities_match)
    report = dict(passed=passed, model_version=model.MODEL_VERSION,
                  scope="Instantiated sequential declarations, including RAM, metadata, PE state, pipeline registers and clock-gate latch.",
                  configuration=values, hardware_configuration=hardware_config(values),
                  source_sha256=hashes, sources_unchanged=unchanged, cache_identity=key,
                  verilator=subprocess.check_output([executable, "--version"], text=True).strip(),
                  command=command, elapsed_seconds=time.monotonic() - start,
                  expected_buffer_arrays_bits=expected, elaborated_state=state,
                  expected_register_arrays_bits=expected_registers,
                  memory_geometry=layout, shared_data_memory=shared_data,
                  capability_parameters=capabilities, capabilities_match=capabilities_match,
                  single_array_and_vector_pe_count=architecture)
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    if passed:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(report, indent=2) + "\n")
    return report
