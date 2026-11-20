# im2col 坐标和通道边界路径

## 当前结构

`conv_im2col_frontend` 在现有坐标寄存周期保存输出行尾、卷积核行尾和分块末行条件。配置更新、位置解码、快速描述符接收和逐项发送同时维护这些条件，公开握手和完成周期保持一致。

七个坐标方向分别并行计算结果与图像范围。低八位产生进位，高位预先计算两种进位对应的结果；图像范围检查使用两个八位比较和高位加法等式。数据字命中独立比较缓存地址和当前响应地址，完成条件只选择一位命中结果。短步长地址、归约位置和通道索引采用分段加法。`LANES=3/4` 的低两位偏移直接按位生成，高十四位范围比较拆成两个七位比较。

该实现保留三个退休行号计算、剩余列数寄存和直接按有效通道计算末段条件。接口、内部存储容量、分块尺寸及配置范围保持一致，新增四个状态位。

坐标算法参考附件 `fpga_after_59966.tar.gz` 中 `optimize/frontend-coordinate-depth` 的实现，附件参考提交为 `8011bdd98d9d186c1ad5e644c49ef4cb61cf948a`，分析提交为 `7bf8f83`。本次采用当前分支的末段和退休逻辑，并独立完成下述验证。

## 独立综合

参数为 `SIZE=16`、`LANES=4`、`BUS_WIDTH=64`、`CACHE_SETS=128`、`CACHE_WAYS=2`、`LINE_BYTES=16`。综合器将缓存和预测器作为接口边界，使用原生 Xilinx 7 系列映射。

| 项目 | 参考提交 `8c669a70` | 当前实现 |
|---|---:|---:|
| 逻辑 LUT 单元 | 6503 | 7179 |
| 触发器 | 3236 | 3240 |
| DSP48E1 | 30 | 30 |
| CARRY4 | 726 | 840 |
| 寄存器间最长组合路径 | 20 | 15 |

路径分析逐位检查单元连接，按实际端口依赖处理 `LUT6_2`、`CARRY4` 和 DSP 内部寄存边界。当前最长路径从 `row_base_ix[0]` 到 `state[0]`，共 15 个组合单元。综合峰值常驻内存为 416680 KiB。物理 LUT 位置和 150 MHz 器件时序使用完整 `soc_top` 的实现报告评估。

## 功能与周期验证

所有结果、源码摘要及日志摘要保存在 `docs/data/frontend_coordinate_validation.json`。

| 验证内容 | 结果 |
|---|---|
| 完整状态等价 | 11 种配置，346481 位，全部通过 |
| 缓存策略 | 0、1、2、3 |
| 缓存行宽 | 8、16、32、64、128、256 字节 |
| 传输通道数 | `LANES=1/2/3/4` |
| 生产缓存配置 | `SIZE=16`、`BUS_WIDTH=64`、128 组、2 路，覆盖 `LANES=2/4` |
| 坐标算术 | 7 个方向的 35 位结果和范围条件，共 252 位；全部输入模式通过 |
| 数据字命中 | 261 个任意输入位、2 个命中结果，通过 |
| 通道范围专用表达式 | 32 个任意输入位、13 个结果位，通过 |
| 公开输出逐周期比较 | 4 种数值配置，各 37 项任务，共 148 项任务、1675290 周期，19 项公开输出一致 |
| 定向控制 | 23 项检查、16 次填充写入、134 周期，通过 |
| 前端背压 | 38 项窗口任务和控制测试，共 251160 周期，249427 次受阻提供、81 次快速描述符上下文，通过 |
| DMA 窗口逐周期比较 | 49 项公开输出和 401 位完整队列状态，24913 周期一致 |
| DMA 窗口数值与恢复 | 421 个接收请求、417 个完成请求、4 个复位取消请求、4441 个输出元素、19 个预期错误，通过 |
| 驻留窗口连续输出 | 128 个请求、512 个响应、2048 个元素；响应最大间隔 3 周期，输出范围共 1534 周期 |

完整状态证明分为两个直接连接的部分。首先，对通用通道加法和大小比较形式完成全部 11 种配置的状态证明。其次，`group_boundary_equivalence.py` 从当前 RTL 提取两个专用表达式，对其全部输入模式证明等价，并验证生成通用表达式形式后的整个文件摘要与完整状态证明的源码完全一致。两处表达式以外的源码按字节相同。当前 RTL 另有 4 种配置的直接完整状态证明，共 108705 位。

参考前端源码 SHA-256 为 `f2878906967681fbfffb2aebf7e3311d7efa6c7f921d44aa62c1cb5a2b0cf8f8`。通用表达式形式为 `c00bfa51c394461e675fa7f4ffad87e530636406bf937777d9c61cf01d990705`。当前前端源码为 `6d8e25052e266e7a7ed55bd3b696daa74d9f8d7cbb1f997406a09ebd67c0e102`。

窗口逐周期记录位于 `test/dma_direct_offer/window_cycles.csv.gz`。当前运行生成的请求、响应、队列控制和各槽位字段与该记录逐字节一致；解压后 SHA-256 为 `6065ce15a5a5bdb653e13fd1b5d2905858b2f96004916048fd2428867c5e5289`。

## 复现

下列命令从仓库根目录运行，环境需提供带 slang 的 Pyosys 和 Verilator。

```bash
python3 test/conv_frontend/tools/group_boundary_equivalence.py \
  --out build/frontend_coordinate/group_arithmetic
python3 test/conv_frontend/tools/run_state_equivalence.py \
  --reference-ref 8c669a70 \
  --current-source build/frontend_coordinate/group_arithmetic/general_frontend.sv \
  --out build/frontend_coordinate/state
python3 test/conv_frontend/tools/group_boundary_equivalence.py \
  --state-summary build/frontend_coordinate/state/summary.json \
  --out build/frontend_coordinate/group_arithmetic
python3 test/conv_frontend/tools/coordinate_bound_equivalence.py \
  --out build/frontend_coordinate/coordinate_arithmetic
python3 test/conv_frontend/tools/word_match_equivalence.py \
  --reference-ref 8c669a70 --out build/frontend_coordinate/word_arithmetic
python3 test/conv_frontend/tools/compare_frontend.py \
  --reference-ref 8c669a70 --lanes 4 --out build/frontend_coordinate/interface
python3 test/dma_direct_offer/frontend_backpressure.py \
  --cases window control --out build/frontend_coordinate/backpressure
python3 test/dma_direct_offer/window_compare.py \
  --out build/frontend_coordinate/window_dma
python3 test/conv_frontend/tools/synthesis.py \
  --reference-ref 8c669a70 --lanes 4 --out build/frontend_coordinate/reference
python3 test/conv_frontend/tools/synthesis.py \
  --lanes 4 --out build/frontend_coordinate/current
```
