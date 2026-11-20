# 向量输出偏移的三层并行前缀

`vector_engine.sv` 将32位低位加法划分为16个二位分段。每段先计算进位生成和传播条件，随后按距离1、3、9合并相邻区间，形成三层并行前缀。各段最后并行形成两个结果位。

两个区间的进位关系使用双输出LUT同时计算生成条件和传播条件。三个区间的生成关系只依赖五个输入，可以通过一级LUT完成；传播条件同时计算。每个最终前缀完整覆盖第0段至当前段，保留32位加法进位。

高32位的范围关系与低位有符号比较并行计算。FPGA分支使用固定LUT完成符号范围选择和上下限条件合并，通用分支使用相同布尔关系。完整64位回绕、下限优先级、状态寄存器和接口周期保持一致。

## 功能验证

参考提交为 `b20921b3b1fc3351b1f6447dd688af12ac60ef19`。本目录记录独立向量修改的验证结果，全部源码摘要及程序摘要保存在 `measurement.json`。

- 生产源码中的全部偏移和限幅表达式直接用于形式证明，表达式之外的向量源码与参考提交相同。
- 任意64位舍入值、32位偏移和两个32位上下限，共160位相关输入，不增加取值限制。
- 两个限幅条件及完整32位结果共34位输出与参考实现相同；完整32位结果同时与原始有符号64位加法和限幅表达式相同。
- 通用实现及官方 `LUT6_2` 模型分别通过证明。
- 实际向量模块、DMA与缓存采用 `TILE=16`、`PE_COUNT=8`、64位总线、128个缓存集合和缓存策略3。592个任务、168,601个输出数值检查全部通过，共2,979,488个任务执行周期。

## 映射结果

| 独立算术模块 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT | 176 | 176 |
| 最长寄存器间组合路径 | 11级 | 10级 |

完整向量模块使用相同生产参数和相同Xilinx原生映射流程，包含结果选择与存储写入。

| 完整向量模块 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT原语 | 10,916 | 10,860 |
| 分布式存储LUT | 248 | 248 |
| 触发器 | 6,029 | 6,029 |
| DSP48E1 | 17 | 17 |
| CARRY4 | 675 | 675 |
| 完整模块最长路径 | 15级 | 15级 |
| 输出偏移第10位至结果存储 | 14级 | 13级 |
| 舍入值至结果存储 | 14级 | 13级 |
| 全部输出偏移位至结果存储 | 14级 | 15级 |

全部偏移位的最长路径经过ADD结果选择。上述数据为相应隔离源码的映射结果，整机物理位置和全部跨模块路径由完整SoC测量给出。

## 运行

在对应源码提交和已准备的开源工具环境中执行：

```sh
python3 test/vector_offset_clamp/run.py --reference b20921b3 \
  --out build/vector_r22_offset/formal_radix3
python3 test/vector_offset_clamp/synthesis.py --reference b20921b3 \
  --out build/vector_r22_offset/local_radix3
python3 test/vector_input_banks/prepare_measurement.py --reference b20921b3 \
  --out build/vector_r22_offset/full
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/vector_r22_offset/full/cases.json \
  --cases vector_reference vector_current --out build/vector_r22_offset/full/synthesis
python3 test/vector_offset_clamp/paths.py \
  --reference build/vector_r22_offset/full/synthesis/vector_reference \
  --current build/vector_r22_offset/full/synthesis/vector_current \
  --proof build/vector_r22_offset/formal_radix3/summary.json \
  --out build/vector_r22_offset/full_paths.json
python3 test/vector_engine/run.py --xilinx --bus-width 64 --pes 8 --jobs 1 \
  --verilator verilator-modern --out build/vector_r22_offset/fpga64
python3 test/vector_offset_prefix3/collect.py --build build/vector_r22_offset \
  --out test/vector_offset_prefix3/measurement.json
```
