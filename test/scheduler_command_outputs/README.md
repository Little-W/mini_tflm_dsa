# 调度器命令输出保持

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`ps_window_scheduler` 在命令执行期间保存命令描述，`frame_id`、`frame_init`、`p0`、`rows`、`q0` 和 `frame_final` 直接读取这些寄存器。命令接收状态独立于这些字段的输出路径，因此 PS 帧尺寸和容量检查可以直接使用已保存的字段。命令接收、执行完成、压力处理、配置错误通知和所有公开输出保持原有周期关系。

## 验证结果

- 六组参数的完整状态与公开输出等价证明全部通过，共 19,400 位，输入序列未施加约束。
- 独立调度模型通过 975 个配置和 182,426 条命令，覆盖完整帧、切片帧、14,760 次压力事件、帧编号重复使用、输出尾部尺寸以及非法配置处理。
- 实际参考模块与当前模块在八组参数及条件编译方式下逐周期比较，共完成 666,384 次公开输出比较。测试包含 228,992 个配置位 X/Z 注入和随机四态控制周期，同时检查执行字段与命令寄存器之间的保持关系。

生产参数为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`。独立模块采用相同综合设置的测量结果如下。

| 指标 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,234 | 1,111 |
| 包含分布式存储的名义 LUT | 1,290 | 1,167 |
| 触发器 | 966 | 901 |
| DSP48E1 | 13 | 13 |
| RAMB36E1 | 2 | 2 |
| 寄存器间最长组合级数 | 9 | 9 |

两次寄存器路径分析均覆盖完整图，包含同步数据输入和控制输入。该表描述独立调度器，完整 SoC 的跨模块路径另行测量。150 MHz 的频率检查需要目标器件的实现时序报告。

## 运行方法

参考源码提交为 `e389766c92424d4fab48302c82db4ed6b9a4de61`。先将该提交的 `rtl/npu/control/ps_window_scheduler.sv` 和 `rtl/common` 导出到独立目录，再将该目录传给 `--reference-root`。

```sh
python3 test/kernel_issue_timing/run_formal.py \
  --module ps_window_scheduler --source-root . --reference-root /tmp/scheduler_reference \
  --profiles 4:2:0 8:4:1 16:8:16 16:16:16 16:16:0 16:16:32 \
  --fpga --out /tmp/scheduler_command_formal
python3 test/ps_compression/run_window_scheduler.py \
  --source-root . --fpga --out /tmp/scheduler_command_numeric
python3 test/scheduler_command_outputs/run_four_state.py \
  --source-root . --reference-root /tmp/scheduler_reference \
  --out /tmp/scheduler_command_four_state
python3 scripts/fpga/open_fpga_synth.py --source-root . \
  --case-config test/scheduler_command_outputs/synthesis_cases.json --cases scheduler \
    --max-register-path-cells 10 \
  --require-register-path-limit --out /tmp/scheduler_command_measure
```

`validation.json` 保存参数、通过计数、输入文件 SHA256 和详细报告位置。四态测试只对模块名称作实例隔离，直接编译完整 RTL，并在时钟上升沿前后比较全部公开输出。
