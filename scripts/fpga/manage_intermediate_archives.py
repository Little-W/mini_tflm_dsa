#!/usr/bin/env python3
"""压缩已完成测量的中间文件，并按清单恢复和核对完整内容。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_manifest(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def relative_path(root, value):
    source = root / value
    if source.is_symlink():
        raise ValueError(f'Symbolic links are not intermediate files: {value}')
    resolved = source.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f'Path is outside the selected root: {value}')
    return resolved.relative_to(root)


def archive_file(root, relative, manifest, manifest_path):
    name = str(relative)
    source = root / relative
    existing = manifest['files'].get(name)
    if existing:
        target = root / existing['archive']
        if sha256(target) != existing['archive_sha256']:
            raise ValueError(f'Archive checksum differs: {target}')
        if source.exists() and sha256(source) != existing['uncompressed_sha256']:
            raise ValueError(f'Existing source differs: {source}')
        return existing
    status = source.stat()
    target = source.with_suffix(source.suffix + '.gz')
    temporary = target.with_suffix(target.suffix + '.tmp')
    if target.exists() or temporary.exists():
        raise FileExistsError(target)
    original_hash = sha256(source)
    try:
        with source.open('rb') as input_file, temporary.open('xb') as output:
            with gzip.GzipFile(fileobj=output, mode='wb', filename='', compresslevel=1, mtime=0) as archive:
                shutil.copyfileobj(input_file, archive, 1024 * 1024)
        with gzip.open(temporary, 'rb') as archive:
            restored_hash = hashlib.file_digest(archive, 'sha256').hexdigest()
        if restored_hash != original_hash:
            raise ValueError(f'Restored checksum differs: {source}')
        current = source.stat()
        if (current.st_size, current.st_mtime_ns) != (status.st_size, status.st_mtime_ns):
            raise ValueError(f'Source changed during compression: {source}')
        temporary.replace(target)
        entry = {'archive': str(target.relative_to(root)), 'uncompressed_sha256': original_hash,
                 'archive_sha256': sha256(target), 'uncompressed_bytes': status.st_size,
                 'archive_bytes': target.stat().st_size, 'mode': status.st_mode & 0o777,
                 'mtime_ns': status.st_mtime_ns, 'decompressed_content_verified': True}
        manifest['files'][name] = entry
        write_manifest(manifest_path, manifest)
        source.unlink()
        return entry
    finally:
        if temporary.exists():
            temporary.unlink()


def restore_file(root, relative, entry):
    source = root / relative
    archive = root / entry['archive']
    if sha256(archive) != entry['archive_sha256']:
        raise ValueError(f'Archive checksum differs: {archive}')
    if source.exists():
        if sha256(source) != entry['uncompressed_sha256']:
            raise FileExistsError(f'Existing file has different content: {source}')
        return
    source.parent.mkdir(parents=True, exist_ok=True)
    temporary = source.with_suffix(source.suffix + '.restore.tmp')
    try:
        with gzip.open(archive, 'rb') as input_file, temporary.open('xb') as output:
            shutil.copyfileobj(input_file, output, 1024 * 1024)
        if temporary.stat().st_size != entry['uncompressed_bytes'] or sha256(temporary) != entry['uncompressed_sha256']:
            raise ValueError(f'Restored checksum differs: {source}')
        os.chmod(temporary, entry['mode'])
        os.utime(temporary, ns=(entry['mtime_ns'], entry['mtime_ns']))
        temporary.replace(source)
    finally:
        if temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('archive', 'restore'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--paths-file', type=Path)
    selection.add_argument('--path', action='append')
    selection.add_argument('--all', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = (json.loads(args.manifest.read_text()) if args.manifest.exists()
                else {'schema_version': 1, 'original_root': str(root), 'compression': 'gzip', 'files': {}})
    if args.all:
        if args.operation != 'restore':
            parser.error('--all is available for restore')
        names = sorted(manifest['files'])
    elif args.paths_file:
        names = json.loads(args.paths_file.read_text())
    else:
        names = args.path
    for name in names:
        relative = relative_path(root, name)
        if args.operation == 'archive':
            entry = archive_file(root, relative, manifest, args.manifest)
            print(json.dumps({'path': str(relative), 'bytes_saved': entry['uncompressed_bytes'] - entry['archive_bytes'],
                              'sha256': entry['uncompressed_sha256']}, ensure_ascii=False), flush=True)
        else:
            restore_file(root, relative, manifest['files'][str(relative)])
            print(json.dumps({'restored': str(relative), 'sha256': manifest['files'][str(relative)]['uncompressed_sha256']},
                             ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
