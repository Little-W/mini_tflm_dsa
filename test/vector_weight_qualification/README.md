# 向量权重读写资格

## 结构

`state_dw_execute` 与 `state_weight_read_phase` 和状态字共同保存。前者表示 `DW_EXECUTE`，后者表示 `OUTPUT_INIT`、`DW_EXECUTE` 或 `DW_FINISH`。全部 89 处状态更新同时维护这些标志；核位置推进、计算发射和共享权重读使能直接使用相应的寄存结果。

`active_lane_mask` 与有效通道数 `active` 在复位、空间块初始化、向量初始化和向量分块推进时共同更新。每个掩码位表示对应通道下标小于 `active`。权重写入、量化请求、累加提交和极值池化结果选择使用同一组资格。

权重写入按总线字归并。每组总线字共用一个列地址比较，各字节先结合返回有效位与通道资格，再合并该组的非空结果。最终写入资格并行选择各组结果。列地址比较采用完整三十二位算术，未知位按同一个 RTL 表达式传播。地址、数据、掩码和写入阶段仍在原有时钟边沿保存。

生产实例净增加 17 个触发器。请求接受、响应接收、计算发射和写入提交的周期顺序保持相同。

## 验证

| 检查 | 覆盖与结果 |
| --- | --- |
| 状态控制字 | 全部 89 处更新核对，4 项 SAT 检查，4,096 种四态状态编码 |
| 排空条件 | 两种共享配置，131,072 次四态比较 |
| 有效通道掩码 | 4 处更新核对，6 组参数的实际源码一步归纳证明，393,222 次四态比较 |
| 权重字节选择与非空归并 | 8 组参数的全部二值输入证明，320,000 次四态比较 |
| 末项状态与预取地址 | 6 组实际源码一步归纳证明，9 种位宽共 216,009 次四态比较 |
| 生产参数数值回归 | 616 项任务，170,743 个输出 |
| 通用参数数值回归 | 616 项任务，170,743 个输出 |
| 生产参数固定等待测试 | 40 项任务，103,743 个输出 |

有效通道证明保留实际 RTL 中的 `active` 与 `active_lane_mask` 寄存器，其余状态和存储输出作为自由输入。仅第一个采样周期要求复位，后续复位、操作模式和控制输入均自由。参数包含 1、3、8、16 个 PE，4、7、16、32、64 个通道，以及生产共享存储和通用共享量化配置。

组合权重检查使用已经证明的逐通道关系，并比较每个写入掩码位及最终接收资格。列地址、有效通道数、返回有效位与写使能均保持自由。参数覆盖 1 至 64 个通道、1 至 16 个总线字节和 1 至 32 位列地址。

生产配置使用 `TILE=16`、`PE_COUNT=8`、64 位总线、8 路窗口、7 个共享存储银行和独立向量量化。通用配置使用 16 个 PE、32 位总线、4 路窗口、私有存储和共享量化。测试覆盖输入暂停、无效坐标、跨核位置预取、128 位权重内容与地址、任务切换、错误恢复、末拍、背压以及请求和响应交叠。

三组数值测试的逐案例全部统计与参考版本相同。生产、通用和固定等待任务的周期总数分别为 3,423,269、3,995,791 和 1,071,159。

## 生产参数映射

| 项目 | 数量 |
| --- | ---: |
| 逻辑 LUT | 10,399 |
| LUT RAM 的名义 LUT 数 | 176 |
| 名义 LUT 合计 | 10,575 |
| 触发器 | 6,437 |
| DSP | 81 |
| RAMB18 | 9 |
| 完整寄存器连接图最大组合级数 | 10 |
| 寄存器到权重读取使能 | 1 |
| 寄存器到权重读取地址 | 2 |
| 输入接口到权重写入暂存 | 8 |

与窗口控制版本相比，名义 LUT 和 DSP 数量相同，触发器净增加 17 个；权重读取使能路径由 4 级降至 1 级，输入接口到权重写入暂存由 11 级降至 8 级。这里统计独立向量实例，完整 SoC 报告继续检查外围控制与共享存储连接。器件频率由布局布线后的时序报告确定。

## 复现

```sh
mkdir -p /tmp/vector_weight_reference
git archive a9c827def8c3e3c0a58965d42fc2a0f9aaec30c0 rtl include | tar -x -C /tmp/vector_weight_reference
python test/vector_weight_qualification/run_active.py --source-root . --reference-root /tmp/vector_weight_reference --tool-root . --out /tmp/vector_weight_active
python test/vector_weight_qualification/run_mask.py --source-root . --reference-root /tmp/vector_weight_reference --tool-root . --out /tmp/vector_weight_mask
python test/vector_control_flags/run.py --source-root . --out /tmp/vector_weight_state
python test/vector_request_boundary/run_formal.py --source-root . --out /tmp/vector_weight_tap
```

数值回归使用 [请求与预取检查](../vector_request_boundary/README.md) 中的生产和通用命令。独立综合使用 `test/vector_engine/production_synthesis_cases.json` 的 `vector` 项，并指定 `--rtl-dsp-attributes` 和 `--wide-alu-dsp-budget 740`。

`validation.json` 保存准确的 RTL、依赖源码、验证程序、结果文件与映射校验值。`run_mask.py` 核对除已证明的状态、通道掩码及权重归并之外的源码逐项相同；既有末项证明通过 `engine_transform.json` 继续检查完整实际时序逻辑。
