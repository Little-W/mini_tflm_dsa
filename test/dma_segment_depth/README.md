# DMA 分段地址与写末拍计算

读取方向分别准备物理突发限制后的地址和页边界限制后的地址，最后由页限制条件选择结果。地址计算与拍数选择并行执行；未按总线字边界对齐时，保留低位字节偏移和原有整数拍数计算。

写入方向直接计算剩余末拍编号，并行比较页限制和物理突发限制。命令与数据通道分别使用相同结构，保留零剩余拍数时九位减一的回绕结果。RTL 使用显式信号、生成循环与中文注释，所有寄存阶段、公开握手和完成周期保持一致。

## 完整模块资源与路径

参考提交为 `6aeb32c`，其中 DMA RTL 与固定整机提交 `6fa49f2` 相同。独立综合配置为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`RD_CONTEXT_DEPTH=4`、`CACHE_BLOCKS=4` 和 256 拍物理突发上限。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,649 | 1,625 |
| 分布式 RAM LUT | 60 | 60 |
| 触发器 | 722 | 721 |
| CARRY4 | 178 | 167 |
| DSP48E1 | 1 | 1 |
| RAMB18 / RAMB36 | 0 / 0 | 0 / 0 |
| 完整模块最长寄存器间组合单元数 | 16 | 15 |
| 读取状态终点的最长组合单元数 | 16 | 15 |
| 写入状态终点的最长组合单元数 | 16 | 14 |

实际路径包含 DSP 内部寄存边界之间的算术，完整连接图分析已通过。整合后仍需重新测量完整 SoC 的跨模块组合路径和资源。

## 已完成验证

11 组完整状态与公开输出比较全部通过，共 58,341 个比较点。外部输入保持自由，覆盖 32、64、128、1,024 位总线，8、16、32 位数据，1、2、3、4 个描述符，16、17、32 位地址，以及单拍、32 拍和 256 拍上限。生产配置的 `SIZE=64`、`CACHE_BLOCKS=64` 包含在验证中。

BUS32/64 描述符检查共完成 752 个命令、282,596 次数据比较和 75,836 个周期。每项命令、数据节拍、等待、错误、同时接收与完成以及周期统计均与参考实现相同。4 KiB 读取检查完成 1,324 个命令和 449,248 次数据比较；写入检查在一项及四项在途请求下完成 1,680 个命令，检查 3,123,136 个写入字节。

中止检查通过 14 种情况，包含 65 次写地址接收和 3,266 个写数据节拍，四个编译单元启用未定义行为检查。公开配置检查完成 12 组运行和 1,908 次断言，直接观察实际命令与数据通道的末拍选择结果。形式、综合与仿真的 RTL SHA-256 均为 `c1147a9b4cd72151c376821e4f46f82daa214e1822c7ae672523f61bd7a48499`。

完整参数、逐单元路径、源码摘要和各次运行结果见 [measurement.json](measurement.json)。

## 复现命令

先按仓库的工具说明配置 Yosys、Slang 和 `verilator-modern`，在仓库根目录顺序执行：

```sh
python3 test/dma_byte_layout/run_formal.py \
  --reference-ref 6aeb32c --out build/dma_segment_depth_state_formal \
  --address-parameters --context-parameters --production-parameters
python3 test/dma_byte_layout/synthesis.py \
  --reference-ref 6aeb32c --out build/dma_segment_depth_reference_synth
python3 test/dma_byte_layout/synthesis.py --out build/dma_segment_depth_final_synth
python3 test/dma_segment_depth/measure_paths.py \
  --reference build/dma_segment_depth_reference_synth \
  --current build/dma_segment_depth_final_synth --out build/dma_segment_depth_paths.json
for bus in 32 64; do
  python3 test/linear_dma_context/run.py --bus-width "$bus" \
    --verilator verilator-modern --out "build/dma_segment_depth_context${bus}_final"
  python3 test/linear_dma_4k/run.py --bus-width "$bus" \
    --verilator verilator-modern --out "build/dma_segment_depth_read${bus}"
  python3 test/linear_dma_write_4k/run.py --bus-width "$bus" --jobs 1 \
    --verilator verilator-modern --out "build/dma_segment_depth_write${bus}"
done
python3 test/run_cpp_rtl.py dma_abort \
  --verilator verilator-modern --out build/dma_segment_depth_abort
python3 test/performance_analysis/validate_configuration_bounds.py \
  --verilator verilator-modern --jobs 1 --out build/dma_segment_depth_configuration
```
