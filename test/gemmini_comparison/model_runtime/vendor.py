#!/usr/bin/env python3
"""Stage the fixed DWConv scheduler with a Pico/host RoCC transport."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stage_vendor(destination, software, params, conv_policy=0):
    destination, software, params = map(Path, (destination, software, params))
    (destination / 'include').mkdir(parents=True, exist_ok=True)
    (destination / 'rocc-software/src').mkdir(parents=True, exist_ok=True)
    source = software / 'include/gemmini.h'
    original = source.read_text()
    fence = '#define gemmini_fence() asm volatile("fence")'
    if original.count(fence) != 1:
        raise ValueError('The fixed scheduler must have one fence definition')
    adapted = original.replace(fence, '#define gemmini_fence() gemmini_mmio_fence()')
    (destination / 'include/gemmini.h').write_text(adapted)
    shutil.copyfile(software / 'include/gemmini_counter.h', destination / 'include/gemmini_counter.h')
    shutil.copyfile(params, destination / 'include/gemmini_params.h')
    (destination / 'rocc-software/src/xcustom.h').write_text('#include "mmio.h"\n')
    if conv_policy not in (0, 1, 2):
        raise ValueError('Convolution policy must be auto, native or im2col')
    config = destination / 'include/gemmini_model_config.h'
    config.write_text('#ifndef GEMMINI_CONV_POLICY\n#define GEMMINI_CONV_POLICY ' +
                      str(conv_policy) + '\n#endif\n')
    return {
        'software_path': str(software.resolve()),
        'scheduler_sha256': digest(source),
        'adapted_scheduler_sha256': digest(destination / 'include/gemmini.h'),
        'params_path': str(params.resolve()),
        'params_sha256': digest(params),
        'transport_sha256': digest(HERE / 'mmio.h'),
        'model_config_sha256': digest(config),
        'convolution_policy': ('auto', 'native', 'im2col')[conv_policy],
        'scheduler_adaptation': 'Fence completion uses the MMIO bridge; RoCC operands retain their original 64-bit fields.',
    }
