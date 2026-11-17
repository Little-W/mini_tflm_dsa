# 计算核心验证

该测试通过薄封装直接实例化 `rtl/npu/compute/compute_core.sv`，验证 DiP 阵列、部分和缓存及输出控制。每周期送入完整输入行，权重按照 `B[(row+column)%SIZE][column]` 旋转并从最后一行开始加载。测试逐项检查每个 K tile 的 INT32 结果、下一 K tile 恢复的 PS、最终输出及完成信号。

Verilator 可以直接运行同一 SystemVerilog 测试平台：

```bash
python3 test/compute_core/run.py --verilator /path/to/verilator
```

默认覆盖 SIZE=4、8、16，各自的归约长度为 `3×SIZE+3`，包含四个 K tile 和尾部零填充。SIZE=16 另用同一个压缩存储构建分别运行 RAW32 和 adaptive。测试需要 Python 与 NumPy；输出目录默认为 `build/compute_core/`，其中 `summary.json` 保存源码与可执行文件 SHA-256、命令及数值比较数量。

从仓库根目录运行固定输入测试：

```bash
make vcs-unit-compute_core
```

运行随机矩阵测试：

```bash
make vcs-random-compute COUNT=2 SEED=42
```

参考矩阵与输入文件由 `gen_mats.py` 生成，可用 `--size` 和 `--k` 指定维度。VCS 的固定输入和随机数据分别保存在 `build/vcs/unit/compute_case/`、`build/vcs/unit/compute_random/`；构建与仿真结果位于 `build/vcs/unit/` 下按配置命名的 `compute_core*` 子目录。所有入口保持 `PASS: compute_core matched` 标记；数值或时序不符合参考结果时，通过 `$fatal` 返回失败状态。
