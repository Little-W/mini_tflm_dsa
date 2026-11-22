# 调度器命令等待与压力处理

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`ps_window_scheduler` 在命令进入缓冲区时保存恢复资格和打开阶段标志。命令等待期间，这两个标志保持稳定，压力到达时直接选择恢复操作。

完成、配置准备和行组结束分别更新其所属状态。有效等待命令与这些事件互斥，因此压力输入只参与等待命令的处理。公开接口、命令顺序、接收周期、完成周期和错误通知周期保持一致。

## 正式证明

检查使用实际 RTL，先证明新增状态的复位条件和一步无界归纳不变量，再建立所有公共寄存器的逐位对应关系。参考实现的每个寄存器位均必须找到对应状态；当前实现额外包含两个资格标志。

全部公开输出在公共状态相等及已证明的不变量成立时进行比较。下一周期的公共状态按最多 128 位分组验证，各组使用相同的完整状态关系和自由外部输入。分组范围连续覆盖全部公共状态。

| SIZE | FRAME_COUNT | MAX_REUSE_TILES | 公共寄存器状态位 | 状态转移分组 |
|---:|---:|---:|---:|---:|
| 4 | 4 | 4 | 1,278 | 10 |
| 16 | 16 | 32 | 2,286 | 18 |
| 4 | 2 | 0 | 1,530 | 12 |
| 8 | 4 | 1 | 1,249 | 10 |
| 16 | 8 | 16 | 1,634 | 13 |
| 合计 | | | 7,977 | 63 |

默认参考版本为 `cfcc1a95`。测试仅从该版本读取调度器源码，公共模块使用同一组当前源码。也可以通过 `--reference-root` 指定完整的参考源码目录。

```sh
python test/scheduler_pressure_state/run_formal.py \
  --out /tmp/scheduler_pressure_formal \
  --lock-file ../soc_synth.lock
```

## 四态与逐周期检查

五种参数分别在 `XILINX_FPGA` 和 `ASIC_SYNTHESIS` 模式下运行，包含命令接收、压力恢复、完成、重复配置、边界尺寸、随机等待、未知值和高阻值。共完成 850,512 次检查，其中包含 286,240 个四态输入周期。

```sh
python test/scheduler_command_outputs/run_four_state.py \
  --source-root . \
  --reference-root /tmp/scheduler_pressure_formal/reference \
  --profiles 4:4:4 16:16:32 4:2:0 8:4:1 16:8:16 \
  --out /tmp/scheduler_pressure_four_state
```

## 资源和组合路径

测量模块保留调度器所有公开输出，并在压力输入前放置一个普通寄存器，用于读取压力到各内部状态的真实组合路径。生产参数为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,130 | 1,134 |
| 分布式 RAM 名义 LUT | 56 | 56 |
| 名义 LUT 总数 | 1,186 | 1,190 |
| FF | 913 | 915 |
| DSP48E1 | 13 | 13 |
| RAMB36E1 | 2 | 2 |
| 模块全部寄存器之间的最大组合级数 | 9 | 9 |
| 压力寄存器到内部状态的最大组合级数 | 6 | 4 |
| 压力寄存器到 `ready`、`done_valid` 的组合级数 | 6 | 3 |

```sh
python scripts/fpga/open_fpga_synth.py \
  --source-root . \
  --case-config test/scheduler_pressure_state/synthesis_cases.json \
  --cases scheduler --out /tmp/scheduler_pressure_measure \
  --lock-file ../soc_synth.lock
```

测量遍历完整寄存器路径图。此处记录独立模块结果，整机组合级数由对应 SoC 固定源码版本的完整测量确定。`validation.json` 保存源文件散列、检查数量、参数、报告路径和报告散列。
