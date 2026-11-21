# 帧调度器配置检查

帧调度器并行检查维度零值、复用上界、窗口上界和切片范围。三个宽比较通过 `unsigned_compare` 表达完整无符号关系，FPGA 配置允许综合工具推断行为级算术资源。状态更新合并独立的一位检查结果。

正常命令准备、非法配置通知、命令顺序、背压和完成通知的周期均保持不变。参数 `MAX_REUSE_TILES=0` 继续保留通用配置，非零参数继续检查完整输入上界和移位溢出。

## 资源与验证

生产独立综合参数为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`。

| 项目 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,258 | 1,234 |
| DSP | 10 | 13 |
| 最长寄存器间组合路径 | 9 | 9 |

完整连接图的独立测量保留全部寄存器间路径。附加注册输入的独立测量也得到 9 级，整机控制路径在对应整机综合中统计。

完整状态证明覆盖六组 FPGA 参数和两组 ASIC 参数，共 26,415 位。参数包括 `SIZE=4/8/16`、`FRAME_COUNT=2/4/8/16`、`MAX_REUSE_TILES=0/1/16/32`。证明输入不受限制，全部状态和输出按周期比较。

四态检查从当前 RTL 提取实际比较与条件，针对六组参数分别运行 FPGA 和 ASIC 两种算术配置，共完成 648,276 次检查。测试包含有效配置、零值、上界及上界加一，并在有效配置的每个输入位置注入未知值和高阻态。

## 运行

四态检查从仓库根目录执行：

```sh
python3 test/scheduler_config_timing/run_four_state.py
```

完整状态证明复用 `test/kernel_issue_timing/run_formal.py`。先将参考提交的 `rtl/common` 和 `rtl/npu/control/ps_window_scheduler.sv` 提取到独立目录，再执行：

```sh
python3 test/kernel_issue_timing/run_formal.py --module ps_window_scheduler --reference-root build/scheduler_config_reference --profiles 4:2:0 8:4:1 16:8:16 16:16:16 16:16:0 16:16:32 --fpga --out build/scheduler_config_timing/formal_fpga
python3 test/kernel_issue_timing/run_formal.py --module ps_window_scheduler --reference-root build/scheduler_config_reference --profiles 4:2:0 16:16:32 --out build/scheduler_config_timing/formal_asic
```

参考提交为 `0097b66ed57e1b8ef00e402e89dc5b274f1626be`。`validation.json` 保存精确参数、源码散列、资源结果和验证汇总。
