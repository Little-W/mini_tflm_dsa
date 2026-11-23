# IA 请求资格与共享写数据路径

`ia_loader` 分别保留两个坐标等式和已保存标签等式的组合边界，使这些比较独立完成后再与槽位、行数和请求条件组合。声明和逻辑表达式保持一致，全部时序状态和公开事务周期继续使用原有定义。

`ia_loader_cache_mgr` 在原有写命令寄存级前，分别完成紧凑字节排列与宽数据端口选择，再选择最终存储格式。字节符号扩展、偏移运算、写掩码和地址计算保持原有定义。格式包含未知位时，使用原有双端口选择表达式保留四态传播。共享写数据寄存器在已有时钟边沿更新。

## 验证范围

| 检查 | 实际结果 |
|---|---:|
| 完整加载器状态与公开输出等价 | 4 种配置、42,224 位通过 |
| 完整缓存状态与公开输出等价 | 3 种配置、8,709 位通过 |
| 四态预选与保持行为 | 100,004 组输入、157,968 次比较通过 |
| 缓存与共享存储联合比较 | 26,504 周期、397,560 次比较通过 |

加载器等价检查覆盖有序与通用任务、`SIZE=3/16`、外部与本地存储、`BUS_WIDTH=32/64`、`CACHE_BLOCKS=4/32`、`COUNT_WIDTH=29/32`。缓存检查覆盖通用排列和生产 DMA 排列，以及共享写数据预选的启用与关闭。形式输入保持任意取值。

四态测试保留全部数据字节的 `0/1/X/Z` 覆盖，增加格式和使能中的未知值，并逐周期比较寄存数据、使能、保持行为和复位。联合存储测试覆盖紧凑 S8、宽 S8、S16、合法 S16 列起点、掩码、存储分配、配置切换、冲突故障和重新配置。实际执行 18,504 次 IA 写入、10,752 次 IA 读取、52,554 次部分和写入和 52,307 次部分和读取。

## 完整 IA 模块测量

生产参数为 `SIZE=16`、`BUS_WIDTH=64`、`DATA_WIDTH=16`、`CACHE_BLOCKS=32`、`COUNT_WIDTH=29`，启用有序任务、外部存储、生产 DMA 排列和共享写数据预选。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 5,797 | 5,849 |
| 寄存器 | 3,102 | 3,102 |
| RAMB36 / RAMB18 | 2 / 1 | 2 / 1 |
| 寄存器间最长组合单元数 | 13 | 13 |
| 内部寄存器至 `load_ia_req` | 11 | 10 |
| `ext_dma_wr_data` 至共享写数据寄存器 | 8 | 7 |
| `ext_dma_wr_col_base` 至共享写数据寄存器 | 12 | 11 |
| `ext_dma_wr_valid` 至共享写数据寄存器 | 10 | 10 |

表中的端口路径单独标明范围。两个完整模块寄存器图均已完成检查。跨 DMA、加载器、仲裁器的组合路径使用完整 SoC 网表测量；目标器件的 150 MHz 时序与物理 Slice LUT 数量使用布局布线报告确认。

## 复现

输入准备程序保存当前 RTL、依赖文件和 SHA256。参考加载器保留相同外围逻辑，三个比较信号使用普通声明；参考缓存采用保存的原生双端口选择片段。

```bash
python3 test/ia_control_output_depth/prepare_measurement.py \
  --out build/ia_control_output_inputs
python3 test/ia_timing/run_formal.py \
  --source-root build/ia_control_output_inputs/current \
  --reference-root build/ia_control_output_inputs/reference \
  --cases loader_ordered loader_generic loader_small_cache loader_ordered29 \
  --out build/ia_control_output_formal
python3 test/ia_write_output_depth/run_formal.py \
  --source-root build/ia_control_output_inputs/current \
  --reference-root build/ia_control_output_inputs/reference \
  --cases shared_layout1 shared_layout0 production \
  --out build/ia_control_output_cache_formal
python3 test/ia_shared_write_stage/run_four_state.py \
  --out build/ia_control_output_four_state
python3 test/ia_shared_write_stage/run_interface.py \
  --verilator verilator --out build/ia_control_output_numeric
python3 scripts/fpga/open_fpga_synth.py \
  --source-root build/ia_control_output_inputs/current \
  --case-config build/ia_control_output_inputs/cases.json \
  --cases ia_loader_reference ia_loader_current \
  --out build/ia_control_output_mapping \
  --lock-file /tmp/npu_synthesis_20261121.lock --max-register-path-cells 14
python3 test/ia_control_output_depth/measure_paths.py \
  --top ia_loader \
  --reference-folder build/ia_control_output_mapping/ia_loader_reference \
  --current-folder build/ia_control_output_mapping/ia_loader_current \
  --out build/ia_control_output_paths.json
python3 test/ia_control_output_depth/collect_results.py \
  --loader-formal build/ia_control_output_formal/summary.json \
  --cache-formal build/ia_control_output_cache_formal/summary.json \
  --four-state build/ia_control_output_four_state/summary.json \
  --numeric build/ia_control_output_numeric/summary.json \
  --measurement build/ia_control_output_paths.json \
  --out build/ia_control_output_results.json
```

`measurement.json` 保存本轮当前设计的完整结果。
