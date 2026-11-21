# 线性 DMA 后续读长度

后续突发和新行分别计算页边界限制、突发上限和 AXI 末拍序号，再由 `rd_follow_beats` 选择最终的八位长度。两组完整结果保留组合边界，避免状态选择进入页距离减法和大小比较。

页边界末拍序号使用页内拍索引的逐位取反结果；地址含字内偏移时额外减一。剩余拍数的低八位使用原生定宽减一，未知输入按逐位借位关系传播。未知状态选择条件保留完整原生表达式的四态语义。全部改动位于组合逻辑，寄存器、公开端口、AXI 事务顺序及接口周期保持不变。

## 验证结果

[measurement.json](measurement.json) 保存当前线性 DMA 源码、参考源码、测试输入和映射输入的 SHA-256，并汇总以下实际完成的检查。

| 检查 | 覆盖范围 | 结果 |
|---|---|---:|
| 完整模块等价 | `SIZE=16/64`，总线宽度 `32/64`，读写在途数各 `1/4`，读描述符深度 `1/4` | 32 组、45,168 个公开输出与状态位通过 |
| 实际长度表达式 | `ADDR_LSB=1/2/3/4`，最大突发拍数 `1/2/4/8/16/32/64/128/256` | 36 组无约束 SAT 证明通过 |
| 四态传播 | 32,768 组数据，逐组覆盖上述 36 种参数 | 1,179,648 次严格比较通过 |
| 4 KiB 读事务 | 总线宽度 `32/64`、读在途数 `1/4`，固定及随机等待 | 2,648 个命令、32,432 次物理突发通过 |
| 4 KiB 写事务 | 总线宽度 `32/64`、写在途数 `1/4`，固定及随机等待 | 1,680 个命令、12,824 次物理突发通过 |

完整模块证明检查所有公开输出、共享时钟状态和展开后的描述符存储，不约束外部输入序列。长度表达式证明覆盖任意地址和剩余拍数，包含地址带字内偏移、零拍数及全部九位计数值。四态检查包含 X、Z 地址位、未知计数、未知配置、确定与未知的后续突发选择条件。

读写数值检查复用 `test/linear_dma_4k/run.py` 和 `test/linear_dma_write_4k/run.py`，累计验证 828,344 个总线数据拍。现有参考模型、事务与等待场景全部保留。

## 完整模块中的路径测量

为单独比较读长度实现，两次映射使用完全相同的双通道 DMA 外围源码和参数，仅替换 `axi_linear_block_dma.sv`。映射参数为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`DATA_LANES=8`、`WINDOW_LANES=8`、`CONV_LINE_BYTES=128`，其余参数见 [cases.json](cases.json)。测量遍历完整映射组合图，按实际寄存器起点和终点筛选目标。

| 测量项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 线性 DMA 状态寄存器之间的最长路径 | 15 级 | 13 级 |
| `rd_follow_beats → rd_arlen_r` | 15 级 | 8 级 |
| `rd_follow_beats → rd_follow_addr` | 11 级 | 10 级 |
| 完整测量模块逻辑 LUT | 21,975 | 21,776 |
| 完整测量模块触发器 | 7,503 | 7,506 |
| 推断的 DSP48E1 / RAMB18E1 | 32 / 13 | 32 / 13 |

两份完整图均覆盖所有已映射组合单元。本项固定外围的完整 DMA 最长路径均为 15 级，当前最长路径位于前端 `addr → tap_group_base`；最终前端与线性 DMA 的联合结果由 `test/frontend_depth_timing/` 单独记录。表中 LUT 是映射逻辑单元数量，物理 Slice LUT 和 150 MHz 时序由实际器件实现报告确认。

## 复现

在仓库根目录执行，需要 `pyosys`、Verilator、Icarus Verilog 和 C++ 编译工具。以下命令使用当前 RTL 创建独立输入目录，生成参考模块时只替换随测试保存的长度选择表达式。

```bash
run_root=build/dma_read_length_depth
python test/dma_read_length_depth/prepare_measurement.py --out "$run_root/inputs"

python test/frontend_depth_timing/linear_check.py \
  --reference "$run_root/inputs/reference/rtl/npu/dma/axi_linear_block_dma.sv" \
  --candidate "$run_root/inputs/current/rtl/npu/dma/axi_linear_block_dma.sv" \
  --sizes 16 64 --out "$run_root/formal"
python test/dma_read_length_depth/check.py \
  --reference "$run_root/inputs/reference/rtl/npu/dma/axi_linear_block_dma.sv" \
  --candidate "$run_root/inputs/current/rtl/npu/dma/axi_linear_block_dma.sv" \
  --out "$run_root/arithmetic"

for bus in 32 64; do
  for outstanding in 1 4; do
    python test/linear_dma_4k/run.py \
      --source-root "$run_root/inputs/current" \
      --bus-width "$bus" --outstanding "$outstanding" \
      --out "$run_root/read/b${bus}_o${outstanding}"
  done
  python test/linear_dma_write_4k/run.py \
    --source-root "$run_root/inputs/current" \
    --bus-width "$bus" --outstanding 1 4 --jobs 1 \
    --out "$run_root/write/b${bus}"
done

for design in reference current; do
  python scripts/fpga/open_fpga_synth.py \
    --source-root "$run_root/inputs/$design" \
    --case-config test/dma_read_length_depth/cases.json --cases dma_length \
    --max-register-path-cells 14 --out "$run_root/mapping_$design" \
    --lock-file /tmp/npu_synthesis_20261121.lock
done
python test/dma_read_length_depth/measure_paths.py \
  --reference-folder "$run_root/mapping_reference/dma_length" \
  --current-folder "$run_root/mapping_current/dma_length" \
  --out "$run_root/paths.json"
python test/dma_read_length_depth/collect_results.py \
  --source-root "$run_root/inputs/current" \
  --formal "$run_root/formal/summary.json" \
  --arithmetic "$run_root/arithmetic/summary.json" \
  --read-root "$run_root/read" --write-root "$run_root/write" \
  --measurement "$run_root/paths.json" --out "$run_root/measurement.json"
```

汇总程序逐项检查源码、配置数量、四态覆盖、实际读写结果及完整图状态；线性 DMA 目标寄存器路径超过 14 级时返回失败。`prepare_measurement.py` 和 `prepare_reference.py` 均支持 `--source-root`，可以使用独立固定源码目录。
