#!/usr/bin/env python3
"""基于已核对的远端提交导出增量 bundle，并在独立对象库中恢复验证。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]


def git(*arguments, directory=ROOT, data=None):
    result = subprocess.run(['git', '-C', str(directory), *map(str, arguments)],
                            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return result.stdout


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clean(directory):
    if git('status', '--porcelain', directory=directory).strip():
        raise RuntimeError(f'导出目录包含未提交修改：{directory}')


def referenced_commits(revision):
    result = subprocess.run(['git', '-C', str(ROOT), 'grep', '-I', '-h', '-E',
                             '[0-9a-f]{7,40}', revision, '--', 'docs', 'scripts', 'test'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode(errors='replace'))
    candidates = sorted(set(re.findall(rb'(?<![0-9a-z])([0-9a-f]{7,40})(?![0-9a-z])', result.stdout)))
    objects = git('cat-file', '--batch-check=%(objectname) %(objecttype)',
                  data=b'\n'.join(candidates)+b'\n').decode().splitlines()
    return sorted({line.split()[0] for line in objects if line.endswith(' commit')})


def tree_entries(directory, revision):
    entries = []
    for record in git('ls-tree', '-rz', revision, directory=directory).split(b'\0'):
        if not record:
            continue
        metadata, path = record.split(b'\t', 1)
        mode, kind, object_id = metadata.decode().split()
        entries.append((mode, kind, object_id, os.fsdecode(path)))
    return entries


def tracked_content(directory, revision):
    records = {}
    for mode, kind, object_id, name in tree_entries(directory, revision):
        path = directory/name
        if kind == 'commit':
            records[name] = {'mode': mode, 'commit': object_id}
        elif mode == '120000':
            records[name] = {'mode': mode, 'sha256': hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()}
        else:
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f'受版本控制的文件不存在：{path}')
            if bool(path.stat().st_mode & 0o111) != (mode == '100755'):
                raise RuntimeError(f'文件执行权限不一致：{path}')
            records[name] = {'mode': mode, 'sha256': digest(path)}
    encoded = json.dumps(records, sort_keys=True, separators=(',', ':')).encode()
    return records, hashlib.sha256(encoded).hexdigest()


def independent_repository(source, destination, revision):
    destination.mkdir(parents=True, exist_ok=False)
    git('init', '--initial-branch=restore', directory=destination)
    # fetch 为目标仓库接收独立对象，不使用共享对象或 alternates。
    git('fetch', '--no-tags', '--no-recurse-submodules', source, revision, directory=destination)
    if (destination/'.git/objects/info/alternates').exists():
        raise RuntimeError('恢复对象库不可依赖外部对象目录')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', default='origin')
    parser.add_argument('--branch', default='main')
    parser.add_argument('--label', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--restore', type=Path, required=True)
    parser.add_argument('--evaluation', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', args.label):
        parser.error('label 仅允许小写英文字母、数字、下划线和连字符')
    clean(ROOT)
    revision = git('rev-parse', 'HEAD^{commit}').decode().strip()
    tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
    remote_ref = 'refs/heads/'+args.branch
    remote_lines = git('ls-remote', '--exit-code', args.remote, remote_ref).decode().splitlines()
    if len(remote_lines) != 1:
        raise RuntimeError('远端分支必须唯一')
    base, observed_ref = remote_lines[0].split()
    if observed_ref != remote_ref:
        raise RuntimeError('远端返回的分支与请求不一致')
    git('fetch', '--no-tags', args.remote, base)
    remote_url = git('remote', 'get-url', args.remote).decode().strip()
    git('merge-base', '--is-ancestor', base, revision)
    evaluation_path = args.evaluation.resolve()
    evaluation = json.loads(evaluation_path.read_text())
    measured_revision = evaluation['source']['commit']
    git('diff', '--exit-code', measured_revision, revision, '--',
        'rtl', 'include', 'config/npu_fpga.mk', 'picorv32')
    out, restored = args.out.resolve(), args.restore.resolve()
    if out.exists() or restored.exists():
        raise FileExistsError('导出目录与独立恢复目录必须使用新的路径')
    out.mkdir(parents=True)
    bundle = out/(args.label+'.bundle')
    main_ref = 'refs/checkpoints/'+args.label+'/main'
    references = {main_ref: revision}
    for commit in referenced_commits(revision):
        result = subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', commit, revision],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 1:
            references['refs/checkpoints/'+args.label+'/reference/'+commit] = commit
        elif result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace'))
    created = {}
    try:
        for reference, commit in references.items():
            git('update-ref', reference, commit, '0'*40)
            created[reference] = commit
        git('-c', 'pack.threads=1', '-c', 'pack.windowMemory=64m', 'bundle', 'create',
            bundle, *references, '^'+base)
    finally:
        for reference, commit in created.items():
            git('update-ref', '-d', reference, commit)
    git('bundle', 'verify', bundle)
    prerequisites = []
    with bundle.open('rb') as stream:
        while line := stream.readline().rstrip(b'\n'):
            if line.startswith(b'-'):
                prerequisites.append(line[1:].split(b' ', 1)[0].decode())
    independent_repository(remote_url, restored, base)
    git('bundle', 'verify', bundle, directory=restored)
    git('fetch', '--no-tags', bundle,
        '+refs/checkpoints/'+args.label+'/*:refs/checkpoints/'+args.label+'/*', directory=restored)
    git('checkout', '--detach', main_ref, directory=restored)
    fsck = git('fsck', '--full', '--strict', directory=restored)
    if git('rev-parse', 'HEAD^{commit}', directory=restored).decode().strip() != revision:
        raise RuntimeError('独立恢复后的提交不一致')
    if git('rev-parse', 'HEAD^{tree}', directory=restored).decode().strip() != tree:
        raise RuntimeError('独立恢复后的文件树不一致')
    original_files, original_digest = tracked_content(ROOT, revision)
    restored_files, restored_digest = tracked_content(restored, revision)
    if original_files != restored_files:
        raise RuntimeError('独立恢复后的文件内容或权限不一致')
    submodules = []
    for mode, kind, commit, name in tree_entries(ROOT, revision):
        if mode != '160000':
            continue
        source, destination = ROOT/name, restored/name
        clean(source)
        if git('rev-parse', 'HEAD^{commit}', directory=source).decode().strip() != commit:
            raise RuntimeError('子模块检出提交与主仓库记录不一致：'+name)
        if destination.exists() and not any(destination.iterdir()):
            destination.rmdir()
        independent_repository(source, destination, commit)
        git('checkout', '--detach', commit, directory=destination)
        git('fsck', '--full', '--strict', directory=destination)
        before, before_digest = tracked_content(source, commit)
        after, after_digest = tracked_content(destination, commit)
        if before != after:
            raise RuntimeError('子模块独立恢复后的内容不一致：'+name)
        submodules.append({'path': name, 'commit': commit, 'files': len(before),
                           'tracked_content_sha256': before_digest, 'restored_content_sha256': after_digest,
                           'fsck_passed': True, 'independent_object_store': True})
    clean(ROOT)
    clean(restored)
    if git('rev-parse', 'HEAD').decode().strip() != revision:
        raise RuntimeError('导出过程中源提交发生改变')
    verification = {
        'schema_version': 1, 'created_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'remote_branch': args.remote+'/'+args.branch, 'remote_commit': base,
        'commit': revision, 'tree': tree, 'bundle_main_ref': main_ref,
        'bundle_refs': references, 'bundle_prerequisites': prerequisites,
        'bundle_bytes': bundle.stat().st_size, 'bundle_sha256': digest(bundle),
        'commits_since_remote': int(git('rev-list', '--count', base+'..'+revision)),
        'independent_restore': {'passed': True, 'independent_object_store': True,
            'base_object_source': 'fetch of the verified commit from the configured remote URL',
            'bundle_verified_against_base': True, 'fsck_full_strict_passed': True,
            'fsck_stdout_sha256': hashlib.sha256(fsck).hexdigest(),
            'head_matches': True, 'tree_matches': True, 'tracked_files': len(original_files),
            'tracked_content_sha256': original_digest, 'restored_content_sha256': restored_digest,
            'tracked_content_and_modes_match': True, 'clean_worktree': True, 'submodules': submodules},
        'evaluation_path': str(evaluation_path.relative_to(ROOT)),
        'evaluation_sha256': digest(evaluation_path), 'evaluation': evaluation,
        'measured_rtl_matches_exported_commit': True, 'remote_push_performed': False,
    }
    verification_path = out/(args.label+'_verification.json')
    verification_path.write_text(json.dumps(verification, ensure_ascii=False, indent=2)+'\n')
    readme = out/(args.label+'.md')
    readme.write_text(f'''# SoC 优化提交与恢复说明

导出提交为 `{revision}`，远端 `{args.remote}/{args.branch}` 的已核对提交为 `{base}`。
增量范围包含 {verification['commits_since_remote']} 个提交。主提交引用为 `{main_ref}`。

## 恢复

在已经连接原远端仓库的工作目录中执行以下命令。`BUNDLE_PATH` 指向本次下载的 bundle 文件。

```bash
git fetch origin main
git cat-file -e {base}^{{commit}}
git bundle verify "$BUNDLE_PATH"
git fetch "$BUNDLE_PATH" '+refs/checkpoints/{args.label}/*:refs/checkpoints/{args.label}/*'
git switch -c restored_{args.label} {main_ref}
git submodule update --init --recursive
git fsck --full --strict
git rev-parse HEAD
```

最终 `HEAD` 应为 `{revision}`，文件树应为 `{tree}`。
bundle 包含主分支提交及仓库测试引用的辅助提交；子模块按仓库记录的固定提交初始化。

## 导出验证

独立对象库从已核对的远端提交开始，完成 bundle 检查、导入、检出和 `git fsck --full --strict`。
共检查 {len(original_files):,} 个受版本控制的文件或子模块记录，文件内容和执行权限均一致。
完整配置、资源、组合路径和功能检查结果保存在 `{verification_path.name}` 的 `evaluation` 中。

| 文件 | SHA-256 |
| --- | --- |
| `{bundle.name}` | `{verification['bundle_sha256']}` |

本次操作只导出本地提交。远端仓库没有推送操作。
''')
    print(json.dumps({'bundle': str(bundle), 'report': str(readme), 'verification': str(verification_path),
                      'commit': revision, 'remote_commit': base, 'independent_restore_passed': True},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
