"""Use the production C device planner for host capacity searches."""
from __future__ import annotations

import ctypes
import functools
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name("planner_bridge.c")
HEADER = ROOT / "drivers/gempact_tiling.h"
REQUEST_FIELDS = (
    "rows", "reduction", "cols", "size", "ia_bytes", "frames", "pool_bytes",
    "req_r", "req_w", "mode", "is_supported", "per_channel", "lhs_element_bytes",
    "compact_mode_mask", "frame_capable", "adaptive", "estimated_record_bytes",
    "literal_record_bytes", "micro_setup_cycles",
    "im2col_source_bytes", "im2col_pixel_channels", "im2col_stage_bytes_per_position",
    "im2col_base_fraction_q8", "im2col_cache_bytes", "directory_rows", "ia_bank_count", "ps_bank_count",
)
TILING_FIELDS = ("ia_reuse", "w_reuse", "row_groups", "row_tail_tiles", "col_groups", "col_tail_tiles")
RESULT_FIELDS = (
    "is_mode", "frame_rows", "adaptive_active", "reduction", "lhs_element_bytes",
    "bus_bytes", "payload_bound_bytes", "lhs_read_rounds", "rhs_read_rounds",
    "operand_read_bytes", "frame_count", "array_stream_cycles", "service_estimate",
    "ps_control", "ia_slots", "slice_rows", "predicted_resident_frames",
    "estimated_record_bytes", "literal_record_bytes", "candidates_evaluated",
    "micro_commands", "weight_shift_rows",
    "ia_bank_count", "ia_bytes", "pool_bytes", "raw_safe_is_mode", "raw_safe_ps_control",
    "raw_safe_slice_rows", "raw_safe_ia_bank_count", "raw_safe_ia_bytes", "raw_safe_pool_bytes",
)


@functools.lru_cache(maxsize=4)
def _library(source_digest, compiler):
    directory = ROOT / "build/capacity/planner" / source_digest
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / "planner.so"
    if not library.exists():
        temporary = directory / f"planner-{os.getpid()}.so"
        command = [compiler, "-std=c11", "-O2", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                   "-I", str(HEADER.parent), str(SOURCE), "-o", str(temporary)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode:
            temporary.unlink(missing_ok=True)
            raise ValueError("Cannot compile the production capacity planner: " + result.stderr)
        after = hashlib.sha256(SOURCE.read_bytes() + HEADER.read_bytes() + compiler.encode()).hexdigest()
        if after != source_digest:
            temporary.unlink(missing_ok=True)
            raise ValueError("Planner source changed during compilation; run the capacity command again")
        temporary.replace(library)
    value = ctypes.CDLL(str(library))
    value.capacity_plan_device.argtypes = (ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint64))
    value.capacity_plan_device.restype = ctypes.c_int
    return value


SHARED_FIELDS = ("total_bytes", "bank_bytes", "ia_bank_mask", "directory_rows")
GEOMETRY_FIELDS = ("input_bytes", "input_channels", "group_channels", "kernel_h", "kernel_w",
                   "stride_w", "source_bytes", "cache_bytes")


def plan(request, shared_memory=None, im2col_geometry=None):
    compiler = shutil.which(os.environ.get("CC", "cc"))
    if compiler is None:
        raise ValueError("A host C compiler is required for device capacity planning")
    values = [request[name] if index < 19 else request.get(name, 0)
              for index, name in enumerate(REQUEST_FIELDS)]
    values += [shared_memory[name] if shared_memory else 0 for name in SHARED_FIELDS]
    values += [im2col_geometry[name] if im2col_geometry else 0 for name in GEOMETRY_FIELDS]
    if any(type(v) is not int or v < 0 or v > 0xffffffff for v in values):
        raise ValueError("Device planner fields must be unsigned 32-bit integers")
    source_digest = hashlib.sha256(SOURCE.read_bytes() + HEADER.read_bytes() + compiler.encode()).hexdigest()
    arguments = (ctypes.c_uint32 * len(values))(*values)
    output = (ctypes.c_uint64 * (12 + len(RESULT_FIELDS)))()
    if not _library(source_digest, compiler).capacity_plan_device(arguments, output):
        raise ValueError("No supported tiling fits the device configuration")
    result = dict(zip(RESULT_FIELDS, output[12:]))
    result["tiling"] = dict(zip(TILING_FIELDS, output[:6]))
    result["raw_safe"] = dict(zip(TILING_FIELDS, output[6:12]))
    return result
