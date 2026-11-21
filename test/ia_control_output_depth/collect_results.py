#!/usr/bin/env python3
"""核对 IA 请求与共享写数据的同源功能验证和完整模块测量。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOADER = 'rtl/npu/loaders/ia_loader.sv'
CACHE = 'rtl/npu/loaders/ia_loader_cache_mgr.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('loader-formal', 'cache-formal', 'four-state', 'numeric', 'measurement'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    reports = {name: json.loads(getattr(args, name).read_text()) for name in
               ('loader_formal', 'cache_formal', 'four_state', 'numeric', 'measurement')}
    hashes = {name: digest(ROOT / name) for name in (LOADER, CACHE)}
    for name in ('loader_formal', 'cache_formal', 'four_state', 'numeric'):
        if reports[name]['passed'] is not True:
            raise RuntimeError('功能检查不完整：' + name)
    if any(reports['loader_formal']['source_sha256'][name] != sha for name, sha in hashes.items()):
        raise RuntimeError('加载器形式检查源码不匹配')
    if reports['cache_formal']['source_sha256'][CACHE] != hashes[CACHE]:
        raise RuntimeError('缓存形式检查源码不匹配')
    if reports['four_state']['source_sha256'] != hashes[CACHE]:
        raise RuntimeError('四态检查源码不匹配')
    cache_matches = [sha for name, sha in reports['numeric']['source_sha256'].items()
                     if name.endswith(CACHE)]
    if cache_matches != [hashes[CACHE]]:
        raise RuntimeError('实际存储事务检查源码不匹配')
    for label in ('reference', 'current'):
        part = reports['measurement'][label]
        if part['register_paths']['graph_complete'] is not True:
            raise RuntimeError('模块图覆盖不完整')
        if label == 'current':
            for source, expected in hashes.items():
                matches = [sha for name, sha in part['source_manifest']['sources_sha256'].items()
                           if name.endswith(source)]
                if matches != [expected]:
                    raise RuntimeError('模块测量源码不匹配：' + source)
    result = dict(passed=True, source_sha256=hashes, reports=reports,
        input_reports_sha256={str(getattr(args, name)): digest(getattr(args, name)) for name in reports},
        physical_timing_confirmed=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, source_sha256=hashes)))


if __name__ == '__main__':
    main()
