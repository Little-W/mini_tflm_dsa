#!/usr/bin/env python3
"""导出固定提交、逐提交补丁、完整历史、测量结果及可执行恢复脚本。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = 'aa2ef9a32daaded9ff16db0b8d3c905763dc95cb'


def git(*arguments, data=None, directory=ROOT):
    result = subprocess.run(['git', '-C', str(directory), *arguments], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return result.stdout


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def referenced_commits(revision):
    result = subprocess.run(['git', '-C', str(ROOT), 'grep', '-I', '-h', '-E',
                             '[0-9a-f]{7,40}', revision, '--', 'docs', 'scripts', 'test'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode(errors='replace'))
    candidates = sorted(set(re.findall(rb'(?<![0-9a-z])([0-9a-f]{7,40})(?![0-9a-z])', result.stdout)))
    objects = git('cat-file', '--batch-check=%(objectname) %(objecttype)',
                  data=b'\n'.join(candidates) + b'\n').decode().splitlines()
    return sorted({line.split()[0] for line in objects if line.endswith(' commit')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--base', default=BASE)
    parser.add_argument('--label', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--kind', choices=('rolling', 'synthesis-60000', 'physical-60000',
                                          'physical-45000'), default='rolling')
    parser.add_argument('--measurement-name')
    parser.add_argument('--measurement-file', type=Path, default=ROOT / 'docs/data/fpga_soc_measurements.json')
    parser.add_argument('--next-steps', type=Path, required=True)
    parser.add_argument('--include', action='append', default=[], metavar='NAME=PATH')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', args.label):
        parser.error('label 仅允许小写英文字母、数字、下划线和连字符')
    revision = git('rev-parse', args.ref + '^{commit}').decode().strip()
    base = git('rev-parse', args.base + '^{commit}').decode().strip()
    git('merge-base', '--is-ancestor', base, revision)
    if git('rev-list', '--merges', base + '..' + revision).strip():
        raise RuntimeError('逐提交补丁导出要求从指定起点到固定提交为线性历史')
    measurement = None
    if args.measurement_name:
        report = json.loads(args.measurement_file.read_text())
        measurement = next(item for item in report['measurements'] if item['name'] == args.measurement_name)
        git('diff', '--exit-code', measurement['source']['commit'], revision,
            '--', 'rtl', 'config/npu_fpga.mk', 'picorv32')
    if args.kind != 'rolling':
        if measurement is None or not measurement['source']['source_content_matches_git']:
            raise RuntimeError('面积检查点需要完整 SoC 的固定源码测量结果')
        if not measurement['functional_verification']['passed'] or not measurement['wide_alu_verification']['passed']:
            raise RuntimeError('面积检查点需要完整组合等价与 DSP 参数验证')
        if not measurement.get('register_path_graph_complete'):
            raise RuntimeError('面积检查点需要完整寄存器间组合路径分析')
        resources = measurement['resources']
        if args.kind == 'synthesis-60000':
            if not 0 < resources['logic_lut_cells'] <= 60000:
                raise RuntimeError('综合逻辑 LUT 尚未满足 60,000 条件')
        else:
            placement = measurement.get('placement') or {}
            positions = resources.get('physical_lut_sites_after_placement')
            maximum_positions = 45000 if args.kind == 'physical-45000' else 60000
            if (not placement.get('complete') or placement.get('resource_errors') or
                    placement.get('unplaced_cells') or positions is None or not 0 < positions <= maximum_positions):
                raise RuntimeError(f'物理 LUT 位置尚未满足合法布局和 {maximum_positions:,} 条件')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'patches').mkdir()
    (out / 'commits').mkdir()
    (out / 'external').mkdir()
    commits = git('rev-list', '--reverse', base + '..' + revision).decode().splitlines()
    git('format-patch', '--binary', '--full-index', '--no-stat', '--no-signature', '--always',
        '--numbered-files', '--output-directory', str(out / 'patches'), base + '..' + revision)
    patches = sorted((out / 'patches').iterdir(), key=lambda path: int(path.name))
    if len(patches) != len(commits):
        raise RuntimeError('补丁数量与提交数量不一致')
    records = []
    for index, (commit, patch) in enumerate(zip(commits, patches), 1):
        name = f'{index:04d}-{commit[:12]}.patch'
        patch.rename(out / 'patches' / name)
        raw = git('cat-file', 'commit', commit)
        (out / 'commits' / (commit + '.commit')).write_bytes(raw)
        header = raw.split(b'\n\n', 1)[0].decode()
        records.append({
            'commit': commit, 'tree': re.search(r'^tree (\w+)$', header, re.M)[1],
            'parents': re.findall(r'^parent (\w+)$', header, re.M),
            'subject': git('show', '-s', '--format=%s', commit).decode().strip(),
            'author_date': git('show', '-s', '--format=%aI', commit).decode().strip(),
            'patch': 'patches/' + name, 'raw_commit': 'commits/' + commit + '.commit',
        })
    (out / 'series').write_text(''.join(record['patch'] + '\n' for record in records))
    references = referenced_commits(revision)
    main_ref = 'refs/checkpoints/' + args.label + '/main'
    temporary_refs = {main_ref: revision}
    for commit in references:
        reachable = subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', commit, revision])
        if reachable.returncode == 1:
            temporary_refs['refs/checkpoints/' + args.label + '/reference/' + commit] = commit
        elif reachable.returncode:
            raise RuntimeError('无法检查参考提交：' + commit)
    for reference in temporary_refs:
        existing = subprocess.run(['git', '-C', str(ROOT), 'show-ref', '--verify', '--quiet', reference])
        if existing.returncode == 0:
            raise RuntimeError('检查点名称已经存在：' + reference)
    try:
        for reference, commit in temporary_refs.items():
            git('update-ref', reference, commit)
        git('-c', 'pack.threads=1', '-c', 'pack.windowMemory=64m', 'bundle', 'create',
            str(out / 'source.bundle'), *temporary_refs)
    finally:
        for reference, commit in temporary_refs.items():
            git('update-ref', '-d', reference, commit)
    git('bundle', 'verify', str(out / 'source.bundle'))
    submodules = []
    for line in git('ls-tree', '-r', revision).decode().splitlines():
        metadata, path = line.split('\t', 1)
        mode, kind, commit = metadata.split()
        if mode != '160000':
            continue
        directory = ROOT / path
        git('cat-file', '-e', commit + '^{commit}', directory=directory)
        reference = 'refs/checkpoints/' + args.label + '/' + commit
        bundle = 'external/' + path.replace('/', '_') + '.bundle'
        try:
            git('update-ref', reference, commit, directory=directory)
            git('bundle', 'create', str(out / bundle), reference, directory=directory)
        finally:
            git('update-ref', '-d', reference, commit, directory=directory)
        submodules.append({'path': path, 'commit': commit, 'bundle': bundle, 'bundle_ref': reference})
    with (out / 'source.tar.gz').open('wb') as compressed:
        archive = subprocess.Popen(['git', '-C', str(ROOT), 'archive', '--format=tar',
                                    '--prefix=source/', revision], stdout=subprocess.PIPE)
        with gzip.GzipFile(fileobj=compressed, mode='wb', mtime=0) as stream:
            shutil.copyfileobj(archive.stdout, stream)
        if archive.wait():
            raise RuntimeError('源码快照导出失败')
    with (out / 'combined.patch').open('wb') as stream:
        subprocess.run(['git', '-C', str(ROOT), 'diff', '--binary', '--full-index', base, revision],
                       stdout=stream, check=True)
    shutil.copyfile(Path(__file__).with_name('restore_checkpoint.py'), out / 'restore_checkpoint.py')
    for method, name in (('patches', 'apply_patches.sh'), ('bundle', 'restore_bundle.sh')):
        path = out / name
        path.write_text('#!/bin/sh\nset -eu\ncheckpoint_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                        'exec python3 "$checkpoint_dir/restore_checkpoint.py" --package "$checkpoint_dir" '
                        '--method ' + method + ' "$@"\n')
        path.chmod(0o755)
    shutil.copyfile(args.next_steps, out / 'NEXT_STEPS.md')
    if measurement:
        (out / 'measurement.json').write_text(json.dumps(measurement, ensure_ascii=False, indent=2) + '\n')
    included = {}
    for value in args.include:
        name, source = value.split('=', 1)
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+', name):
            raise RuntimeError('附加文件名称无效：' + name)
        source = Path(source).resolve()
        target = out / 'results' / name
        target.parent.mkdir(exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)
        included[name] = str(source)
    tree = git('rev-parse', revision + '^{tree}').decode().strip()
    manifest = {'schema_version': 1, 'label': args.label, 'kind': args.kind,
                'base_commit': base, 'commit': revision, 'tree': tree, 'commits': records,
                'bundle_main_ref': main_ref, 'bundle_refs': sorted(temporary_refs),
                'historical_reference_commits': references, 'submodules': submodules,
                'measurement': args.measurement_name, 'included_results': included,
                'requirements': {'physical_lut_positions_maximum': 45000,
                                 'clock_frequency_mhz': 150,
                                 'register_path_combinational_cells_maximum': 9},
                'requirement_status': {
                    'physical_lut_positions_within_45000':
                        measurement['resources']['physical_lut_sites_after_placement'] <= 45000
                        if measurement and measurement['resources'].get('physical_lut_sites_after_placement') is not None
                        else None,
                    'register_path_within_limit':
                        measurement['longest_register_path_cells'] <= 9
                        if measurement and measurement.get('register_path_graph_complete') else None,
                    'timing_150mhz_confirmed':
                        measurement['timing_150mhz_confirmed'] if measurement else None,
                },
                'generator_sha256': digest(Path(__file__)),
                'rtl_commit': measurement['source']['commit'] if measurement else revision}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    changes = ['# 修改记录', '', f'起始提交：`{base}`。', '', f'固定提交：`{revision}`。', '',
               '| 顺序 | 提交 | 作者时间 | 修改内容 |', '| ---: | --- | --- | --- |']
    for index, record in enumerate(records, 1):
        subject = record['subject'].replace('|', '\\|')
        changes.append(f"| {index} | `{record['commit'][:12]}` | {record['author_date']} | {subject} |")
    (out / 'CHANGES.md').write_text('\n'.join(changes) + '\n')
    title = {'rolling': '工作版本交接包', 'synthesis-60000': '完整 SoC 60,000 逻辑 LUT 交接包',
             'physical-60000': '完整 SoC 60,000 物理 LUT 位置交接包',
             'physical-45000': '完整 SoC 45,000 物理 LUT 位置交接包'}[args.kind]
    (out / 'README.md').write_text(f'''# {title}

固定提交为 `{revision}`，源码树为 `{tree}`。补丁起始提交为 `{base}`，共 {len(records)} 个提交。

## 内容

- `CHANGES.md`：按提交顺序列出的修改记录。
- `NEXT_STEPS.md`：复测流程及器件时序检查方法。
- `patches/` 与 `series`：完整二进制补丁系列及应用顺序。
- `commits/`：原始 Git 提交对象，保留作者、提交者、日期、说明和父提交。
- `source.bundle`：完整提交历史和验证脚本引用的历史提交。
- `source.tar.gz`：固定提交的源码快照；`external/` 保存子模块的独立恢复包。
- `combined.patch`：相对起始提交的完整差异。
- `manifest.json` 与 `checksums.json`：版本、配置来源和文件 SHA-256。
- `results/`：导出时指定的综合、实现、仿真和工具结果。

## 逐提交恢复

以下命令创建一个尚不存在的目录，按 `series` 顺序实际应用全部补丁，并检查每一步的源码树与原始提交标识。

```sh
./apply_patches.sh --destination /path/to/restored_soc
```

已有仓库含起始提交时，可在独立工作树中执行相同检查：

```sh
./apply_patches.sh --repository /path/to/mini_tflm_dsa --destination /path/to/restored_soc
```

## 直接恢复完整提交

```sh
./restore_bundle.sh --destination /path/to/restored_soc
```

两种方式均恢复子模块，并在恢复目录旁保存 `*.recovery.json`。恢复后工作目录保持清洁，目标分支和现有工作目录不受修改。

## 测量与继续运行

面积检查点的 `measurement.json` 记录实际测量阶段、固定 RTL、LUT、存储与 DSP 数量以及时序完成状态。后续运行命令见源码中的 `docs/fpga_optimization_reproduction.md` 和 `docs/open_fpga_synthesis.md`。
''')
    checksums = {str(path.relative_to(out)): digest(path) for path in sorted(out.rglob('*')) if path.is_file()}
    (out / 'checksums.json').write_text(json.dumps(checksums, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'package': str(out), 'commit': revision, 'commits': len(records),
                      'files': len(checksums), 'kind': args.kind}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
