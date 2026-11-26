#!/usr/bin/env python3
"""为前端形式检查显式设置通用或综合编译宏。"""


def slang_command(options=()):
    """通用模式撤销前端默认综合宏，综合模式使用调用者给出的定义。"""
    synthesis = any(option == '-DSYNTHESIS' or option.startswith('-DSYNTHESIS=')
                    for option in options)
    return 'read_slang ' if synthesis else 'read_slang -USYNTHESIS -UXILINX_FPGA '
