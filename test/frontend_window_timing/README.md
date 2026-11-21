# 窗口候选坐标选择验证

`conv_im2col_frontend` 根据描述符选择当前空间位置、相邻空间位置及前后卷积核位置。坐标、地址、填充标志与窗口请求保持原有周期关系。

实现通过 `add_equal` 并行检查四组相邻核位置和连续空间分块起点的进位一致性。核位置使用 33 位加法比较，空间分块起点使用 32 位模加比较。前向、后向、跨行与跳过填充位置的候选坐标分别计算填充状态，描述符选择已完成的结果。35 位有符号坐标及其溢出行为保留，公开接口与状态寄存器保持原有形式。

## 功能检查

`check.py` 从指定版本与当前实际源码提取候选选择区域，逐位比较 338 位输出，包括坐标、地址、核位置、填充标志与快速接收条件。SAT 检查覆盖 `SIZE=4/16/64` 和 `CACHE_POLICY=0/3`，所有输入均未增加约束，并包含 `p0` 加上行数时发生 32 位溢出的情况。

```sh
python test/frontend_window_timing/check.py --out build/frontend_window_timing/proof
python test/conv_frontend/tools/compare_frontend.py \
  --reference-ref 4dee27ffec4dc891daf2681379f8b3fd27fd41f2 \
  --out build/frontend_window_timing/frontend --verilator verilator --lanes 4
python test/window_dma/run.py \
  --reference-ref 4dee27ffec4dc891daf2681379f8b3fd27fd41f2 \
  --out build/frontend_window_timing/window --verilator verilator --jobs 2 --fpga
```

前端数值比较覆盖 4、8、16 三种阵列尺寸、32/64 位总线、窗口模式与普通模式，并比较 19 个公开输出。控制测试覆盖配置检查、无效描述符和填充输出。

DMA 测试包含连续命中、单拍窗口、普通读取与窗口读取并发、随机坐标和停顿、读取错误后的请求处理、重新配置、无效列数、复位及中止。连续命中测试逐周期比较完整窗口、AXI 与忙状态记录。

## 结构测量

```sh
python scripts/fpga/open_fpga_synth.py \
  --cases reference_window_decode candidate_window_decode \
  --case-config build/frontend_window_timing/proof/synthesis_cases.json \
  --out build/frontend_window_timing/synthesis
python test/frontend_window_timing/paths.py --scope window-decode \
  --top reference_window_decode_registered \
  --mapped build/frontend_window_timing/synthesis/reference_window_decode/mapped.json \
  --pre-lut build/frontend_window_timing/synthesis/reference_window_decode/pre_lut.il \
  --out build/frontend_window_timing/reference_paths.json
python test/frontend_window_timing/paths.py --scope window-decode \
  --top candidate_window_decode_registered \
  --mapped build/frontend_window_timing/synthesis/candidate_window_decode/mapped.json \
  --pre-lut build/frontend_window_timing/synthesis/candidate_window_decode/pre_lut.il \
  --out build/frontend_window_timing/candidate_paths.json
```

测量对象是实际前端的窗口候选选择逻辑。两个版本的输入与输出采用相同的寄存结构，便于比较组合逻辑与资源。

| 项目 | 原版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT 单元数 | 2,456 | 2,527 |
| 寄存器数 | 1,584 | 1,584 |
| 寄存器间最长组合单元数 | 19 | 17 |
| `tile_q0` 至输出的最长组合单元数 | 19 | 12 |
| `p0` 至输出的最长组合单元数 | 17 | 9 |

完整前端数值测试通过 2,171,907 个周期的输出比较，控制测试通过 23 项检查。DMA 测试处理 678 个请求，其中 674 个完成、4 个由复位取消；检查 5,481 个输出元素。连续命中测试的 520 行逐周期记录一致。

`measurement.json` 保存源码摘要、验证结果和结构测量。表中 LUT 数量仅属于上述局部逻辑，组合单元数包含实际连接的 LUT 与进位单元。150 MHz 时序结果需使用完整设计的器件延迟和布线报告确定。

`paths.py` 的默认模式读取完整 SoC 网表，检查描述符队列和整个图像前端的最长路径，并单独固定 `descriptor[1]` RAM 到 `demand_word_matches_q/D`、`work_word_matches_q/D` 的终点。`--reference-report` 接收同一脚本生成的原版本结果，`--summary-out` 保存起点、终点、组合单元数及两版本的简明比较。

## 完整 SoC 连接路径

`soc_paths.json` 保存同一映射流程、同一分析脚本及相同起止点筛选条件下的完整 SoC 测量。

| 范围 | 原版本组合单元数 | 当前版本组合单元数 |
|---|---:|---:|
| q0 描述符 RAM 至 `demand_word_matches_q/D` | 27 | 19 |
| q0 描述符 RAM 至 `work_word_matches_q/D` | 28 | 18 |
| q0 描述符 RAM 至任意前端终点 | 28 | 21 |
| 完整描述符队列至任意前端终点 | 28 | 23 |
| 整个图像前端 | 28 | 25 |

两个固定匹配终点的当前路径均不经过 `CARRY4`。前端当前最长路径从 `row_wrap_q` 到缓存 `work_request.in_range`，也到需求队列保存的同一范围标志。该路径包含 `next_row_addr` 的 32 位地址加法和 `req_addr >= base_q` 的范围比较，共经过 11 个 `CARRY4` 与 14 个 LUT。

上述结果来自完整映射网表的实际连接。器件布局、布线延迟及 150 MHz 的建立时间仍由原生时序分析确定。
