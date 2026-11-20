#!/usr/bin/env python3
"""在新工作目录中恢复交接包，并逐项检查文件摘要和提交内容。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def git(directory, *arguments, data=None):
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


def checked_path(root, relative):
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeError('交接包包含无效路径：' + relative)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--repository', type=Path,
                        help='使用已有仓库建立独立工作树；省略时从包内 bundle 创建新仓库')
    parser.add_argument('--method', choices=('patches', 'bundle'), default='patches')
    args = parser.parse_args()
    package = args.package.resolve()
    destination = args.destination.resolve()
    checksums = json.loads((package / 'checksums.json').read_text())
    for relative, expected in checksums.items():
        path = checked_path(package, relative)
        if digest(path) != expected:
            raise RuntimeError('文件摘要不匹配：' + relative)
    manifest = json.loads((package / 'manifest.json').read_text())
    if destination.exists():
        raise RuntimeError('恢复目录必须尚未存在：' + str(destination))
    bundle = package / 'source.bundle'
    if args.repository:
        repository = args.repository.resolve()
        git(repository, 'cat-file', '-e', manifest['base_commit'] + '^{commit}')
        git(repository, 'worktree', 'add', '--detach', str(destination), manifest['base_commit'])
    else:
        destination.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(destination)], check=True)
        git(destination, 'fetch', '--no-tags', str(bundle), manifest['bundle_main_ref'])
        git(destination, 'checkout', '--detach', manifest['base_commit'])
    applied = []
    if args.method == 'patches':
        for record in manifest['commits']:
            current = git(destination, 'rev-parse', 'HEAD').decode().strip()
            if record['parents'] != [current]:
                raise RuntimeError('补丁顺序与父提交不匹配：' + record['commit'])
            patch = checked_path(package, record['patch'])
            git(destination, 'apply', '--check', '--index', '--binary', str(patch))
            git(destination, 'apply', '--index', '--binary', '--whitespace=nowarn', str(patch))
            tree = git(destination, 'write-tree').decode().strip()
            if tree != record['tree']:
                raise RuntimeError('补丁产生的源码树不匹配：' + record['commit'])
            raw_commit = checked_path(package, record['raw_commit']).read_bytes()
            restored = git(destination, 'hash-object', '-w', '-t', 'commit', '--stdin',
                           data=raw_commit).decode().strip()
            if restored != record['commit']:
                raise RuntimeError('提交内容不匹配：' + record['commit'])
            git(destination, 'update-ref', 'HEAD', restored, current)
            applied.append(restored)
    git(destination, 'fetch', '--no-tags', str(bundle),
        *(reference + ':' + reference for reference in manifest['bundle_refs']))
    if args.method == 'bundle':
        git(destination, 'checkout', '--detach', manifest['commit'])
    for item in manifest['submodules']:
        path = checked_path(destination, item['path'])
        path.mkdir(parents=True, exist_ok=True)
        if any(path.iterdir()):
            raise RuntimeError('子模块恢复目录必须为空：' + item['path'])
        subprocess.run(['git', 'init', '-q', str(path)], check=True)
        git(path, 'fetch', '--no-tags', str(package / item['bundle']), item['bundle_ref'])
        git(path, 'checkout', '--detach', item['commit'])
        if git(path, 'rev-parse', 'HEAD').decode().strip() != item['commit']:
            raise RuntimeError('子模块提交不匹配：' + item['path'])
    final = git(destination, 'rev-parse', 'HEAD').decode().strip()
    tree = git(destination, 'rev-parse', 'HEAD^{tree}').decode().strip()
    if final != manifest['commit'] or tree != manifest['tree']:
        raise RuntimeError('恢复后的完整提交或源码树不匹配')
    if git(destination, 'status', '--porcelain', '--untracked-files=normal').strip():
        raise RuntimeError('恢复后的工作目录包含未提交差异')
    report = {'passed': True, 'method': args.method, 'commit': final, 'tree': tree,
              'patch_commits_checked': len(applied), 'files_checked': len(checksums),
              'historical_reference_commits': manifest['historical_reference_commits'],
              'submodules': [{'path': item['path'], 'commit': item['commit']}
                             for item in manifest['submodules']]}
    output = destination.parent / (destination.name + '.recovery.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
