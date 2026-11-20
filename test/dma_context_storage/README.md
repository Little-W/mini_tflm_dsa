# DMA 描述符存储与同步基地址读取

`axi_linear_block_dma` 把当前响应需要的描述符字段保存在一个异步读取的 `regfile` 中，标签使用独立的同步复位寄存器。每个描述符的基地址保存在同步读取的 `regfile` 中，采用 `p_ram_style="block"`。所有存储字使用相同的写地址与写入使能。

当前描述符完成且队列仍有后继描述符时，同步读取后继基地址。读取结果与地址来源标志在同一个时钟边沿更新，响应地址在原有周期取得后继基地址。初始命令与后续行地址使用直接地址寄存器。同址读写返回写入前的数据，与原有采样行为一致。

## 容量与功能

生产 SoC 中 DMA 使用 `SIZE=64`、`CACHE_BLOCKS=64`、四个描述符。描述符容量为 616 bit，包括 128 bit 基地址、476 bit 其他字段及 12 bit 标签。完整 NPU 展开保留全部缓冲数组与寄存器数组容量，增加 32 bit 同步读结果和 1 bit 地址来源状态。

6 组 FPGA 形式等价比较共通过 16,628 bit，覆盖 32/64 bit 总线、1/2/3/4 个描述符和生产配置。每个原始存储字的字段分别与当前两个存储阵列逐位比较，公开输出和完整行地址均参加证明；外部输入保持自由。

数值回归覆盖 1 个和 4 个描述符，分别采用固定等待与随机等待。四次运行合计完成 816 个命令、396,912 次输出数据比较，包含 S8/S16、非总线边界地址、尾列、256 拍突发、4 KiB 边界、同时完成与接收、地址通道暂停及错误恢复。

## 独立综合结果

参考提交为 `df8a9b2d`。两份源码使用相同的公共 RTL、`SYNTHESIS` 和 `XILINX_FPGA` 分支，以及七系列综合选项。参数为 `SIZE=64`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`CACHE_BLOCKS=64`、`RD_CONTEXT_DEPTH=4`。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,705 | 1,714 |
| 分布式 RAM LUT | 64 | 56 |
| 共享打包前合计 | 1,769 | 1,770 |
| 触发器 | 735 | 744 |
| RAMB18E1 | 0 | 1 |
| DSP48E1 | 1 | 1 |
| CARRY4 | 175 | 175 |
| 最长寄存器间组合单元数 | 16 | 16 |

该修改将后继基地址的存储读取纳入同步 BRAM。独立综合的最长路径仍来自后续突发地址计算；完整 SoC 使用统一算术映射，其组合深度和布局资源由整机报告统计。150 MHz 需要器件延迟与布线时序结果。

输入摘要、源文件散列和运行统计见 [base_measurement.json](base_measurement.json)。

## 复现

```sh
python3 test/frontend_rtl_structure/formal.py \
  --reference df8a9b2d --retimed-dma-base \
  --cases linear32 linear64 linear64_c1 linear64_c2 linear64_c3 linear64_s64 \
  --out build/dma_context_base_formal
python3 test/dma_context_storage/run_capacity.py \
  --reference-ref df8a9b2d --out build/dma_context_base_capacity \
  --verilator verilator-modern
python3 test/linear_dma_context/run.py --fpga --bus-width 64 \
  --outstanding 4 --contexts 1 --out build/dma_context_base_numeric1 \
  --verilator verilator-modern
python3 test/linear_dma_context/run.py --fpga --bus-width 64 \
  --outstanding 4 --contexts 4 --out build/dma_context_base_numeric4 \
  --verilator verilator-modern
```
