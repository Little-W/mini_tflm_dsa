# DMA 描述符的 regfile 存储

`axi_linear_block_dma` 将描述符数据保存到 `regfile`，标签使用独立的同步复位寄存器。数据阵列提供两个异步读取端口，分别读取当前描述符和下一描述符的起始地址。写入使能为复位有效且命令被接收，数据与标签在同一个采样边沿更新。

当前描述符数量、接收条件、指针回绕、响应顺序、错误归属和全部公开输出周期保持一致。存储器不设置物理资源属性，由综合工具根据容量与端口自行选择实现。

## 资源与组合路径

独立综合使用 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=4`、`RD_CONTEXT_DEPTH=4`，参考提交为 `4448177`。两份实现均使用相同的七系列综合流程。

| 项目 | 参考实现 | regfile 实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,731 | 1,642 |
| 分布式 RAM LUT | 0 | 60 |
| 上述两项合计 | 1,731 | 1,702 |
| 触发器 | 1,013 | 721 |
| CARRY4 | 183 | 183 |
| DSP48E1 | 1 | 1 |
| RAMB18 / RAMB36 | 0 / 0 | 0 / 0 |
| 最长寄存器间组合单元数 | 16 | 16 |

逻辑 LUT 减少 89 个，计入新增分布式存储后，物理共享前的 LUT 合计减少 29 个。完整 SoC 的面积由固定整机版本重新测量。最长寄存器间组合路径的最终限制为 15 个单元。

## 完整状态与容量

11 组参数的完整模块比较共证明 43,693 位状态与输出等价，全部外部输入保持自由。参数覆盖 32、64、128、1,024 位总线，8、16、32 位数据，1、2、3、4 个描述符，16、17、32 位地址，以及单拍、32 拍和 256 拍物理突发上限。

验证副本把两份实现的每个描述符组织为相同的观察向量，保持所有真实状态更新。前向结构比较、组合证明和时序归纳共同检查完整状态，不增加输入取值限制。

生产 SoC 的 DMA 使用 `SIZE=64`、`CACHE_BLOCKS=64`、四个描述符。封装前后均保存 616 位描述符状态，其中 regfile 数据为 604 位，标签为 12 位。两次完整 NPU 展开只替换 DMA 源码，全部顺序状态、缓冲数组与寄存器数组容量相同。

## 功能与配置检查

- BUS32/64 的描述符回归完成 752 个命令、282,596 次数据比较和 75,836 个周期，固定等待与随机等待的全部计数均与参考实现一致。
- 64 位总线的 4 KiB 读取回归完成 726 个命令、293,600 次数据比较，覆盖跨页、跨字、描述符继续执行及最多四个在途事务。
- 写入回归覆盖一个和四个在途事务以及固定和随机等待，共完成 1,104 个命令和 2,475,760 次写入字节检查。
- 中止恢复通过 14 个场景，包含 65 个写地址接收和 3,266 个写数据节拍；全部 C++ 编译单元启用未定义行为检查。
- 配置检查完成 12 次 RTL 运行和 1,836 条断言。独立 DMA 实例遍历两种总线下的全部合法突发上限与页内分段；42 组完整 NPU 配置检查参数传播、共享存储能力和容量。Python 配置接口接收 24 组合法共享配置并拒绝 22 组非法配置。

详细参数、编译输入、运行统计和 SHA-256 见 [measurement.json](measurement.json)。

## 复现

```sh
python3 test/dma_byte_layout/run_formal.py \
  --reference-ref 4448177 --out build/dma_context_formal \
  --address-parameters --context-parameters --production-parameters \
  --observe-context-storage
python3 test/dma_byte_layout/synthesis.py \
  --reference-ref 4448177 --out build/dma_context_synth/reference
python3 test/dma_byte_layout/synthesis.py --out build/dma_context_synth/current
python3 test/dma_context_storage/run_capacity.py \
  --out build/dma_context_capacity --verilator verilator-modern
python3 test/linear_dma_context/run.py \
  --out build/dma_context32 --bus-width 32 --verilator verilator-modern
python3 test/linear_dma_context/run.py \
  --out build/dma_context64 --bus-width 64 --verilator verilator-modern
python3 test/linear_dma_4k/run.py \
  --out build/dma_context_page64 --bus-width 64 --verilator verilator-modern
python3 test/linear_dma_write_4k/run.py \
  --out build/dma_context_write64 --bus-width 64 --verilator verilator-modern --jobs 1
python3 test/run_cpp_rtl.py dma_abort \
  --out build/dma_context_abort --verilator verilator-modern
python3 test/performance_analysis/validate_configuration_bounds.py \
  --out build/dma_context_config --verilator verilator-modern --jobs 2
```
