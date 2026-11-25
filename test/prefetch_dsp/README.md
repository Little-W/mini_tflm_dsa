# 预取准备阶段的分段加法

`conv_im2col_prefetch.g_prefetch_prepare[2]` 的卷积核横坐标加法使用
`parallel_prefix_add.p_dsp_split_width=16`。两个16位分段通过普通 RTL 加法推断
DSP 算术，各段保留进位，低段进位用于修正高段结果。输出继续保留完整32位和值。
预取阶段、寄存器更新条件、公开接口和传输周期保持一致。

## 功能检查

`run_formal.py` 从指定 Git 提交独立保存参考源码，比较完整预取模块的实际寄存器
和全部21个公开输出，共492位。六组参数覆盖 `p_size=1/3/8/16/32`、
`p_line_bytes=16/32/64/128/256`、缓存请求是否登记，以及显式扩展的 `p_rw=5`。
外部输入不附加约束，时序证明采用归纳法。另对启用 `SYNTHESIS` 的加法器证明
完整33位结果，两个32位操作数与输入进位均为自由输入。

`run_four_state.py` 对每组参数检查数据、有效位、预取阶段与引用字段，逐位向
数据、配置、复位及握手输入注入 X/Z，并要求全部13个预取阶段都被执行。
四态比较使用通常的 RTL 仿真分支。

`run_mapped.py` 使用完整 Xilinx `cells_sim.v` 模型，将生产参数的实际映射网表与
启用 `SYNTHESIS` 的 RTL 逐周期比较。数据寄存器在前32个时钟周期内完成首次保存，
随后每个周期检查三个时刻的全部21个公开输出。

在仓库根目录执行：

```sh
python test/prefetch_dsp/run_formal.py \
  --reference a48e0c2768edd76ef24c0b6aa20afd9e45cebb27 \
  --out build/prefetch_dsp/formal
python test/prefetch_dsp/run_four_state.py \
  --formal build/prefetch_dsp/formal \
  --out build/prefetch_dsp/four_state
```

## 资源和路径检查

`prepare_measurement.py` 保存两侧完整源码、SHA-256 和显式 `-G` 参数。
预取模块使用 `p_size=16`、`p_line_bytes=128`、`p_rw=5`，缓存请求登记使能。
完整前端使用 `SIZE=16`、`SLOT_W=5`、`LANES=8`、`CACHE_SETS=16`、
`CACHE_WAYS=2`、`LINE_BYTES=128`、`BUS_WIDTH=64`、`DMA_MAX_BYTES=2048`、
`CACHE_POLICY=3`、`REGISTER_DESCRIPTOR=0`、`REGISTER_ROW_ADDRESS=0`、
`REGISTER_CACHE_REQUEST=1`、`CACHE_RESPONSE_DEPTH=1`。

```sh
python test/prefetch_dsp/prepare_measurement.py \
  --reference a48e0c2768edd76ef24c0b6aa20afd9e45cebb27 \
  --out build/prefetch_dsp/inputs
for measurement_side in reference current; do
  python scripts/fpga/open_fpga_synth.py \
    --source-root "build/prefetch_dsp/formal/sources/$measurement_side" \
    --case-config build/prefetch_dsp/inputs/all_cases.json \
    --cases prefetch --abc9-batch-size 64 --abc9-isolate-leaves \
    --out "build/prefetch_dsp/prefetch_$measurement_side"
  python scripts/fpga/open_fpga_synth.py \
    --source-root "build/prefetch_dsp/inputs/sources/$measurement_side" \
    --case-config build/prefetch_dsp/inputs/all_cases.json \
    --cases frontend --abc9-batch-size 64 --abc9-isolate-leaves \
    --out "build/prefetch_dsp/frontend_$measurement_side"
done
python test/prefetch_dsp/run_mapped.py \
  --formal build/prefetch_dsp/formal \
  --mapped build/prefetch_dsp/prefetch_current/prefetch/mapped.v \
  --out build/prefetch_dsp/mapped
```

完整前端的复用参考测量由31份依赖源码、明确的综合选项与当前参考提交逐项核对。
结构路径按连通的器件单元统计，DSP 的内部寄存器和独立 SIMD 通道参与边界识别。
150 MHz 的物理时序由布局布线结果评估。

## 已完成的验证

六组完整模块的无输入约束时序证明全部通过。四态仿真共执行45,050个周期，
完成2,838,150次端口输出比较和20,468次逐位 X/Z 注入。实际映射网表与
`SYNTHESIS` RTL 的4,097个周期比较通过，共检查256,095个端口输出结果。

| 测量范围 | 逻辑 LUT | 触发器 | DSP | 寄存器之间最长路径 |
| --- | ---: | ---: | ---: | ---: |
| 完整预取模块，参考 | 1,298 | 927 | 3 | 13 |
| 完整预取模块，当前 | 1,261 | 927 | 4 | 13 |
| 完整卷积前端，参考 | 16,554 | 6,178 | 32 | 16 |
| 完整卷积前端，当前 | 16,410 | 6,178 | 33 | 16 |

完整前端的输入到寄存器、寄存器到输出及输入到输出最长路径分别为16、12和2级，
与参考实现相同；RAMB36为1个、RAMB18为22个、存储 LUT 为68个，数量保持一致。
`validation.json` 保存两侧完整源码摘要、显式参数、证明记录和映射结果。
