# 前端定宽算术检查

## 地址推进

`conv_geometry_movement_add` 将 32 位地址与位移分成两个 16 位部分并行求和。高位结果按组并行结合低位进位，保持完整模加法结果和原有更新周期。

```sh
python3 test/frontend_arithmetic/check_movement.py \
  --out build/frontend_arithmetic/movement
```

检查从生产几何模块提取五路地址推进语句，覆盖全部输入组合的两组 SAT 证明，以及 31138 个四态样本。四态样本逐位注入 X 和 Z，包含普通步进和换行步进的选择输入。

`movement_measurement.json` 保存测试结果及映射配置。输入和输出全部寄存的小模块使用 23 个 LUT 和 1 个 DSP，最长组合路径为 4 级；参照实现为 6 级，资源数量相同。实际生产参数的完整 DMA 均为 14887 个逻辑 LUT 和 24 个 DSP。前端 42 项数值与事务测试通过，总周期为 145444。

## 预取准备加法

`conv_im2col_prefetch` 的三个准备加法和两个横坐标加法采用相同的分段计算结构，继续在原有准备周期保存结果。

```sh
python3 test/frontend_arithmetic/check_prefetch.py \
  --out build/frontend_arithmetic/prefetch
```

两组 SAT 证明直接比较生产语句与参照模块的五路完整结果，不限制输入值。20962 个四态样本逐位覆盖 X 和 Z。42 项前端数值、事务和 lint 检查通过，总周期保持 145444。

`prefetch_measurement.json` 保存详细结果。完整 DMA 的逻辑 LUT 从 14887 减至 14792，减少 95 个；DSP 从 24 增至 28，触发器数量保持 7590。

## 描述符提交加法

`conv_descriptor_add` 计算完整的坐标与像素和值。十六位低段形成进位，高段同时准备两种进位输入的结果，提交阶段直接选择相应结果。

```sh
python3 test/frontend_arithmetic/run.py \
  --out build/frontend_arithmetic/coordinate
```

检查包括 12 组不同位宽和综合模式的算术 SAT 证明、5 组完整描述符提交模块的 SAT 证明及 21512 个四态样本，均不限制输入值。42 项前端数值、事务和 lint 检查通过，总周期保持 145444。

`coordinate_measurement.json` 保存详细结果。配置寄存器到输入坐标寄存器的最长组合路径由 13 级减至 10 级。完整 DMA 使用 14901 个逻辑 LUT，比预取加法优化后的版本增加 109 个；DSP 保持 28 个，触发器保持 7590 个。

## 保存字地址比较

`conv_descriptor_match` 支持保存三位比较组的结果。流式输出的下一卷积核地址使用分组模式检查已保存数据字，其余调用保持完整字段比较。

```sh
python3 test/frontend_arithmetic/check_word_match.py \
  --out build/frontend_arithmetic/word_match
```

11 种位宽的无约束 SAT 检查同时验证两种比较模式，18892 个四态样本覆盖逐位 X 和 Z。42 项前端数值、事务和 lint 检查通过，总周期保持 145444。

`word_match_measurement.json` 保存详细结果。回绕状态到保存字命中寄存器的最长组合路径由 12 级减至 10 级，完整 DMA 减少 17 个逻辑 LUT，DSP 和触发器数量保持不变。

## 范围计算与窗口目标准备

`conv_im2col_group_ranges` 独立计算配置、译码和流式推进的通道范围。高位关系、低位逐通道范围、译码选择和数据选择分别由小模块完成。比较组及数据归并组保留各自的组合边界，运行状态直接选择已经完成的候选结果。流式模块保持原有提交和输出周期。

`conv_descriptor_window_target` 在现有窗口准备边沿保存三个完整目标归约序号。后续描述符以分组相等比较确定目标命中，窗口有效位随配置更新清除。三个准备加法采用可推断的分段普通算术，共增加三个 DSP。`conv_descriptor_address_add` 对提交地址使用十六位进位选择，并保留四态分组加法的逐位传播。

以下检查直接读取生产模块及其依赖：

```sh
python3 test/frontend_arithmetic/run.py --out build/frontend_arithmetic/commit
python3 test/frontend_arithmetic/check_ranges.py --out build/frontend_arithmetic/ranges
python3 test/frontend_arithmetic/check_word_steps.py --out build/frontend_arithmetic/word_steps
python3 test/frontend_arithmetic/check_active_columns.py --out build/frontend_arithmetic/active
python3 test/frontend_arithmetic/check_geometry_positions.py --out build/frontend_arithmetic/positions
python3 test/frontend_arithmetic/check_stream.py --out build/frontend_arithmetic/stream
python3 test/frontend_arithmetic/check_window_targets.py --out build/frontend_arithmetic/targets
```

完整组合包括 46 项组合逻辑 SAT 证明、7 项时序归纳证明和 200396 个四态样本。窗口目标证明包含配置更新、窗口覆盖写入和有效位更新，比较完整三十三位结果；其余组合检查不限制输入数据。完整流式证明覆盖 4、8、16 通道、直接描述符及准备描述符两种配置，并包含综合与通用编译模式。

42 项前端连续数值与事务检查通过，总周期为 178417。配置、请求、快路径及输出统计共 128 行，与相同输入、参数及缓存响应深度的参照结果逐项一致。检查未出现位宽、锁存器、多重驱动或组合循环诊断。

`frontend_partition_measurement.json` 保存完整参数、源码摘要、验证结果及映射结果。相同缓存响应深度为 2、每拍 8 个样本、64 位总线、4096 字节缓存配置下，完整 DMA 的逻辑 LUT 从 14834 增至 15075，DSP 从 28 增至 31，触发器从 7588 增至 7686。最长组合路径从 14 级减至 13 级；配置寄存器到组范围的最长路径从 14 级减至 10 级，输入忙信号到准备描述符从 12 级减至 11 级，归约长度到有效通道范围仍为 12 级。剩余路径继续由整机测量定位。结构级数记录组合单元数量，150 MHz 实现结果由目标器件的时序分析确认。


## 流式输出接收资格

前端在输出握手和描述符状态条件确定后提供 `stream_operation_accept`。
流式模块共用该事件更新通道范围、地址和有效列数，确定输入保持原有周期，
含未知值的输入保留完整提交条件的四态传播。

`check_stream_accept.py` 从实际前端、描述符和流式模块提取接收与提交语句，
验证任意状态位和输入值下的逻辑关系，并执行 2146 个四态样本。
`check_stream.py` 验证 5 种参数配置的全部公开输出和保存状态。
42 项连续事务测试总计 178417 周期，与相同配置参照的 128 条事务统计完全一致。

完整 DMA 使用描述符与行地址准备寄存器、8 通道窗口、64 位总线和深度为 2 的缓存响应。
同一映射配置的逻辑 LUT 从 15075 减至 15044，DSP 保持 31，最长组合路径为 13 级。
`WAIT_WORD` 到运行地址和保存字匹配寄存器的最长路径均为 12 级。
完整数据及源码摘要保存在 `stream_accept_measurement.json`。


## 描述符通道组步长

`conv_descriptor_group_steps` 同时计算一个和两个通道组之后的三十三位归约位置。
两种步长共享高十六位的递增结果，低十七位采用普通加法并由综合工具推断算术资源。
含未知输入时保持各自分组加法的逐位传播。

`check_group_steps.py` 从参照提交提取两项完整计算，分别在通用与综合模式下执行
全部输入形式证明和四态测试，共 2 项证明、6340 个样本。
42 项连续前端事务保持 178417 周期，128 条事务统计与相同配置参照一致。
完整 DMA 的逻辑 LUT 从 15044 减至 15010，DSP 从 31 增至 32，寄存器保持 7687。
源码摘要和测量数据保存在 `group_steps_measurement.json`。


## 输出推进后的范围

`conv_stream_range_after` 分别准备缓存数据输出和补零输出的剩余范围，
输出阶段只选择已完成的一位结果。未知输出阶段使用完整逐通道表达式。

`check_range_after.py` 验证 1、4、8、16、33 通道的全部输入，
共 5 项形式证明和 13162 个四态样本。完整流式模块的 5 种配置通过时序归纳证明。
42 项连续事务保持 178417 周期，128 条事务统计与同一配置参照一致。

加入通道组步长共享计算后，完整 DMA 的逻辑 LUT 为 15030，DSP 为 32，寄存器为 7687。
`WAIT_WORD` 到运行地址的最长路径为 10 级，到保存字匹配寄存器为 11 级；
完整 DMA 的最长组合路径仍为 13 级。源码摘要与完整测量数据保存在 `range_after_measurement.json`。
