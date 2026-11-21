# 量化运行控制

串行量化保存逐通道配置，运行状态直接使用该配置决定参数请求、分组切换和计算许可。初始化边沿使用当前输入配置。行缓存有效条件与末批位置并行计算，再合并参数许可和初始化条件。

## 验证结果

六组参数完成完整模块等价证明，共比较 54,122 个状态及输出位，覆盖 1、2、4 和 16 个计算通道、32 位和 64 位总线、逐张量及逐通道量化。存储器两侧接收共同的任意读数据，全部读写地址、数据、使能和时钟端口参与比较；小型寄存器数组保留完整存储状态。输入不附加功能约束。

运行许可检查穷举九个控制位的四态组合，在两种逐通道功能配置下完成 524,288 次比较。生产配置数值测试检查 528,384 个元素、16,512 个输出拍和 157 个分组，覆盖清除、复位与 DMA 参数读取。参考和当前实现均为 74,461 个测试周期。

独立综合使用 `VLEN=16`、`BUS_WIDTH=64`、`MAX_IA_REUSE=32`、`p_compute_lanes=2` 和 512 行输入存储。名义 LUT 数为 4,918，参考版本为 4,848；寄存器、DSP 与块存储器数量保持一致。模块内部最长寄存器路径为 8 级。完整 SoC 中初始化信号到量化控制的路径由整机综合检查。

源码散列、检查数量和映射摘要保存在 [validation.json](validation.json)。

## 重复执行

```sh
python3 test/requant_control_selection/prepare_measurement.py \
  --source-root . --out build/requant_control_selection/measurement
python3 test/requant_control_selection/run_formal.py --source-root . \
  --reference-root build/requant_control_selection/measurement/inputs/reference \
  --out build/requant_control_selection/formal
python3 test/requant_control_selection/check_four_state.py --source-root . \
  --reference-root build/requant_control_selection/measurement/inputs/reference \
  --out build/requant_control_selection/four_state
python3 test/requant_time_share/run.py --source-root . --xilinx \
  --lanes 2 --reuse 32 --bus 64 \
  --out build/requant_control_selection/numeric
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_control_selection/measurement/cases.json \
  --cases reference current --rtl-dsp-attributes --wide-alu-dsp-budget 740 \
  --out build/requant_control_selection/measurement/results
```
