"""Shared-array buffer sizing and conservative host tiling.

Buffer arrays follow the full INT16, WS/IS, per-channel, Conv and vector engine
configuration. Complete sequential state is obtained from a source-matched
Verilator elaboration, including every pipeline register and PE register.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "veri/top_regression"))
from host_tiling import plan_dispatch, payload_bound  # noqa: E402
from . import device_planner

TILE = 16
POOL_ALIGNMENT = 64
MAX_POOL_BYTES = 1 << 24
CACHE_CHOICES = (2, 4, 8, 16)
FRAME_CHOICES = (4, 8, 16, 25)
SCOPES = ("logical-state", "buffer-ram")
REPRESENTATIONS = ("adaptive", "raw32")
MODEL_VERSION = "dip-shared-bank-v3"
DECODE_FIFO_ROWS = 8
DECODE_PREFETCH_CREDITS = 7
SHARED_BANK_BYTES = 2048
SHARED_BANK_BYTE_CHOICES = (1024, 2048, 4096)
SHARED_MIN_BANKS = 6
SHARED_MAX_BANKS = 9
SHARED_DIRECTORY_ROWS = 1024


def ceil_div(x, y):
    return (x + y - 1) // y


def _integer(value, name, minimum=1, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        suffix = f"..{maximum}" if maximum is not None else " or greater"
        raise ValueError(f"{name} must be an integer in {minimum}{suffix}")
    return value


def geometry(cache, frames, pool_bytes, size=16, compressed=True, *, shared=None,
             bank_bytes=SHARED_BANK_BYTES, bank_count=None):
    _integer(cache, "IA cache blocks", 2, 64)
    _integer(frames, "PS frame count", 1, 64)
    _integer(size, "array size", 2, 32)
    if cache & (cache - 1) or size & (size - 1):
        raise ValueError("array size and IA cache blocks must be powers of two")
    _integer(pool_bytes, "PS pool bytes", 0, MAX_POOL_BYTES)
    if compressed and (size != TILE or pool_bytes < POOL_ALIGNMENT or pool_bytes % POOL_ALIGNMENT):
        raise ValueError("compressed PS requires SIZE=16 and a positive multiple-of-64 pool")
    _integer(bank_bytes, "shared bank bytes")
    if bank_bytes not in SHARED_BANK_BYTE_CHOICES:
        raise ValueError(f"shared bank bytes must be one of {SHARED_BANK_BYTE_CHOICES}")
    if bank_count is not None:
        _integer(bank_count, "shared bank count", SHARED_MIN_BANKS, SHARED_MAX_BANKS)
    storage = _storage_geometry(cache, frames, pool_bytes, size, compressed, shared,
                                bank_bytes, bank_count)
    return storage["max_r_s8"], storage["max_frame_rows"]


def _storage_geometry(cache, frames, pool_bytes, size, compressed, shared,
                      bank_bytes, bank_count):
    initial_ia_bytes = cache * size * size * 2
    total = bank_bytes * bank_count if bank_count is not None else initial_ia_bytes + pool_bytes
    enabled = bool(shared is not False and compressed and size == TILE and
                   SHARED_MIN_BANKS * bank_bytes <= total <= SHARED_MAX_BANKS * bank_bytes and
                   total % bank_bytes == 0)
    max_cache = 4 * bank_bytes // (size * size * 2) if enabled else cache
    max_r = max_cache
    max_frame = max_r * size
    banks = total // bank_bytes - 1 if enabled else 4
    depth = bank_bytes // 16 if enabled else pool_bytes // POOL_ALIGNMENT
    address_bits = max(1, (depth - 1).bit_length()) if compressed else 0
    rotation_bits = max(1, (banks - 1).bit_length()) if compressed else 0
    return dict(shared_ia_ps_enabled=enabled,
                configured_ia_cache_bytes=initial_ia_bytes,
                configured_ps_pool_bytes=pool_bytes if compressed else 0,
                shared_total_bytes=total if enabled else 0,
                shared_bank_bytes=bank_bytes if enabled else 0,
                shared_physical_bank_count=total // bank_bytes if enabled else 0,
                shared_ia_bank_mask=0x16 if enabled else 0,
                default_ia_banks=1 if enabled else 0,
                default_ia_bytes=bank_bytes if enabled else initial_ia_bytes,
                default_ps_pool_bytes=total - bank_bytes if enabled else pool_bytes,
                default_max_r_s8=bank_bytes // (size * size) // 2 if enabled else cache,
                default_max_r_s16=0 if enabled else max(1, cache // 2),
                max_ia_cache_blocks=max_cache,
                max_ia_bytes=4 * bank_bytes if enabled else initial_ia_bytes,
                max_r_s8=max_r, max_r_s16=max(1, max_cache // 2),
                max_frame_rows=max_frame, max_matrix_rows=max_r * size,
                max_stream_rows=max_r * size,
                logical_ps_rows=SHARED_DIRECTORY_ROWS if enabled else
                    max_frame * frames if compressed else (3 * size - 1) * (frames + 1),
                directory_bits_per_row=3 + rotation_bits + 4 * address_bits if compressed else 0,
                payload_bank_depth=depth if compressed else 0,
                payload_metadata_bank_count=banks if compressed else 0)


def memory_geometry(cache, frames, pool_bytes, size=16, compressed=True, *, shared=None,
                    bank_bytes=SHARED_BANK_BYTES, bank_count=None):
    """Physical storage and maximum logical dimensions of the compiled design."""
    geometry(cache, frames, pool_bytes, size, compressed, shared=shared,
             bank_bytes=bank_bytes, bank_count=bank_count)
    return _storage_geometry(cache, frames, pool_bytes, size, compressed, shared,
                             bank_bytes, bank_count)


def buffer_arrays_bits(cache, frames, pool_bytes, size=16, compressed=True, *, shared=None,
                       bank_bytes=SHARED_BANK_BYTES, bank_count=None):
    """Addressable data arrays and their persistent metadata, in logical bits.

    The full interface has 16-bit activation and stationary operands, both S8
    and S16 output queues, and eight vector processing elements at SIZE>=8.
    Shared IA storage reads one 128-bit word for compact S8 and two words from
    separate banks for S16. IA and PS use disjoint allocations of the same
    physical data memory. IA, the DiP array and PS transfer complete rows.
    Pipeline work registers, DMA descriptor queues and compute registers are
    counted by the complete-state elaboration.
    """
    layout = memory_geometry(cache, frames, pool_bytes, size, compressed, shared=shared,
                             bank_bytes=bank_bytes, bank_count=bank_count)
    rmax, max_frame = layout["max_r_s8"], layout["max_frame_rows"]
    slots = 2 * layout["max_ia_cache_blocks"]
    wide_rmax = max(1, cache // 2)
    oa_banks = min(frames * wide_rmax, 32)
    oa_s16_banks = min(oa_banks, 4)
    logical_rows = layout["logical_ps_rows"]
    frame_length_bits = max(1, max_frame.bit_length())
    bits = {
        "ia_cache_tags": slots * (8 * 32 + 16 + 12 + 1),
        "ia_slot_metadata": slots * (size.bit_length() + 2),
        "kernel_cache": 2 * size * size * 16,
        "bias_cache": 2 * rmax * size * 32,
        "requant_is_cache": rmax * size * (32 + 32 + 6 + 6),
        "oa_s8_fifo": oa_banks * size * size * 8,
        "oa_s16_fifo": oa_s16_banks * size * size * 16,
        "conv_data_cache": 128 * 2 * 16 * 8,
        "conv_cache_metadata": 128 * 2 * (28 + 1 + 1 + 13 + 32),
        "conv_prefetch_queue": 8 * (4 * 32 + 1),
        "conv_request_queue": 4 * (5 * 32 + 3),
        "conv_response_queue": 4 * (32 + 1),
        "vector_buffers": size * (5 * 16 + 49 * 8 + 5 * 32),
        "ps_frame_lengths": frames * frame_length_bits,
    }
    if layout["shared_ia_ps_enabled"]:
        bits["ia_ps_shared_ram"] = layout["shared_total_bytes"] * 8
    else:
        bits["ia_cache"] = cache * size * size * 16
        bits["ps_payload"] = pool_bytes * 8 if compressed else logical_rows * size * 32
    if compressed:
        bank_depth = layout["payload_bank_depth"]
        banks = layout["payload_metadata_bank_count"]
        bank_count_bits = bank_depth.bit_length()
        bits.update(ps_directory=logical_rows * layout["directory_bits_per_row"],
                    ps_decoded_fifo=DECODE_FIFO_ROWS * size * 32,
                    ps_decoded_first=DECODE_FIFO_ROWS,
                    ps_frame_valid=frames,
                    ps_frame_max_record_words=frames * 3,
                    ps_free_bitmap=banks * bank_depth,
                    ps_bank_free_count=banks * bank_count_bits,
                    ps_resident_words=banks * frames * frame_length_bits)
    return bits


def register_arrays_bits(cache, frames, pool_bytes, size=16, compressed=True, *, shared=None,
                         bank_bytes=SHARED_BANK_BYTES, bank_count=None):
    """Register groups checked separately within complete sequential state."""
    memory_geometry(cache, frames, pool_bytes, size, compressed, shared=shared,
                    bank_bytes=bank_bytes, bank_count=bank_count)
    bits = {"core_row_metadata": 4 * size + 1}
    return bits


def buffer_ram_bytes(cache, frames, pool_bytes, size=16, compressed=True, *, shared=None,
                     bank_bytes=SHARED_BANK_BYTES, bank_count=None):
    return ceil_div(sum(buffer_arrays_bits(cache, frames, pool_bytes, size, compressed,
                                          shared=shared, bank_bytes=bank_bytes,
                                          bank_count=bank_count).values()), 8)


def allocation(cache, frames, pool_bytes, budget_bytes, scope="buffer-ram", *,
               size=16, compressed=True, measured_state_bits=None, shared=None,
               bank_bytes=SHARED_BANK_BYTES, bank_count=None):
    _integer(budget_bytes, "budget bytes")
    if scope not in SCOPES:
        raise ValueError(f"budget scope must be one of {SCOPES}")
    arrays = buffer_arrays_bits(cache, frames, pool_bytes, size, compressed, shared=shared,
                                bank_bytes=bank_bytes, bank_count=bank_count)
    ram_bits = sum(arrays.values())
    ram_bytes = ceil_div(ram_bits, 8)
    if measured_state_bits is not None:
        _integer(measured_state_bits, "elaborated state bits", ram_bits)
    if scope == "logical-state" and measured_state_bits is None:
        raise ValueError("logical-state budgeting requires a current source-matched RTL elaboration; use --measure-state")
    layout = memory_geometry(cache, frames, pool_bytes, size, compressed, shared=shared,
                             bank_bytes=bank_bytes, bank_count=bank_count)
    rmax = layout["max_r_s8"]
    registers = register_arrays_bits(cache, frames, pool_bytes, size, compressed, shared=shared,
                                     bank_bytes=bank_bytes, bank_count=bank_count)
    used = measured_state_bits / 8 if scope == "logical-state" else ram_bytes
    return dict(ia_cache_blocks=cache, ps_frame_count=frames, size=size,
                compressed_ps=bool(compressed), ps_pool_bytes=pool_bytes if compressed else 0,
                max_r=rmax, max_w=frames, **layout,
                decode_fifo_rows=DECODE_FIFO_ROWS if compressed else 0,
                decode_prefetch_credits=DECODE_PREFETCH_CREDITS if compressed else 0,
                buffer_arrays_bits=arrays, buffer_ram_bits=ram_bits, buffer_ram_bytes=ram_bytes,
                register_arrays_bits=registers, register_array_bits=sum(registers.values()),
                ps_buffer_bits=sum(v for k, v in arrays.items() if k.startswith("ps_")),
                shared_data_ram_bits=arrays.get("ia_ps_shared_ram", 0),
                logical_state_bits=measured_state_bits,
                logical_state_bytes=None if measured_state_bits is None else measured_state_bits / 8,
                other_state_bits=None if measured_state_bits is None else measured_state_bits - ram_bits,
                budget_used_bytes=used, unused_budget_bytes=budget_bytes - used)


def validate_workloads(workloads):
    if not isinstance(workloads, list) or not workloads:
        raise ValueError("workloads must be a nonempty list of {M, K, N} objects")
    result = []
    for task in workloads:
        if not isinstance(task, dict):
            raise ValueError("each workload must contain M, K and N")
        result.append({key: _integer(task.get(key), key, 1, (1 << 20) - 1) for key in ("M", "K", "N")})
    return result


def required_pool_bytes(rows, cols, r, w, mode=0, size=16):
    return payload_bound(size, r, w, cols if mode else rows)


def plan_for_hardware(M, K, N, cache, frames, pool_bytes, representation="adaptive", *,
                      mode=None, requested_r=0, requested_w=0, lhs_bytes=1,
                      per_channel=False, adaptive=None, size=16, compressed=True,
                      lhs_offset=0, rhs_offset=0, shared=None,
                      bank_bytes=SHARED_BANK_BYTES, bank_count=None):
    validate_workloads([dict(M=M, K=K, N=N)])
    layout = memory_geometry(cache, frames, pool_bytes, size, compressed, shared=shared,
                             bank_bytes=bank_bytes, bank_count=bank_count)
    if representation not in REPRESENTATIONS:
        raise ValueError(f"representation must be one of {REPRESENTATIONS}")
    if lhs_bytes not in (1, 2):
        raise ValueError("input elements must contain one or two bytes")
    if adaptive is None:
        adaptive = representation == "adaptive"
    if compressed:
        def exponent(offset, wide=False):
            return 15 if wide else 7 if offset == 0 else 8 if -128 <= offset <= 128 else 15
        product_exp = exponent(lhs_offset, lhs_bytes == 2) + exponent(rhs_offset)
        retained_k = (K - 1) & ~(size - 1)
        literal_bytes = 48 if product_exp < 23 and retained_k < (1 << (23 - product_exp)) else 64
        compact_mask = int(lhs_bytes == 1 and -127 <= lhs_offset <= 128) | \
                       (int(-127 <= rhs_offset <= 128) << 1)
        shared_memory = dict(total_bytes=layout["shared_total_bytes"], bank_bytes=layout["shared_bank_bytes"],
                             ia_bank_mask=layout["shared_ia_bank_mask"], directory_rows=SHARED_DIRECTORY_ROWS) \
                        if layout["shared_ia_ps_enabled"] else None
        dispatch = device_planner.plan(dict(
            rows=M, reduction=K, cols=N, size=size, ia_bytes=cache * size * size * 2,
            frames=frames, pool_bytes=pool_bytes, req_r=requested_r, req_w=requested_w,
            mode=2 if mode is None else mode, is_supported=1, per_channel=int(per_channel),
            lhs_element_bytes=lhs_bytes, compact_mode_mask=compact_mask,
            frame_capable=1, adaptive=int(adaptive and representation == "adaptive"),
            estimated_record_bytes=32 if lhs_bytes == 1 else 64,
            literal_record_bytes=literal_bytes, micro_setup_cycles=64), shared_memory=shared_memory)
    else:
        dispatch = plan_dispatch(M, K, N, size, cache, frames, requested_r, requested_w,
                                 2 if mode is None else mode, True, per_channel, lhs_bytes, 4, 0, False)
    t = dispatch["tiling"]
    return dict(M=M, K=K, N=N, mode=dispatch["is_mode"],
                mode_name="IS" if dispatch["is_mode"] else "WS", R=t["ia_reuse"], W=t["w_reuse"],
                row_groups=t["row_groups"], column_groups=t["col_groups"],
                row_tail_tiles=t["row_tail_tiles"], column_tail_tiles=t["col_tail_tiles"],
                required_pool_bytes=dispatch["payload_bound_bytes"], frame_rows=dispatch["frame_rows"],
                adaptive_active=dispatch["adaptive_active"], raw_safe=dispatch["raw_safe"],
                ideal_operand_read_bytes=dispatch["operand_read_bytes"],
                C_external_bytes=M * N, column_frames=dispatch["frame_count"],
                array_stream_cycles=dispatch["array_stream_cycles"],
                service_estimate=dispatch["service_estimate"], groups=t["row_groups"] * t["col_groups"],
                ps_control=dispatch.get("ps_control", 0),
                slice_rows=dispatch.get("slice_rows", 0),
                micro_commands=dispatch.get("micro_commands", 0),
                predicted_resident_frames=dispatch.get("predicted_resident_frames", 0),
                literal_record_bytes=dispatch.get("literal_record_bytes", 64),
                ia_bank_count=dispatch.get("ia_bank_count", 0),
                ia_bytes=dispatch.get("ia_bytes", cache * size * size * 2),
                ps_pool_bytes=dispatch.get("pool_bytes", pool_bytes),
                raw_safe_is_mode=dispatch.get("raw_safe_is_mode", dispatch["is_mode"]),
                raw_safe_ps_control=dispatch.get("raw_safe_ps_control", 1),
                raw_safe_slice_rows=dispatch.get("raw_safe_slice_rows", 0),
                raw_safe_ia_bank_count=dispatch.get("raw_safe_ia_bank_count", 0),
                raw_safe_ia_bytes=dispatch.get("raw_safe_ia_bytes", cache * size * size * 2),
                raw_safe_pool_bytes=dispatch.get("raw_safe_pool_bytes", pool_bytes))


def max_pool_bytes(cache, frames, budget_bytes, *, scope="buffer-ram", representation="adaptive",
                   measure=None, fixed_only=False, bank_bytes=SHARED_BANK_BYTES, bank_count=None):
    _integer(budget_bytes, "budget bytes")
    if scope not in SCOPES:
        raise ValueError(f"budget scope must be one of {SCOPES}")
    if scope == "logical-state" and measure is None:
        raise ValueError("logical-state search requires a real elaboration callback")
    if bank_count is not None:
        pool = (bank_count - 1) * bank_bytes
        layout = memory_geometry(cache, frames, pool, shared=True,
                                 bank_bytes=bank_bytes, bank_count=bank_count)
        if buffer_ram_bytes(cache, frames, pool, shared=True,
                            bank_bytes=bank_bytes, bank_count=bank_count) > budget_bytes:
            return 0, None
        state = measure(cache, frames, pool, representation, bank_bytes=bank_bytes,
                        bank_count=bank_count) if scope == "logical-state" else None
        return (layout["default_ps_pool_bytes"], state) if state is None or state <= budget_bytes * 8 else (0, None)
    def family_maximum(unit, first, upper, pool_from_unit, *, shared):
        low, high = first - 1, upper
        while low < high:
            candidate = (low + high + 1) // 2
            pool = pool_from_unit(candidate)
            if buffer_ram_bytes(cache, frames, pool, shared=shared, bank_bytes=bank_bytes) <= unit:
                low = candidate
            else:
                high = candidate - 1
        return pool_from_unit(low) if low >= first else 0

    def largest_ram_candidate(ram_budget):
        fixed = family_maximum(ram_budget, 1, min(MAX_POOL_BYTES, ram_budget) // POOL_ALIGNMENT,
                               lambda count: count * POOL_ALIGNMENT, shared=False)
        while fixed and (buffer_ram_bytes(cache, frames, fixed, bank_bytes=bank_bytes) > ram_budget or
                         (fixed_only and memory_geometry(cache, frames, fixed, bank_bytes=bank_bytes)["shared_ia_ps_enabled"])):
            fixed -= POOL_ALIGNMENT
        if fixed_only:
            return fixed
        initial_ia = cache * TILE * TILE * 2
        first_bank_count = max(SHARED_MIN_BANKS, ceil_div(initial_ia + POOL_ALIGNMENT, bank_bytes))
        upper_bank_count = min(SHARED_MAX_BANKS, min(MAX_POOL_BYTES + initial_ia, ram_budget) // bank_bytes)
        shared_pool = family_maximum(ram_budget, first_bank_count, upper_bank_count,
                                     lambda count: count * bank_bytes - initial_ia, shared=True)
        return max(fixed, shared_pool)

    ram_budget = budget_bytes
    while ram_budget > 0:
        pool = largest_ram_candidate(ram_budget)
        if pool < POOL_ALIGNMENT:
            return 0, None
        state = measure(cache, frames, pool, representation) if scope == "logical-state" else None
        if state is None or state <= budget_bytes * 8:
            return pool, state
        ram_budget = buffer_ram_bytes(cache, frames, pool, bank_bytes=bank_bytes) - ceil_div(state - budget_bytes * 8, 8)
    return 0, None


def solve(workloads, budget_bytes, budget_scope="buffer-ram", representation="adaptive", *,
          measure=None, bank_bytes=None):
    tasks = validate_workloads(workloads)
    _integer(budget_bytes, "budget bytes")
    if budget_scope not in SCOPES or representation not in REPRESENTATIONS:
        raise ValueError("unsupported budget scope or PS representation")
    if budget_scope == "logical-state" and measure is None:
        raise ValueError("logical-state search requires a real elaboration callback")
    if bank_bytes is not None and (type(bank_bytes) is not int or bank_bytes not in SHARED_BANK_BYTE_CHOICES):
        raise ValueError(f"shared bank bytes must be one of {SHARED_BANK_BYTE_CHOICES}")
    options = []
    for cache in CACHE_CHOICES:
        for frames in FRAME_CHOICES:
            capacities = []
            if bank_bytes is None:
                pool, state = max_pool_bytes(cache, frames, budget_bytes, scope=budget_scope,
                                             representation=representation, measure=measure, fixed_only=True)
                if pool:
                    capacities.append((pool, state, {}))
            initial_ia = cache * TILE * TILE * 2
            for banks in range(SHARED_MIN_BANKS, SHARED_MAX_BANKS + 1):
                shared_pool = banks * SHARED_BANK_BYTES - initial_ia if bank_bytes is None else (banks - 1) * bank_bytes
                parameters = {} if bank_bytes is None else dict(shared=True, bank_bytes=bank_bytes, bank_count=banks)
                if shared_pool < POOL_ALIGNMENT or buffer_ram_bytes(cache, frames, shared_pool, **parameters) > budget_bytes:
                    continue
                measured = None
                if budget_scope == "logical-state":
                    measured = measure(cache, frames, shared_pool, representation) if bank_bytes is None else \
                        measure(cache, frames, shared_pool, representation, bank_bytes=bank_bytes, bank_count=banks)
                if measured is None or measured <= budget_bytes * 8:
                    capacities.append((shared_pool, measured, parameters))
            for pool, state, parameters in capacities:
                try:
                    plans = [plan_for_hardware(**task, cache=cache, frames=frames, pool_bytes=pool,
                                               representation=representation, **parameters) for task in tasks]
                except ValueError:
                    continue
                alloc = allocation(cache, frames, pool, budget_bytes, budget_scope,
                                   measured_state_bits=state, **parameters)
                key = (math.prod(p["service_estimate"] for p in plans),
                       sum(p["column_frames"] for p in plans), sum(p["groups"] for p in plans),
                       alloc["budget_used_bytes"], cache, frames)
                options.append((key, alloc, plans))
    if not options:
        raise ValueError(f"no shared-array configuration fits {budget_bytes} B ({budget_scope})")
    key, alloc, plans = min(options, key=lambda option: option[0])
    return dict(schema_version=2, model_version=MODEL_VERSION,
                budget=dict(bytes=budget_bytes, scope=budget_scope), representation=representation,
                workloads=tasks, allocation=alloc, plans=plans,
                metrics=dict(gmean_operand_read_bytes=math.exp(sum(math.log(p["ideal_operand_read_bytes"]) for p in plans) / len(plans)),
                             gmean_service_estimate=math.exp(sum(math.log(p["service_estimate"]) for p in plans) / len(plans)),
                             exact_operand_read_product_hex=format(math.prod(p["ideal_operand_read_bytes"] for p in plans), "x"),
                             exact_service_product_hex=format(key[0], "x"), task_count=len(plans),
                             sum_column_frames=key[1], sum_groups=key[2]),
                search=dict(enumerated_geometries=len(CACHE_CHOICES) * len(FRAME_CHOICES),
                            feasible_geometries=len({(item[1]["ia_cache_blocks"], item[1]["ps_frame_count"])
                                                     for item in options}),
                            feasible_configurations=len(options), ia_cache_choices=CACHE_CHOICES,
                            ps_frame_choices=FRAME_CHOICES,
                            shared_bank_byte_choices=(bank_bytes or SHARED_BANK_BYTES,),
                            shared_total_bank_choices=tuple(range(SHARED_MIN_BANKS, SHARED_MAX_BANKS + 1))),
                objective="Minimize the product of device planner service estimates; then matrix frames, groups and allocated bytes.",
                assumptions=[
                    "One shared physical compute array supports INT8 and INT16 operands, WS/IS, bias, per-channel quantization and tails.",
                    "Conv, the vector engine including its three-row image cache, and both output data widths are included in the RAM subtotal.",
                    "Shared builds use configured 1, 2 or 4 KiB physical 128-bit SRAM banks. IA and PS receive disjoint banks per layer, and the data pool is counted once.",
                    "Shared storage has 1024 row directory entries. IA tags, slot metadata, IS bias and requantization buffers cover the largest supported logical IA allocation.",
                    "An explicit shared bank count sets the total data pool independently of the initial IA and PS fields. Fixed builds retain four PS banks with 64-byte capacity increments.",
                    "The decoder has eight 512-bit FIFO rows and seven prefetch credits; history and pipeline registers are included in elaborated state.",
                    "The host search calls drivers/gempact_tiling.h. RAW scheduling uses actual matrix rows and physical pool capacity; a single K tile uses no intermediate PS.",
                    "Expanded reuse uses saved K progress and capacity admission. Changing the active window preserves completed partial sums.",
                    "Operand-read estimates include the device planner's IA slot reuse. Image-cache reuse, AXI splitting and controller waiting require RTL measurement.",
                    "Logical state is measured for every candidate considered under that budget, using matching RTL sources and parameters.",
                    "Logical buffer bits and sequential bits do not include FPGA block rounding or ASIC memory macro granularity."])
