# AXI 双项缓冲验证

`soc_axi_pingpong_chan` 使用两个数据寄存器保存完整数据，并以非空与满状态直接产生输出资格。同步复位、收发事件、读写位置和全部输出由完整状态证明与四态仿真检查。

当前设计、测量数据和检查说明见 [占用状态验证](../axi_occupancy/README.md)。`verify.py` 调用该验证程序，保持已有执行入口：

```bash
python3 test/soc_pingpong/verify.py --out build/soc_pingpong
python3 test/soc_pingpong/synthesis.py --out build/soc_pingpong_synthesis
```

两个程序默认使用参考提交 `8aa34632c9cb0d1a8ea047a76d53e28dfee0006f`。可使用 `--reference` 指定其他参考版本。`verify.py` 支持 `--iverilog`、`--vvp`、`--source-root` 和 `--tool-root`，并可通过 `--measure` 同时运行独立综合。
