# 写回索引与 FIFO 银行选择

## 实现

`oa_writer` 并行计算最后一个有效行、列的索引。行列模式和末尾数据块条件随后选择已有索引，索引为零时仍保留饱和减一的行为。准备下一组行数时，剩余行数和容量上限分别计算五位行分块数量，完整位宽的范围比较选择相应结果。九位行数截断和五位分块数回绕与原表达式一致。

`vec_s8_to_fifo_full` 在继续输出时，直接根据当前拍是否为行末选择当前银行或后续银行的就绪标志。组启动要求 `!co_active`，继续输出要求 `co_active`，两者互斥。首拍启动继续使用原有银行选择；继续输出的读取使能和数据有效状态使用独立的就绪条件。

上述调整均为组合运算重排。配置捕获、DMA 命令、有效数据、存储读写、反压、完成和复位周期保持一致。

## 资源与组合路径

联合测量实例化生产 `oa_writer` 和实际 32 个存储体的循环 INT8 FIFO，保留全部公开输出，参数为 `VLEN=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=28`。参考提交为 `2407d9d6`，两个版本使用相同的 Xilinx 7 系列综合配置。

| 项目 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT 原语 | 2,955 | 2,944 |
| 触发器 | 1,051 | 1,051 |
| RAMB18E1 | 8 | 8 |
| DSP48E1 | 0 | 0 |
| 联合模块最长寄存器间组合路径 | 18 级 | 14 级 |
| `cfg_is_mode` 至下一有效列索引 | 18 级 | 14 级 |
| `cfg_is_mode` 至下一有效行索引 | 18 级 | 14 级 |
| 下一行组起点至行分块数 | 16 级 | 14 级 |
| `write_oa_granted` 至 `co_data_valid` | 9 级 | 5 级 |
| `start_permitted` 至 `co_data_valid` | 7 级 | 3 级 |

最后两项在综合后的输入端口建立分析起点，以测量该端口至实际数据有效寄存器的组合部分。资源统计取自原始综合网表。完整 SoC 的物理 LUT 数和工作频率由其独立布局与时序结果给出。

## 验证范围

- 写回控制完成七组参数的时序归纳，比较 64 个原有寄存状态和全部公开输出，并检查行分块寄存结果的关系。首个边沿复位，后续输入不受约束。向量长度覆盖 4、8、16、32，总线覆盖 32、64 位，计数宽度覆盖 8、16、28、32 位。
- FIFO 完成七组参数的等价检查，共比较 10,486 位，覆盖全部公开输出、寄存状态及存储端口。配置包括 3、8、16、32 个存储体、32 位和 64 位总线、循环与普通布局，以及通用和 FPGA 实现。存储读数据和外部输入不受取值限制；实际存储实现保持相同。FPGA 分支使用工具提供的 `LUT6_2` 功能模型。
- 四组实际写回控制测试共通过 1,024 个场景、568,789 个周期，逐周期比较全部 21 个公开输出，覆盖 17,667 个 DMA 命令、3,439 个合并组、501 次完成和 390 次运行中断。
- 实际 FPGA FIFO 使用 16、32 个存储体与 BUS32、BUS64 的四种组合，每种通过 81 个用例和 12,392 个输出字节，合计 324 个用例、49,568 个字节。公开输出的数据和周期均一致。

`measurement.json` 保存生产源码、参考源码、形式验证结果、仿真程序和综合网表的 SHA-256，以及每项路径的起止信号。验证和测量使用相同的两份生产 RTL。

## 运行方法

需要安装 Pyosys 和 Verilator，并将相应可执行文件加入环境。

```sh
python3 test/oa_fifo_timing/run_formal.py \
  --reference 2407d9d6 --out build/oa_fifo_selection/formal_writer
python3 test/fifo_byte_rotation/run_formal.py \
  --reference 2407d9d6 --out build/oa_fifo_selection/formal_fifo
python3 test/oa_writer/run_equivalence.py --reference 2407d9d6 \
  --out build/oa_fifo_selection/numeric_writer --verilator verilator-modern \
  --profiles 4:32:8 16:32:28 16:64:28 32:64:32 --scenarios 256 --cycles 1024

for banks in 16 32; do
  for bus in 32 64; do
    python3 test/writeback_cyclic/run.py --reference-rev 2407d9d6 \
      --out build/oa_fifo_selection/numeric_n${banks}_b${bus} \
      --banks ${banks} --bus-width ${bus} --fpga --verilator verilator-modern
  done
done

python3 test/oa_fifo_timing/prepare_measurement.py \
  --reference 2407d9d6 --out build/oa_fifo_selection/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/oa_fifo_selection/inputs/cases.json \
  --cases reference current --out build/oa_fifo_selection/synthesis
python3 test/oa_fifo_selection/measure_paths.py \
  --reference build/oa_fifo_selection/synthesis/reference \
  --current build/oa_fifo_selection/synthesis/current \
  --out build/oa_fifo_selection/target_paths.json
```
