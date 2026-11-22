# 帧调度候选存在性状态

`candidate_exists` 与帧目录在相同的时钟边沿更新，表示 `live & frame_open` 中是否存在有效帧。命令完成时，先按当前执行帧、结束标志和开放范围计算目录的后继值，再保存存在性。复位、配置开始和帧组结束清除该位。`SWEEPING` 阶段直接使用保存的资格判断当前帧组是否完成，命令接收与完成周期保持一致。

## 完成的检查

参考源来自 `9d75f75a`。五组完整状态参数按 `SIZE:FRAME_COUNT:MAX_REUSE_TILES` 分别为 `4:4:4`、`16:16:32`、`4:2:0`、`8:4:1`、`16:8:16`。全部 7,987 个公共寄存器状态位、公开输出和一步状态转移均已完成证明；每组仅新增一个保存存在性的 RTL 状态位。外部输入不作限制。

新增状态关系 `candidate_exists == |(live & frame_open)` 完成复位检查及一步无界归纳。除上述五组外，另检查 `4:3:4` 和 `16:17:32`，共七组参数。

实际完整模块在 `4:4:4` 与 `16:16:32` 下分别执行 FPGA 和 ASIC 两种模式的四态逐周期比较。检查全部公开输出以及保存关系，共 348,248 次输出比较、114,496 个四态输入周期，覆盖命令接收、压力、完成、配置和复位。

独立命令功能检查通过 975 项用例、182,426 条命令，包含分片、帧编号复用、尾帧、压力恢复、存储预留和非法配置。功能测试采用 `SIZE=16, FRAME_COUNT=16, MAX_REUSE_TILES=0` 与 `XILINX_FPGA` 分支，并启用未定义行为检查。

## 资源与路径

生产参数独立完整模块测量结果如下。统计包含实际逻辑 LUT 与分布式 RAM 的 nominal LUT 数量。

| 项目 | 参考版本 | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,134 | 1,161 |
| 分布式 RAM LUT | 56 | 56 |
| nominal LUT | 1,190 | 1,217 |
| 触发器 | 915 | 917 |
| DSP | 13 | 13 |
| RAMB36 | 2 | 2 |
| 最长寄存器间组合路径 | 9 | 9 |

参考版本 `live` 到 `phase`、`ready`、`resume_valid` 与 `cursor_mask` 的最长组合路径为 8 级。当前版本通过保存的存在性状态控制这些寄存器，`live` 到这些终点的组合依赖已消除；保存位到控制寄存器最多 5 级，进入保存位的数据路径最多 8 级。两份映射图完整，整机连接后的路径由完整 SoC 测量确定。

## 重复执行

```bash
python3 test/scheduler_candidate_exists/run_formal.py --source-root . --reference 9d75f75a --out build/scheduler_candidate_exists/formal
python3 test/scheduler_candidate_exists/prove_invariant.py --source-root . --profiles 4:4:4 16:16:32 4:2:0 8:4:1 16:8:16 4:3:4 16:17:32 --out build/scheduler_candidate_exists/invariant
python3 test/scheduler_candidate_exists/run_four_state.py --source-root . --reference-root build/scheduler_candidate_exists/formal/reference --profiles 4:4:4 16:16:32 --out build/scheduler_candidate_exists/four_state
python3 test/ps_compression/run_window_scheduler.py --source-root . --fpga --out build/scheduler_candidate_exists/numeric
python3 scripts/fpga/open_fpga_synth.py --source-root . --case-config test/scheduler_candidate_exists/synthesis_cases.json --cases scheduler --out build/scheduler_candidate_exists/synthesis --wide-alu-dsp-budget 740 --rtl-dsp-attributes --max-register-path-cells 10
```

`validation.json` 记录通过范围、数量、源码散列及原报告路径与散列。证明、仿真和综合中间文件保存在指定输出目录。
