# NPU 时钟门控验证

`run_clock_gate.py` 使用 `tb_clock_gate_reset.sv` 检查生产 `npu_axil_top` 的时钟控制。测试覆盖不同复位释放相位、单次启动脉冲、空闲时关闭时钟，以及 AXI 应答尚未结束时保持时钟有效。

通用分支使用 Verilator，编译完整 NPU 层次。Xilinx 分支使用 Icarus Verilog 和官方 `BUFGCE.v`、`glbl.v` 模型。Xilinx 分支从生产源码提取 `npu_top` 与 `npu_axil_reg_if` 的公开接口，测试程序直接施加门控事件；生产时钟控制逻辑和官方 BUFGCE 模型参与仿真。

## 执行

需要 Python 3、Verilator、C++ 编译器、Icarus Verilog 和官方 UNISIM 模型。`--unisim-dir` 接受 Vivado 安装中的 `data/verilog/src` 目录，或直接包含 `BUFGCE.v`、`glbl.v` 的目录。模型也可从 [XilinxUnisimLibrary](https://github.com/Xilinx/XilinxUnisimLibrary) 获取。

```bash
python test/conv_dma/operand_drain/run_clock_gate.py \
  --mode all \
  --unisim-dir "$XILINX_UNISIM_DIR" \
  --out build/conv_dma/clock_gate
```

`XILINX_UNISIM_DIR` 应设为模型所在目录。只运行通用分支时使用 `--mode generic`，只运行 FPGA 分支时使用 `--mode xilinx`。`--verilator`、`--iverilog`、`--vvp` 可指定仿真程序，`--jobs` 控制 Verilator 编译并行度。

## 结果

输出目录按分支保存编译日志、运行日志和程序。`summary.json` 记录实际命令、源码与模型 SHA256、程序 SHA256、通过标记和编译期间源码是否保持不变。所选分支全部完成并通过后，汇总结果才为 `passed: true`。

通用分支检查用于 ASIC 实现的低电平锁存门控表达式，Xilinx 分支检查 BUFGCE 的功能行为。器件时序仍由完整设计的布局布线分析确定。
