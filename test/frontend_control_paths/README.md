# 卷积前端控制与算术路径

前端将输出接收、行与通道组范围、数据字选择及地址选择拆分为独立模块。
每个来源先完成自身资格计算，运行阶段选择已经准备的结果。
描述符的坐标与像素加法分别计算高低两个部分，再按组修正输入进位；
卷积核末位置直接比较当前位置、步长与末位置，减少串联计算。
历史行位置与译码目标采用分组比较，保持完整位宽和原有状态更新周期。

## 实际测量

完整 `axi_dual_block_dma` 使用 16 行阵列、64 位总线、每拍 8 个窗口样本、
128 字节缓存行、16 组双路缓存和深度为 2 的缓存响应。
测量包含坐标与状态选择模块的配套修改。

| 项目 | 参照版本 | 当前结构 |
|---|---:|---:|
| 逻辑 LUT | 14198 | 14202 |
| LUTRAM | 224 | 224 |
| DSP | 68 | 71 |
| 触发器 | 7688 | 7688 |
| 最长组合路径 | 13 | 12 |

当前结构中，坐标到运行状态、组范围到地址、输入配置到组范围以及
已输出通道数到描述符的最长路径均为 10 级；组范围到保存字匹配为 9 级。
输入格式到运行状态和部分完整地址算术仍为 12 级。
结构检查包含寄存器之间的完整组合连接；150 MHz 的实现结果由目标器件时序分析确认。

`measurement.json` 保存完整映射参数、源文件 SHA256、ABC 等价检查和路径结果。
状态模块采用打包联合体提供同一组状态位的枚举与位向量表示，
其通用与综合编译模式的证明见 `../frontend_state_selection/enum_validation.json`。

## 功能检查

完整流式模块的 5 种参数配置通过时序归纳证明，描述符提交模块的
4 种配置通过完整输出与保存状态等价证明。
控制事件、分组范围、历史行递增、数据字选择和描述符算术分别通过
任意输入证明及四态比较，详细结果保存在 `results/`。
通用形式编译显式使用 `-USYNTHESIS -UXILINX_FPGA`，各综合配置显式定义相应宏。
完整模块比较在两份设计中清理无消费者的内部别名，再检查全部公开输出和保存状态。
`compilation_validation.json` 保存各编译条件和检查结果。

相同输入、缓存响应深度和运行参数下，42 项数值事务全部通过，
总计 178417 周期。两份电路的 128 条事务、队列和快路径统计逐项一致，
周期差为 0。输入文件保存在 `vectors.txt`，完整比较保存在 `results/numeric.json`。

以下命令检查实际 RTL 及其依赖：

```sh
python3 test/frontend_arithmetic/check_stream.py --out build/frontend_control_paths/stream
python3 test/frontend_arithmetic/check_descriptor_add.py --out build/frontend_control_paths/add
python3 test/frontend_arithmetic/check_descriptor_ready.py --out build/frontend_control_paths/ready
python3 test/frontend_arithmetic/check_kernel_step.py --out build/frontend_control_paths/kernel
python3 test/frontend_arithmetic/check_chunk_end.py --out build/frontend_control_paths/chunk
python3 test/frontend_arithmetic/check_group_end.py --out build/frontend_control_paths/group_end
python3 test/frontend_arithmetic/check_group_value.py \
  --source rtl/npu/conv/conv_stream_group_value.sv --out build/frontend_control_paths/group_value
python3 test/frontend_arithmetic/check_range_after.py --out build/frontend_control_paths/range
python3 test/frontend_arithmetic/check_transfer_accept.py --out build/frontend_control_paths/transfer
python3 test/frontend_arithmetic/check_history_increment.py --out build/frontend_control_paths/history
python3 test/frontend_arithmetic/check_word_selection.py --out build/frontend_control_paths/word
```

27 个相关 RTL 文件各自只定义一个同名模块，最长文件为 1499 行。
所有模块头及端口均有中文功能注释，使用普通可综合 RTL 描述运算和存储。
