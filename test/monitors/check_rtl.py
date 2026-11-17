#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check that hardware sources contain no testbench observation circuitry."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def main():
    failures = []
    files = [p for p in (ROOT / 'rtl').rglob('*') if p.suffix in ('.sv', '.v')]
    files += list((ROOT / 'asic/rtl').glob('*.sv'))
    for path in files:
        text = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', '', path.read_text(), flags=re.S)
        for pattern in (r'\b(?:stat_\w+|(?:conv|vector|ps|win|frame)_stat_\w+)\b',
                        r'\btb_observer\b', r'\b\w*(?:trace_en|util_trace_en)\b'):
            match = re.search(pattern, text)
            if match:
                failures.append(f'{path.relative_to(ROOT)}: {match.group(0)}')
        guards = []
        for line_number, line in enumerate(text.splitlines(), 1):
            directive = re.match(r'\s*`(ifdef|ifndef|else|endif)\b\s*(\w*)', line)
            if directive:
                operation, name = directive.groups()
                if operation in ('ifdef', 'ifndef'):
                    guards.append(name if operation == 'ifdef' else '')
                elif operation == 'else' and guards:
                    guards[-1] = ''
                elif operation == 'endif' and guards:
                    guards.pop()
            if re.search(r'\bassert\b|\$(?:fatal|error|display|write|test\$plusargs|value\$plusargs)\b', line) and 'NPU_SIM_ASSERT' not in guards:
                failures.append(f'{path.relative_to(ROOT)}:{line_number}: simulation assertion requires NPU_SIM_ASSERT')
    if failures:
        raise SystemExit('\n'.join(failures))
    print(f'RTL_OBSERVATION_CHECK_PASS files={len(files)}')


if __name__ == '__main__':
    main()
