#!/usr/bin/env python3
"""Check full-product Q31 RNE and the optimized INT8 conversion against integers."""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import random
import subprocess

from vendor import digest, stage_vendor

HERE = Path(__file__).resolve().parent
WRAPPER = r'''
#include "backend.h"
#include <vector>
void gemmini_host_command(unsigned, uint64_t, uint64_t) {}
void gemmini_host_fence() {}
extern "C" int32_t requantize32(int32_t value, int32_t multiplier, int shift) {
  return gemmini_requantize_rne(value, multiplier, shift);
}
extern "C" void requantize8(int n, const int32_t *values, const int32_t *multipliers,
                            const int32_t *shifts, int zero, int low, int high,
                            int8_t *output) {
  GemminiLayer p{};
  p.operation = GEMMINI_FULLY_CONNECTED;
  p.batches = p.input_height = p.input_width = p.output_height = p.output_width = 1;
  p.kernel_height = p.kernel_width = p.stride_height = p.stride_width = 1;
  p.output_channels = n;
  p.output_offset = zero;
  p.activation_min = low;
  p.activation_max = high;
  p.per_channel = true;
  p.multipliers = multipliers;
  p.shifts = shifts;
  std::vector<int32_t> sums(n, 0);
  p.weight_sums = sums.data();
  gemmini_requantize_output(p, values, output);
}
'''


def reference(value, multiplier, shift):
    denominator = 1 << (31 - shift)
    quotient, remainder = divmod(value * multiplier, denominator)
    rounded = quotient + int(2 * remainder > denominator or
        (2 * remainder == denominator and quotient & 1))
    return min(2**31 - 1, max(-2**31, rounded))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--software', type=Path, required=True)
    parser.add_argument('--params', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    vendor = stage_vendor(args.out / 'vendor', args.software, args.params)
    wrapper = args.out / 'quantization_wrapper.cc'
    wrapper.write_text(WRAPPER)
    library = args.out / 'quantization.so'
    command = ['g++', '-std=gnu++17', '-O2', '-fwrapv', '-shared', '-fPIC',
        '-DGEMMINI_HOST_COMMANDS', '-I' + str(HERE), '-I' + str(args.out / 'vendor'),
        str(HERE / 'backend.cc'), str(wrapper), '-o', str(library)]
    process = subprocess.run(command, text=True, capture_output=True)
    (args.out / 'build.log').write_text(process.stdout + process.stderr)
    if process.returncode:
        raise RuntimeError(process.stderr)
    loaded = ctypes.CDLL(str(library.resolve()))
    loaded.requantize32.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int]
    loaded.requantize32.restype = ctypes.c_int32
    pointer = ctypes.POINTER(ctypes.c_int32)
    loaded.requantize8.argtypes = [ctypes.c_int, pointer, pointer, pointer,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int8)]
    randomizer = random.Random(0x47454d4d)
    samples = []
    corners = [-2**31, -2**31 + 1, -65537, -129, -128, -127, -3, -2, -1,
               0, 1, 2, 3, 126, 127, 128, 65535, 2**31 - 2, 2**31 - 1]
    for shift in range(-31, 31):
        for multiplier in (-2**31, -1, 0, 1, 2**29, 2**30, 2**30 + 1, 2**31 - 1):
            samples += [(value, multiplier, shift) for value in corners]
        samples += [(randomizer.randrange(-2**31, 2**31),
                     randomizer.randrange(0, 2**31), shift) for _ in range(1000)]
        for target in range(-130, 131):
            multiplier = randomizer.randrange(2**29, 2**31)
            center = (target * (1 << (31 - shift))) // multiplier
            samples += [(value, multiplier, shift) for value in range(center - 2, center + 3)
                        if -2**31 <= value < 2**31]
    expected = [reference(*sample) for sample in samples]
    for sample, wanted in zip(samples, expected):
        actual = loaded.requantize32(*sample)
        if actual != wanted:
            raise AssertionError((sample, actual, wanted))
    count = len(samples)
    array = ctypes.c_int32 * count
    values = array(*(sample[0] for sample in samples))
    multipliers = array(*(sample[1] for sample in samples))
    shifts = array(*(sample[2] for sample in samples))
    output = (ctypes.c_int8 * count)()
    profiles = [(-128, -128, 127), (0, -128, 127), (127, -128, 127),
                (-83, -83, 127), (21, 21, 105)]
    for zero, low, high in profiles:
        loaded.requantize8(count, values, multipliers, shifts, zero, low, high, output)
        wanted = [max(low, min(high, value + zero)) for value in expected]
        for index, (actual, correct) in enumerate(zip(output, wanted)):
            if actual != correct:
                raise AssertionError((profiles, index, samples[index], actual, correct))
    report = dict(passed=True, signed_accumulator_cases=count, int8_cases=count * len(profiles),
        shift_range=[-31,30], rounding='nearest_even, full signed 64-bit product',
        output_profiles=profiles, vendor=vendor, compiler_command=command,
        backend_sha256=digest(HERE / 'backend.cc'), library_sha256=digest(library))
    (args.out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key:report[key] for key in ('passed','signed_accumulator_cases','int8_cases')}))


if __name__ == '__main__':
    main()
