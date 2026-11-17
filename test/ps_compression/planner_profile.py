"""Hardware and planner inputs for reproducible shared-memory measurements."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def integer(value, name, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"Invalid {name}: {value!r}")
    return value


def normalize_profile(manifest, *, root, literal_bound=False, ram_fixed_lat=0):
    """Use build metadata, with source-verified Conv memory timing defaults.

    First-response latency and continuous beat spacing are separate physical
    properties. Request cost remains the production driver's effective
    service estimate; it can differ from latency when reads overlap.
    """
    root = Path(root)
    soc = "profile" in manifest
    source = manifest["profile"] if soc else manifest
    timing_sources = {}
    if soc:
        read_beat = source["ram_continuous_read_beat_cycles"]
        first_latency = source["ram_read_first_latency"]
        timing_sources.update(read_beat="build.profile.ram_continuous_read_beat_cycles",
                              first_response="build.profile.ram_read_first_latency")
    else:
        read_beat = source.get("ram_continuous_read_beat_cycles")
        first_latency = source.get("ram_read_first_latency")
        timing_sources.update(read_beat="build.ram_continuous_read_beat_cycles",
                              first_response="build.ram_read_first_latency")
        if read_beat is None or first_latency is None:
            memory = root / "test/conv_npu/axi_memory.sv"
            text = memory.read_text()
            digest = hashlib.sha256(memory.read_bytes()).hexdigest()
            recorded = manifest.get("source_sha256", {}).get("test/conv_npu/axi_memory.sv")
            if recorded is not None and recorded != digest:
                raise ValueError("Conv memory source differs from its recorded build")
            def default(name):
                match = re.search(r"parameter\s+int\s+" + name + r"\s*=\s*(\d+)\s*[,\n]", text)
                if match is None:
                    raise ValueError(f"Unable to read the Conv memory parameter {name}")
                return int(match[1])
            if read_beat is None:
                read_beat = default("READ_BEAT_CYCLES")
                timing_sources["read_beat"] = "conv_test_axi_memory.READ_BEAT_CYCLES"
            if first_latency is None:
                first_latency = default("READ_FIRST_LATENCY")
                timing_sources["first_response"] = "conv_test_axi_memory.READ_FIRST_LATENCY"
            timing_sources.update(source="test/conv_npu/axi_memory.sv", source_sha256=digest)
    width = integer(source["bus_width"], "bus_width")
    if width not in (32, 64):
        raise ValueError("The NPU AXI data width must be 32 or 64")
    size = integer(source.get("size", 16), "size")
    if size != 16 or not source.get("ps_compress", False):
        raise ValueError("The shared PS measurement requires a 16 by 16 compressed-capable array")
    frames = integer(source.get("ps_frame_count", 16), "ps_frame_count", 1, 64)
    cache = integer(source.get("ia_cache_blocks", 4), "ia_cache_blocks", 2, 64)
    bank_bytes = integer(source["shared_bank_bytes"], "shared_bank_bytes")
    if bank_bytes not in (1024, 2048, 4096):
        raise ValueError("Shared banks must contain 1024, 2048 or 4096 bytes")
    bank_count = integer(source.get("shared_bank_count", 0), "shared_bank_count")
    if not bank_count:
        total = source.get("shared_total_bytes")
        if total is None:
            total = cache * 512 + integer(source["pool_bytes"], "pool_bytes")
        total = integer(total, "shared_total_bytes")
        if total % bank_bytes:
            raise ValueError("Shared capacity must contain complete banks")
        bank_count = total // bank_bytes
    integer(bank_count, "shared_bank_count", 6, 9)
    total = bank_count * bank_bytes
    if source.get("shared_total_bytes", total) != total:
        raise ValueError("Shared total and bank geometry disagree")
    max_dma = integer(source.get("dma_max_bytes", 256 * (width // 8)), "dma_max_bytes", width // 8)
    if max_dma > 256 * (width // 8) or max_dma & (max_dma - 1):
        raise ValueError("DMA maximum must be a power of two within 256 physical beats")
    choices = source.get("shared_ia_bank_choices", [1, 2, 4])
    if not choices or any(type(value) is not int or value not in (1, 2, 4) for value in choices):
        raise ValueError("Invalid shared IA bank choices")
    directory = integer(source.get("ps_directory_rows", 1024), "ps_directory_rows", 1)
    raw_only = bool(source.get("force_raw", source.get("ps_force_raw", False)))
    output_s8 = min(frames * max(1, cache // 2), 32)
    output_limit = integer(source.get("output_banks_s16_max", 4), "output_banks_s16_max")
    output_s16 = min(output_s8, output_limit) if output_limit else output_s8
    caps = (1 << 24) | (frames << 16) | 0x17 | (int(raw_only) << 3) | (int(literal_bound) << 5)
    costs = dict(read_beat_cycles=integer(read_beat, "continuous read beat spacing", 1),
                 write_beat_cycles=integer(source.get("schedule_write_beat_cycles", 1), "write beat cost", 1),
                 read_request_cycles=integer(source.get("schedule_read_request_cycles", 1), "read request cost"),
                 write_request_cycles=integer(source.get("schedule_write_request_cycles", 3), "write request cost"),
                 ia_tile_setup_cycles=integer(source.get("schedule_ia_tile_setup_cycles", 2), "IA tile setup cost"),
                 quant_group_setup_cycles=integer(source.get("schedule_quant_group_setup_cycles", 2), "quantization group setup cost"))
    return dict(source_kind="soc" if soc else "conv", size=size, ia_cache_blocks=cache,
        ps_frame_count=frames, bus_width=width, dma_max_bytes=max_dma,
        shared_bank_bytes=bank_bytes, shared_bank_count=bank_count,
        shared_total_bytes=total, shared_ia_bank_mask=sum(1 << value for value in set(choices)),
        ia_cache_bytes=bank_bytes, ps_pool_bytes=total-bank_bytes, ps_directory_rows=directory,
        ps_caps=caps, literal_bound_capability=bool(literal_bound), raw_only=raw_only,
        matrix_ps_rows=integer(source.get("ps_storage_rows", 799), "matrix_ps_rows"),
        matrix_output_banks=output_s8 | (output_s16 << 16),
        ps_directory_bits_per_row=3 + (bank_count-2).bit_length() + 4 * (bank_bytes//16-1).bit_length(),
        memory_timing=dict(ram_read_first_latency=integer(first_latency, "first response latency", 1),
            ram_continuous_read_beat_cycles=read_beat,
            ram_fixed_lat=integer(ram_fixed_lat, "RAM fixed delay", 0, 255), sources=timing_sources),
        planner_costs=costs)


def profile_header(profile):
    values = {"DENSE_SWEEP_" + name.upper(): profile[name] for name in (
        "size", "ia_cache_blocks", "ps_frame_count", "bus_width", "dma_max_bytes", "ps_caps",
        "matrix_ps_rows", "matrix_output_banks", "ia_cache_bytes", "ps_pool_bytes",
        "shared_bank_bytes", "shared_bank_count", "shared_total_bytes", "shared_ia_bank_mask", "ps_directory_rows")}
    values.update({"DSA_SCHEDULE_" + key.upper(): value for key, value in profile["planner_costs"].items()})
    values["DSA_SCHEDULE_AXI_DATA_BITS"] = profile["bus_width"]
    values["DENSE_SWEEP_RAM_READ_FIRST_LATENCY"] = profile["memory_timing"]["ram_read_first_latency"]
    values["DENSE_SWEEP_RAM_FIXED_LAT"] = profile["memory_timing"]["ram_fixed_lat"]
    return "/* Measurement settings from the selected simulator build. */\n" + "".join(
        f"#define {key} {value}u\n" for key, value in sorted(values.items()))


def profile_signature(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def capability_expectations(profile):
    """Read-only MMIO checks executed before the measurement configuration."""
    values = {0x0e4: (profile["size"] << 24) | (profile["ps_frame_count"] << 16) |
                       (profile["ia_cache_blocks"] << 8) | 7,
              0x0e8: profile["matrix_ps_rows"], 0x0ec: profile["matrix_output_banks"],
              0x0f0: profile["dma_max_bytes"], 0x0f4: profile["bus_width"],
              0x100: profile["shared_total_bytes"], 0x104: profile["shared_bank_bytes"],
              0x10c: profile["shared_ia_bank_mask"], 0x110: profile["ps_directory_rows"],
              0x124: profile["ps_caps"], 0x134: profile["ps_pool_bytes"],
              0x138: profile["ia_cache_bytes"]}
    return [(address, value, 0xffffffff if address != 0x124 or profile["literal_bound_capability"]
             else 0xffffffdf) for address, value in values.items()]
