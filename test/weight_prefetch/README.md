# 阵列权重完整装载

生产阵列在每次全局权重提交前完成 `SIZE` 次权重向量装载。`compute_core` 显式选择 `p_exchange_weights=0`，预取寄存器只在装载时更新，活动寄存器在提交时接收预取权重。工作权重和预取权重分别保存，阵列维持 16 行、16 列、完整十六位乘法操作数及三十二位累加结果。

独立 `ws_systolic_cell` 和 `ws_systolic_array` 的 `p_exchange_weights` 默认值为 `1`，支持提交时交换活动权重与预取权重。参数为 `0` 时采用完整装载语义。数据、部分和、有效位和逐行提交的传播周期相同。

## 装载与提交条件

`kernel_loader_buffer` 每次发送包含 `SIZE` 个权重向量，尾部无效行和无效列补零。`weight_sending_done` 与最后一个向量同时产生，`kernel_loader` 将完成信号和向量装载信号分别寄存一个周期。`npu_controller` 收到完成信号后登记预取完成，再产生权重提交。

提交逐行传播，前一输入流与后一输入流可以同时处于不同阵列行。第 `r` 行在下一次提交前接收的最后 `SIZE-r` 次有效移位已覆盖所需预取权重。行加载条件允许提交边沿接收新的预取数据，活动寄存器在该边沿读取更新前的预取值。驻留权重复用保持活动权重，中止或复位后首次提交仍经过完整装载。

## 独立完整阵列综合

两种配置均使用 16×16 阵列、十六位输入、十六位权重和三十二位累加结果，目标器件为 `xc7a200tfbg484-3`。表中为映射后的原语数量和包含 DSP 内部寄存边界的实际连通路径。

| 指标 | 交换权重 | 完整装载 |
| --- | ---: | ---: |
| 逻辑 LUT | 2,593 | 289 |
| 触发器 | 11,807 | 7,711 |
| DSP48E1 | 256 | 256 |
| 块 RAM、分布式 RAM、SRL | 0 | 0 |
| 最长寄存器间组合单元数 | 2 | 1 |

完整装载省去 2,048 个 `LUT6_2` 权重选择单元，活动权重可直接合入 DSP 输入寄存器，另减少 256 个逻辑 LUT 和 4,096 个触发器。完整 SoC 的物理 LUT 数由整机合法布局统计，150 MHz 由目标器件的布局布线时序检查确认。

## 验证范围

`run_formal.py` 将实际阵列、加载缓冲、发送控制及输出寄存器分别纳入证明。

- 阵列大小 3、4、16 的逐行权重证明允许任意输入位、装载间隔和复位。全局提交前至少完成 `SIZE` 次装载；提交也可与下一块的首次装载同拍。所有已提交行的活动权重与交换实现保持相同。
- 实际 `kernel_loader_buffer` 和 `npu_controller` 的组合证明检查每次提交均具有完整装载。初始化边沿保存驻留模式，任务开始时清空缓冲控制或等待前次发送结束；生产 NPU 观察器检查这些入口条件。
- 实际 `kernel_loader_ctrl` 的所有状态均满足发送请求由控制器授权；实际 `kernel_loader` 的装载和完成输出均经过一个寄存周期。
- 默认交换配置完成五种数据、权重及累加位宽下的全部状态和输出比较。官方 `LUT6_2` 四状态模型完成 100,000 个周期、200,001 次输出比较。

`run_array.py` 使用实际权重缓冲及两种完整阵列，同时比较独立整数矩阵乘加参考。四组配置覆盖大小 3、4、16 和八位、十六位权重，包含连续分块、尾部补零、装载间隔、双槽位预取、有效输入重叠、部分装载清空以及运行中复位。共检查 280,237 个输出元素、84,798 个装载权重、4,357,132 个有效计算单元权重，包含 504 次提交和 114 次复位。四组均覆盖全局提交与下一块首次装载同拍。

`run_mapped.py` 使用实际完整阵列综合网表和官方器件原语运行相同的十六位矩阵场景，检查网表的 131,552 个输出元素，同时比较参考 RTL 的 2,147,424 个有效计算单元权重。测试覆盖 151 次提交、41 次复位及提交与下一块首次装载同拍，使用的网表哈希与上述候选综合结果相同。

`run_npu.py` 在生产配置下使用同一份仿真程序完成 86 项任务，共检查 216,348 个 INT32 输出。附加观察器检查所有有效计算单元的实际活动权重与交换实现逐周期一致，并检查完整发送和提交条件。

| 完整 NPU 测试 | 任务数 | INT32 数值检查 |
| --- | ---: | ---: |
| 常规功能、卷积、Dense、精度与恢复 | 38 | 11,118 |
| 生产容量、WS/IS 帧和配置状态 | 21 | 173,642 |
| 输出 FIFO、INT8/INT16 输出与运行中恢复 | 15 | 11,392 |
| 分块布局和帧调度 | 12 | 20,196 |

实际结构检查确认 256 个阵列计算单元、8 个向量 PE、7 个共享物理存储银行及 458,752 位共享 RAM，全部生产缓冲容量保持。

源码哈希、形式证明、数值检查、生产结构和综合结果保存在 [measurement.json](measurement.json)。

## 复现

在仓库根目录执行以下命令，`PYTHONPATH` 指向含 `pyosys` 的工具环境。

```sh
python3 test/weight_prefetch/run_formal.py --out build/weight_prefetch/formal --iverilog iverilog --vvp vvp
python3 test/weight_prefetch/run_array.py --out build/weight_prefetch/array --verilator verilator
python3 test/weight_prefetch/prepare_measurement.py --out build/weight_prefetch/inputs
python3 scripts/fpga/open_fpga_synth.py --case-config build/weight_prefetch/inputs/cases.json --cases reference candidate --out build/weight_prefetch/synthesis --lock-file /tmp/mini_tflm_dsa_synthesis.lock
python3 test/weight_prefetch/run_mapped.py --mapped build/weight_prefetch/synthesis/candidate/mapped.v --out build/weight_prefetch/mapped_numeric --verilator verilator
python3 test/weight_prefetch/run_npu.py --out build/weight_prefetch/npu --verilator verilator --jobs 1 --build-timeout 7200
python3 test/ps_channels/run_npu_structure.py --out build/weight_prefetch/production_structure --verilator verilator
```
