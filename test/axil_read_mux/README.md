# AXI-Lite 寄存器读回验证

本目录验证 `npu_axil_reg_if` 的分组读回逻辑。每组包含十六个寄存器字，组内按照低位地址选择，高位地址的互斥条件直接选择对应组的数据。公开端口、读回周期、字节写使能、忙状态下的写入处理以及完成状态均参加等价检查。

## 执行

环境需要 Python 3、提供 `read_slang` 的 `pyosys`、Verilator、Icarus Verilog 和 C++ 编译器。

```bash
python test/axil_read_mux/run_validation.py --baseline-ref 4dee27ff
```

默认执行四个步骤：完整模块等价检查、地址与数据四态检查、独立模块面积比较、原有二十三种配置的 AXI-Lite 事务测试。四态检查直接调用本目录的 `run_four_state.py`，事务测试直接调用 `test/capacity/run_shared_bank_registers.py`。

执行形式等价、四态检查和面积比较：

```bash
python test/axil_read_mux/run_validation.py --baseline-ref 4dee27ff --skip-transactions
```

使用已存在的事务测试编译目录：

```bash
python test/axil_read_mux/run_validation.py \
  --baseline-ref 4dee27ff \
  --transaction-out build/soc_timing/shared_registers
```

事务测试会重新检查源码与编译输入，并运行测试程序。

## 检查范围

参考源码始终通过 `git show` 从 `--baseline-ref` 指定的提交读取。当前源码取自工作目录。两份源码分别保存副本并记录 SHA256，使用相同参数完成检查；测试结束时再次确认当前文件内容未变化。

等价检查读取完整模块，将时序过程转换为形式检查可处理的表示，并执行 `equiv_make`、`equiv_simple`、`equiv_induct` 和 `equiv_status -assert`。二态时序模型下的公开端口及匹配内部信号全部通过后，测试才记录通过结果。

四态检查直接提取生产源码中的选择逻辑，同时核对全部七十七条寄存器赋值表达式和七十五个地址。32 位和 64 位 AXI-Lite 数据宽度分别执行 11,264 组检查，覆盖全部 4,096 个地址、未知地址位、高阻地址位以及包含 `X`、`Z` 的读数据；共享存储配置还覆盖七种能力位图，每种执行 100,004 次四态输入检查。

面积比较使用 `scripts/fpga/open_fpga_synth.py` 的 `synth_xilinx -family xc7` 流程，记录逻辑 LUT、寄存器、存储器、DSP 和组合结构级数。当前实现的逻辑 LUT 数量、最长组合结构级数及最长寄存器间结构级数均须不大于参考实现。150 MHz 时序与物理 Slice LUT 数量由 Vivado 的布局布线报告确认。

二十三种配置的事务测试覆盖寄存器读取、字节写使能、共享容量配置、忙状态下的写入处理及返回错误应答的请求，启用 C++ 未定义行为检查。

本目录同时保留 `run.py` 的两种 AXI-Lite 数据位宽数值比较，以及共享存储配置的辅助检查入口。`run_validation.py` 汇总本轮参数下的等价、面积及事务结果。

## 结果

默认输出目录为 `build/axil_read_mux/`：

- `manifest.json`：比较提交、源码 SHA256 和模块参数。
- `equivalence.log`：完整等价检查结果。
- `four_state/summary.json`：地址、数据及共享存储配置的四态检查结果。
- `synthesis/summary.json`：两份实现的模块综合结果。
- `transactions/summary.json`：原有事务测试的结果。
- `summary.json`：本次检查的汇总结果。

`--transaction-out` 可以指定事务测试结果目录。本轮实际通过的结果保存在本目录的 `results_20261121.json`。

| 检查项 | 参考提交 `4dee27ff` | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 962 | 918 |
| 触发器 | 1,357 | 1,357 |
| 最长组合结构级数 | 6 | 6 |
| 最长寄存器间结构级数 | 5 | 5 |
| BRAM / DSP | 0 / 0 | 0 / 0 |

完整模块等价检查通过 5,743 个比较点；二十三种配置的事务测试通过 20,193 次检查，包含 2,898 次读取、759 次写入和 482 次预期返回错误应答的写请求。
