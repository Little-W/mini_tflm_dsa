# 串行量化参数读取

WS 参数存储为串行计算提供按当前批次寻址的读取端口。各计算通道直接取得所需的预处理乘数和移位量，原始参数观察端口保持原有行为。写入事件、地址截断、同地址写入顺序和读取周期均保持一致。生产配置使用两个计算通道和两组参数存储，综合工具可将当前批次读取映射为分布式存储。

## 功能验证

八组完整模块等价证明共比较 76,652 个状态及输出位。WS 参数存储保留实际内容及全部读写端口，其余存储两侧接收共同的任意读值，并比较完整驱动端口。全部输入不附加功能限制。参数覆盖 1、2、4、16 个计算通道，32、64、128 位总线，以及逐张量与逐通道模式。

实际 WS 存储逻辑另完成六组四态测试，共 72,000 个周期、144,000 次完整读取结果比较，覆盖参数写入、当前批次选择、部分未知地址与控制，以及非二次幂银行数的通用分支。

生产配置检查 528,384 个元素、16,512 个输出拍和 157 个分组，包含清除、复位、整组存储和 DMA 参数读取。测试周期为 74,461，与参考实现相同。

## 资源测量

测量保留量化模块全部计算和控制接口，将 SoC 未使用的原始参数观察输出保持未连接。参数为 16 个元素、两个计算通道、64 位总线、32 次行复用和 512 行输入存储。

| 项目 | 参考版本 | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 2,683 | 2,462 |
| 分布式存储的名义 LUT | 0 | 64 |
| 移位寄存器的名义 LUT | 24 | 24 |
| 名义 LUT 合计 | 2,707 | 2,550 |
| 触发器 | 2,439 | 1,815 |
| DSP | 25 | 25 |
| RAMB18 | 19 | 19 |
| 最长寄存器间组合级数 | 8 | 8 |

源码、参数和检查结果保存在 [validation.json](validation.json)。完整 SoC 的资源与跨模块路径由整机综合检查。

## 重复执行

```sh
python3 test/requant_parameter_ports/prepare_measurement.py \
  --source-root . --out build/requant_parameter_ports/measurement
python3 test/requant_parameter_ports/run_formal.py --source-root . \
  --reference-root build/requant_parameter_ports/measurement/inputs/reference \
  --out build/requant_parameter_ports/formal
python3 test/requant_parameter_ports/check_four_state.py --source-root . \
  --reference-root build/requant_parameter_ports/measurement/inputs/reference \
  --out build/requant_parameter_ports/four_state
python3 test/requant_time_share/run.py --source-root . --xilinx \
  --lanes 2 --reuse 32 --bus 64 --out build/requant_parameter_ports/numeric
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_parameter_ports/measurement/cases.json \
  --cases reference current --rtl-dsp-attributes --wide-alu-dsp-budget 740 \
  --out build/requant_parameter_ports/measurement/results
```
