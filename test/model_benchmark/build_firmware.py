#!/usr/bin/env python3
"""Build a software or hardware TFLM/NMSIS RV32 firmware.

Models and inputs are loaded separately. A trace firmware observes each operator
through the existing MicroProfilerInterface; timing uses the ordinary firmware.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TFLM = ROOT / 'drivers/tflm/tflm/tflite-micro'
NN = ROOT / 'drivers/tflm/NMSIS/NN'
SOC = ROOT / 'veri/soc_csrc'
RAM_BYTES = 2 * 1024 * 1024


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2) + '\n')


def run(command, log):
    command = [str(x) for x in command]
    with Path(log).open('w') as stream:
        stream.write('COMMAND: ' + shlex.join(command) + '\n')
        stream.flush()
        p = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    if p.returncode:
        raise RuntimeError(f'{log}\n{Path(log).read_text()[-7000:]}')


def abi_fields(name):
    text = (HERE / 'full_network_abi.h').read_text()
    match = re.search(r'#define FULL_NETWORK_' + name + r'_FIELDS\(X\)(.*?)(?=\n\n)', text, re.S)
    if not match:
        raise ValueError('missing ABI field macro: ' + name)
    return re.findall(r'X\((\w+)\)', match.group(1))


def compiler_sibling(gcc, suffix):
    path = str(Path(shutil.which(str(gcc)) or gcc).resolve())
    if not path.endswith('gcc'):
        raise ValueError('--gcc must name an executable ending in gcc')
    return path[:-3] + suffix


def sources():
    micro = TFLM / 'tensorflow/lite/micro'
    result = []
    for sub in ('', 'arena_allocator', 'memory_planner', 'tflite_bridge'):
        result += [p for p in (micro / sub).glob('*.cc')
                   if not any(word in p.stem for word in ('test', 'benchmark', 'fake_', 'mock_'))]
    result += [p for p in (TFLM / 'tensorflow').rglob('*') if p.suffix in ('.c', '.cc')
               and '/micro/' not in str(p) and '/experimental/' not in str(p)
               and not any(word in p.stem for word in ('test', 'benchmark'))]
    kernels = ['kernel_util.cc', 'micro_tensor_utils.cc', 'conv_common.cc',
               'fully_connected_common.cc', 'depthwise_conv_common.cc', 'pooling_common.cc',
               'reshape.cc', 'reshape_common.cc', 'softmax.cc', 'softmax_common.cc',
               'add.cc', 'add_common.cc']
    kernels += ['nmsis_nn/conv.cc', 'nmsis_nn/depthwise_conv.cc',
                'nmsis_nn/fully_connected.cc', 'nmsis_nn/pooling.cc']
    result += [micro / 'kernels' / name for name in kernels]
    result += list((NN / 'Source').glob('*/*.c'))
    return sorted(set(result))


def dependency_files(path):
    text = Path(path).read_text().replace('\\\n', ' ')
    return [Path(p).resolve() for p in shlex.split(text.split(':', 1)[1])]


def build_firmware(out, gcc, *, hardware=True, trace=False, runtime_root=None,
                   jobs=1, object_cache=None, arena_bytes=256*1024):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(object_cache or out.parent/'firmware_objects').resolve()
    cache.mkdir(parents=True, exist_ok=True)
    gcc = str(Path(shutil.which(str(gcc)) or gcc).resolve())
    gxx, ar, nm, objcopy, readelf = [compiler_sibling(gcc, n) for n in
                                   ('g++', 'ar', 'nm', 'objcopy', 'readelf')]
    common = ['-O3', '-g0', '-march=rv32im_zicsr', '-mabi=ilp32',
              '-ffreestanding', '-fno-builtin', '-ffunction-sections', '-fdata-sections',
              '-fno-unwind-tables', '-DNDEBUG', '-DTF_LITE_STRIP_ERROR_STRINGS',
              '-DTF_LITE_DISABLE_X86_NEON', '-DDSA_TILE_SIZE=16',
              '-DDSA_IA_CACHE_BLOCKS=4', '-DDSA_PS_FRAME_COUNT=16',
              '-DDSA_PCR_ENGINE=0', '-DDSA_PS_POOL_BYTES=0',
              '-Wall', '-Wextra', '-Wno-unused-parameter']
    common += ['-DNMSIS_NN', '-DDSA_NN_RUNTIME_CONTROL=1',
               f'-DDSA_NN_CONV_ENABLE={int(hardware)}', f'-DDSA_NN_VECTOR_ENABLE={int(hardware)}',
               f'-DDSA_NN_FC_ENABLE={int(hardware)}']
    downloads = TFLM/'tensorflow/lite/micro/tools/make/downloads'
    # The NMSIS and standalone drivers intentionally have different headers
    # with the same basename. Select the NMSIS header for NMSIS source builds.
    include_dirs = [HERE, NN/'Include', NN.parent/'Core/Include', ROOT/'drivers',
                    TFLM, downloads, downloads/'flatbuffers/include',
                    downloads/'gemmlowp', downloads/'ruy', downloads/'kissfft']
    common += [f'-I{p}' for p in include_dirs]
    cxx = ['-std=c++17', '-fno-rtti', '-fno-exceptions', '-fno-threadsafe-statics']
    runtime_libs = []
    if runtime_root:
        runtime_root = Path(runtime_root).resolve()
        target = runtime_root/'riscv64-unknown-elf'
        common += ['-isystem', str(target/'include')]
        versions = sorted((runtime_root/'include/c++').glob('*'))
        if len(versions) != 1:
            raise ValueError('runtime-root requires one configured C++ header version')
        cxx += ['-isystem', str(versions[0]), '-isystem', str(versions[0]/'riscv64-unknown-elf'),
                '-isystem', str(versions[0]/'backward')]
        multilib = subprocess.check_output(
            [gcc, '-march=rv32im_zicsr', '-mabi=ilp32', '-print-multi-directory'], text=True).strip()
        cxx_library = runtime_root/'lib'/multilib/'libstdc++.a'
        if not cxx_library.is_file():
            cxx_library = runtime_root/'lib/libstdc++.a'
        runtime_libs = [cxx_library, target/'lib/libm.a', target/'lib/libc.a']
    else:
        for lib in ('libstdc++.a', 'libm.a', 'libc.a'):
            path = Path(subprocess.check_output([gcc, '-march=rv32im_zicsr', '-mabi=ilp32',
                                                '-print-file-name='+lib], text=True).strip())
            if not path.is_file():
                raise ValueError(f'complete RV32 bare-metal C/C++ runtime is required: missing {lib}')
            runtime_libs.append(path)
    libgcc = Path(subprocess.check_output([gcc, '-march=rv32im_zicsr', '-mabi=ilp32',
                                         '-print-libgcc-file-name'], text=True).strip())
    runtime_libs += [libgcc]
    for path in runtime_libs:
        if not path.is_file():
            raise ValueError('missing runtime library: ' + str(path))

    source_files = sources()
    app_sources = [SOC/'start.S', HERE/'runtime.cc', HERE/'firmware.cc']
    all_sources = source_files + app_sources
    before = {str(p.relative_to(ROOT)): digest(p) for p in all_sources}
    before.update({str(p.relative_to(ROOT)): digest(p) for p in
                   [Path(__file__), HERE/'full_network_abi.h', SOC/'link.ld']})

    def compile_one(source):
        flags = common.copy()
        if source.suffix == '.cc':
            # TFLM/FlatBuffers use the standard library's hosted interfaces.
            # The supplied newlib/C++ runtime implements them on bare metal;
            # GCC 14 correctly rejects <string>/<vector> with -ffreestanding.
            flags.remove('-ffreestanding')
            flags += cxx
            if runtime_root:
                # libstdc++'s C wrapper headers use #include_next, so the
                # newlib C include directory must follow all C++ directories.
                index = flags.index(str(target/'include'))
                del flags[index-1:index+1]
                flags += ['-isystem', str(target/'include')]
        elif source.suffix == '.c':
            flags += ['-std=c11']
        if source == HERE/'firmware.cc':
            flags += [f'-DFULL_NETWORK_TRACE_ENABLED={int(trace)}',
                      f'-DFULL_NETWORK_ARENA_BYTES={arena_bytes}']
        if trace and source in [TFLM/'tensorflow/lite/micro'/name for name in
                                ('micro_interpreter_graph.cc','micro_log.cc','debug_log.cc')]:
            flags.remove('-DTF_LITE_STRIP_ERROR_STRINGS')
        compiler = gxx if source.suffix == '.cc' else gcc
        key = hashlib.sha256(json.dumps([str(source), digest(source), compiler, digest(compiler), flags]).encode()).hexdigest()[:24]
        dest = cache/key
        dest.mkdir(exist_ok=True)
        obj = dest / f'{source.stem}_{key}.o'
        dep, meta, log = [dest/n for n in ('source.d', 'compile.json', 'compile.log')]
        reused = False
        if obj.exists() and meta.exists():
            old = json.loads(meta.read_text())
            reused = (digest(obj) == old['object_sha256'] and
                      all(Path(p).is_file() and digest(p) == h for p,h in old['dependencies'].items()))
        command = [compiler, *flags, '-MD', '-MF', dep, '-c', source, '-o', obj]
        if not reused:
            run(command, log)
            dependencies = {str(p):digest(p) for p in dependency_files(dep)}
            write_json(meta, {'command':[str(x) for x in command], 'object_sha256':digest(obj),
                             'dependencies':dependencies})
        record = json.loads(meta.read_text())
        record.update(source=str(source.relative_to(ROOT)), object=str(obj), log=str(log), reused=reused)
        return record

    records = []
    try:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            for record in pool.map(compile_one, all_sources):
                records.append(record)
        library = out/'libtflm_network.a'
        # Every archive member has a unique basename and each build starts
        # with an empty derived archive, so profile changes cannot retain
        # objects absent from the current source inventory.
        library.unlink(missing_ok=True)
        run([ar, 'rcs', library, *[r['object'] for r in records[:len(source_files)]]], out/'archive.log')
        elf = out/'cpu.elf'
        link = [gxx, '-march=rv32im_zicsr', '-mabi=ilp32', '-nostdlib', '-nostartfiles',
                '-T', SOC/'link.ld', '-Wl,--defsym=__ram_length='+str(RAM_BYTES),
                '-Wl,--defsym=full_network_heap_stack_top=0x101000',
                '-Wl,--gc-sections', '-Wl,-u,__libc_init_array', '-Wl,-Map='+str(out/'cpu.map'),
                *[r['object'] for r in records[len(source_files):]],
                '-Wl,--start-group', library, *runtime_libs, '-Wl,--end-group', '-o', elf]
        run(link, out/'link.log')
        run([objcopy, '-O', 'binary', elf, out/'cpu.bin'], out/'objcopy.log')
        raw = (out/'cpu.bin').read_bytes()
        raw += bytes((-len(raw)) % 4)
        (out/'cpu.mem').write_text('@00000000\n'+''.join(f'{word[0]:08x}\n' for word in struct.iter_unpack('<I',raw)))
        symbol_text = subprocess.check_output([nm, '-n', '-S', elf], text=True)
        (out/'cpu.nm').write_text(symbol_text)
        symbols = {}
        sizes = {}
        for line in symbol_text.splitlines():
            parts = line.split()
            if len(parts) == 4 and re.fullmatch('[0-9a-fA-F]+', parts[0]):
                symbols[parts[3]], sizes[parts[3]] = int(parts[0],16), int(parts[1],16)
            elif len(parts) == 3 and re.fullmatch('[0-9a-fA-F]+', parts[0]):
                symbols[parts[2]] = int(parts[0],16)
        if symbols['_end'] > 0x100000:
            raise RuntimeError('firmware/BSS overlaps the immutable model arena')
        run([readelf, '-h', '-A', elf], out/'attributes.log')
        local_deps, external_deps = {}, {}
        for record in records:
            for name, value in record['dependencies'].items():
                path = Path(name)
                if path.is_relative_to(ROOT): local_deps[str(path.relative_to(ROOT))] = value
                else: external_deps[name] = value
        local_deps.update(before)
        stable = all(digest(ROOT/name) == value for name,value in local_deps.items())
        stable = stable and all(digest(name) == value for name,value in external_deps.items())
        manifest = {'passed':stable, 'returncode':0, 'sources_unchanged_during_build':stable,
            'profile':'hardware' if hardware else 'software', 'hardware':hardware, 'trace_enabled':trace,
            'rounding_mode':'nearest_even',
            'compile_defines':{'DSA_NN_RUNTIME_CONTROL':1,
                              'DSA_NN_CONV_ENABLE':int(hardware), 'DSA_NN_VECTOR_ENABLE':int(hardware),
                              'DSA_NN_FC_ENABLE':int(hardware),
                              'FULL_NETWORK_TRACE_ENABLED':int(trace),
                              'NMSIS_NN':True, 'DSA_PCR_ENGINE':0},
            'supported_modes':[31] if hardware else [0], 'preserve_all_tensors':False,
            'trace_mechanism':'separate verification ELF; existing MicroProfilerInterface EndEvent' if trace else 'none',
            'timing':'actual CPU rdcycle around complete MicroInterpreter::Invoke; excludes initialization and output checking',
            'ram_bytes':RAM_BYTES, 'arena_bytes':arena_bytes,
            'arena_address':symbols['full_network_arena'], 'arena_end':symbols['full_network_arena']+sizes['full_network_arena'],
            'symbols':symbols, 'symbol_sizes':sizes,
            'config_fields':abi_fields('CONFIG'), 'result_fields':abi_fields('RESULT'), 'trace_fields':abi_fields('TRACE'),
            'source_sha256':local_deps, 'external_dependency_sha256':external_deps,
            'compiler':gcc, 'compiler_sha256':digest(gcc),
            'compiler_version':subprocess.check_output([gcc,'--version'],text=True).splitlines()[0],
            'runtime_libraries':{str(p):digest(p) for p in runtime_libs},
            'elf':str(elf), 'mem':str(out/'cpu.mem'), 'elf_sha256':digest(elf),
            'mem_sha256':digest(out/'cpu.mem'), 'binary_sha256':digest(out/'cpu.bin'),
            'link_command':[str(x) for x in link], 'compilations':records,
            'dispatch':'Compile-time C/C++ accelerator enable plus runtime mask 31' if hardware else 'Compile-time C/C++ accelerators disabled; mask 0'}
        write_json(out/'firmware.json',manifest)
        if stable: (out/'build_failure.json').unlink(missing_ok=True)
        if not stable: raise RuntimeError('sources changed during firmware build')
        return manifest
    except Exception as error:
        write_json(out/'build_failure.json', {'error':str(error), 'source_sha256_at_start':before,
                   'completed_compilations':records, 'trace_enabled':trace})
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=ROOT/'build/model_benchmark/firmware')
    p.add_argument('--gcc', default='riscv64-unknown-elf-gcc')
    p.add_argument('--runtime-root', type=Path, help='Optional standalone official GCC C++ and newlib runtime installation')
    p.add_argument('--object-cache',type=Path)
    p.add_argument('--jobs',type=int,default=1)
    p.add_argument('--arena-bytes',type=int,default=256*1024)
    p.add_argument('--trace',action='store_true')
    p.add_argument('--hardware', action=argparse.BooleanOptionalAction, default=True)
    args=p.parse_args()
    if args.jobs < 1: p.error('--jobs must be positive')
    manifest=build_firmware(args.out,args.gcc,hardware=args.hardware,trace=args.trace,
        runtime_root=args.runtime_root,jobs=args.jobs,object_cache=args.object_cache,arena_bytes=args.arena_bytes)
    print(json.dumps({'passed':manifest['passed'],'out':str(args.out.resolve()),
                     'hardware':args.hardware,'trace':args.trace,'modes':manifest['supported_modes'],
                     'source_files':len(manifest['source_sha256']),
                     'elf_sha256':manifest['elf_sha256']}))


if __name__=='__main__': main()
