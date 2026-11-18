"""Physical input-cache capacity and convolution working-set guidance."""
from __future__ import annotations

import math


DEFAULT_BYTES = 4096
BYTE_CHOICES = tuple(512 << index for index in range(8))
WAYS = 2
LINE_BYTES = 16
METADATA_BITS_PER_LINE = 7 * 28 + 2 * 13 + 3 * 32 + 1 + 2 + 1


def validate_bytes(value):
    if type(value) is not int or value not in BYTE_CHOICES:
        raise ValueError("IM2COL_CACHE_BYTES must be a power of two in 512..65536")
    return value


def geometry(cache_bytes=DEFAULT_BYTES):
    data_bytes = validate_bytes(cache_bytes)
    lines = data_bytes // LINE_BYTES
    metadata_bits = lines * METADATA_BITS_PER_LINE
    return dict(data_bytes=data_bytes, sets=lines // WAYS, ways=WAYS,
                line_bytes=LINE_BYTES, lines=lines,
                metadata_bits_per_line=METADATA_BITS_PER_LINE,
                metadata_bits=metadata_bits, metadata_bytes=metadata_bits // 8,
                data_and_metadata_bytes=data_bytes + metadata_bits // 8)


def _positive(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(name + " must be a positive integer")
    return value


def analyze_convolution(cache_bytes, *, input_h, input_w, input_channels,
                        kernel_h, kernel_w, element_bytes=1,
                        dilation_h=1, dilation_w=1, input_base_mod16=0):
    """Describe one output row's conservative full-width band in ungrouped NHWC.

    The channel group starts at zero. K16 channel fragments start on 16-byte lines.
    The band includes gaps introduced by dilation and every input column.
    Capacity therefore describes a spatial working set, without predicting
    the selected R/W schedule, prefetch traffic, misses or execution cycles.
    """
    hardware = geometry(cache_bytes)
    for name, value in (("input_h", input_h), ("input_w", input_w),
                        ("input_channels", input_channels), ("kernel_h", kernel_h),
                        ("kernel_w", kernel_w), ("dilation_h", dilation_h),
                        ("dilation_w", dilation_w)):
        _positive(value, name)
    if type(element_bytes) is not int or element_bytes not in (1, 2):
        raise ValueError("element_bytes must be 1 or 2")
    if type(input_base_mod16) is not int or input_base_mod16 not in range(16):
        raise ValueError("input_base_mod16 must be in 0..15")
    pixel_bytes = input_channels * element_bytes
    spatial = input_base_mod16 == 0 and (
        pixel_bytes >= LINE_BYTES and pixel_bytes % LINE_BYTES == 0 or
        pixel_bytes < LINE_BYTES and pixel_bytes & (pixel_bytes - 1) == 0)
    effective_h = 1 + (kernel_h - 1) * dilation_h
    effective_w = 1 + (kernel_w - 1) * dilation_w
    band_pixels = min(input_h, effective_h) * input_w
    tensor_bytes = input_h * input_w * pixel_bytes
    tensor_lines = (input_base_mod16 + tensor_bytes + LINE_BYTES - 1) // LINE_BYTES
    result = dict(input_h=input_h, input_w=input_w, input_channels=input_channels,
                  kernel_h=kernel_h, kernel_w=kernel_w, element_bytes=element_bytes,
                  dilation_h=dilation_h, dilation_w=dilation_w,
                  effective_kernel_h=effective_h, effective_kernel_w=effective_w,
                  input_tensor_bytes=tensor_bytes,
                  whole_tensor_data_capacity_fits=tensor_lines <= hardware["lines"],
                  spatial_index_eligible=spatial,
                  band_rows=min(input_h, effective_h), band_pixels=band_pixels,
                  band_scope="One output row, full input width, one K16 channel fragment")
    if not spatial:
        result.update(band_cache_bytes=None, band_peak_lines_per_set=None,
                      band_fits=None, recommended_cache_bytes=None,
                      detail="Physical-line XOR indexing applies; use the RTL workload test for set conflicts.")
        return result
    if pixel_bytes >= LINE_BYTES:
        lines_per_pixel = (min(input_channels, 16) * element_bytes + LINE_BYTES - 1) // LINE_BYTES
        band_lines = band_pixels * lines_per_pixel
        peak = ((band_pixels + hardware["sets"] - 1) // hardware["sets"]) * lines_per_pixel
        sets_needed = (band_pixels + WAYS // lines_per_pixel - 1) // (WAYS // lines_per_pixel)
        detail = "Spatial index is pixel position modulo sets; channel fragments share the two ways."
    else:
        # Complete input rows can start at any reachable 16-byte line offset.
        maximum_row_offset = LINE_BYTES - math.gcd(input_w * pixel_bytes, LINE_BYTES)
        band_lines = (band_pixels * pixel_bytes + maximum_row_offset + LINE_BYTES - 1) // LINE_BYTES
        lines_per_pixel = None
        peak = (band_lines + hardware["sets"] - 1) // hardware["sets"]
        sets_needed = (band_lines + WAYS - 1) // WAYS
        detail = "Each cache line contains several complete pixels; the band includes row-start alignment."
    needed = WAYS * LINE_BYTES * (1 << max(0, (sets_needed - 1).bit_length()))
    recommended = next((value for value in BYTE_CHOICES if value >= needed), None)
    result.update(fragment_lines_per_pixel=lines_per_pixel,
                  band_cache_bytes=band_lines * LINE_BYTES,
                  band_peak_lines_per_set=peak, band_fits=peak <= WAYS,
                  minimum_band_cache_bytes=needed,
                  recommended_cache_bytes=recommended,
                  next_s8_fragment_spatial_condition=(pixel_bytes >= LINE_BYTES and
                      input_h * input_w <= hardware["sets"] and element_bytes == 1 and
                      input_channels >= 32), detail=detail)
    return result


def guidance(cache_bytes=DEFAULT_BYTES):
    hardware = geometry(cache_bytes)
    sets = hardware["sets"]
    widths = [dict(kernel=kernel,
                   effective_kernel_h=kernel,
                   s8_k16_max_input_width=WAYS * sets // kernel,
                   s16_k16_max_input_width=sets // kernel)
              for kernel in (3, 5, 7)]
    return dict(
        scope="Aligned NHWC input; one full-width input band for one K16 channel fragment",
        requirements="Ungrouped NHWC; 16-byte-aligned input base and channel fragments; channels a multiple of 16; dilation 1",
        band_width_limits=widths,
        next_s8_fragment_max_spatial_pixels=sets,
        whole_tensor_capacity_condition="input_h * input_w * input_channels * element_bytes <= data_bytes; check set occupancy separately",
        dilation_condition="Replace kernel height by 1 + (kernel_h - 1) * dilation_h for the conservative band",
        scheduling_condition="R/W windows, padding, stride and prefetch affect traffic; capacity guidance does not predict cycles",
        fallback_index_condition="Other channel strides or input alignments use physical-line XOR indexing",
        examples=[analyze_convolution(cache_bytes, input_h=64, input_w=width,
                   input_channels=16, kernel_h=3, kernel_w=3, element_bytes=element)
                  for width, element in ((32, 1), (64, 1), (32, 2), (64, 2))])


def help_text(cache_bytes=DEFAULT_BYTES):
    hardware = geometry(cache_bytes)
    limits = guidance(cache_bytes)["band_width_limits"]
    lines = [f"Selected input cache: {hardware['data_bytes']} B, {hardware['sets']} sets, "
             "two ways and 16 B per line.",
             f"Tags and lifetime state add {hardware['metadata_bytes']} B; queues are counted separately.",
             "", "One K16 channel fragment across the full input width:",
             "Kernel       Maximum width, S8 / S16"]
    for row in limits:
        lines.append(f"{row['kernel']}x{row['kernel']}          "
                     f"{row['s8_k16_max_input_width']} / {row['s16_k16_max_input_width']}")
    lines += ["", "These band limits assume ungrouped NHWC, a 16-byte-aligned input and channel fragments, channels divisible by 16, "
              "and dilation 1. They describe the current channel fragment. Full input storage also "
              "depends on height and all channels. R/W, stride and prefetch determine actual reuse.",
              "For dilation, use effective kernel height 1 + (kernel_h - 1) * dilation_h. "
              "Other alignments and channel strides use physical-line XOR indexing.",
              "See docs/im2col_cache_configuration.md for examples and test commands."]
    return "\n".join(lines)
