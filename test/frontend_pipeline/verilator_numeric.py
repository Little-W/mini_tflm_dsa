#!/usr/bin/env python3
"""选择综合条件分支，并限制数值验证的编译并行度。"""
import os
import sys

arguments = sys.argv[1:]
for index, value in enumerate(arguments[:-1]):
    if value in ('-j', '--build-jobs'):
        arguments[index+1] = '1'
target = os.environ.get('FRONTEND_RTL_TARGET', 'asic')
define = '-DASIC_SYNTHESIS=1' if target == 'asic' else '-DXILINX_FPGA=1'
arguments += ['-DSYNTHESIS=1', define,
              '-I'+os.environ['FRONTEND_RTL_ROOT']+'/include',
              '-I'+os.environ['FRONTEND_RTL_ROOT']+'/asic/rtl',
              '-GREGISTER_DESCRIPTOR='+os.environ.get('FRONTEND_REGISTER_DESCRIPTOR', '1'),
              '--output-split', '12000', '--output-groups', '0',
              '-CFLAGS', '-O1 -std=c++20', '-MAKEFLAGS',
              'OPT_FAST=-O1 OPT_SLOW=-O1 OPT_GLOBAL=-O1 '
              'VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E']
executable = os.environ['FRONTEND_REAL_VERILATOR']
os.execv(executable, [executable, *arguments])
