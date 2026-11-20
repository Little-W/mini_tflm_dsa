# 描述符来源选择与前端路径

## 当前设计

`axi_dual_block_dma` 使用 `win_busy` 直接选择窗口队列已经准备的描述符。普通 im2col 命令在窗口队列为空时接收；`rd_start` 所在周期禁止窗口请求进入队列；普通描述符等待前端接收时，`conv_pending` 使窗口队列暂停接收。因此，`conv_pending` 与 `win_busy` 在复位后的每个周期保持互斥，描述符字段的选择结果逐周期保持一致。

本次修改从描述符字段的组合选择条件中移除 `conv_pending`，让该寄存位继续承担普通命令的有效性控制。接口、队列容量、配置范围和各项握手周期保持不变。

参考提交为 `437a8d81`。唯一修改的 RTL 文件为 `rtl/npu/dma/axi_dual_block_dma.sv`，SHA256 为：

```text
30aba691e30cba0398a0fda5e02d63aae43876881cb938c3016f6efe5a03626a
```

## 功能检查

`formal.py` 读取实际 DMA 和窗口队列源码，在复位后不限制外部请求与返回值。前端、线性 DMA、读取保护、写入保护和读取复用模块以接口模型提供任意输出。对于队列深度 2、3、4、7、8，一步归纳证明均通过：队列计数保持在容量范围内，两个描述符来源保持互斥，修改前后的选择表达式在每个周期严格相等。脚本同时核对其余 DMA 逻辑和整个队列源码与参考提交相同。

官方 FPGA 原语模型的窗口测试通过，包括连续命中、反压、普通读取与窗口并发、错误返回、非法描述符、配置切换和复位取消：

| 检查 | 结果 |
|---|---:|
| 接收窗口请求 | 422 |
| 完成窗口请求 | 418 |
| 复位取消窗口请求 | 4 |
| 数值比较 | 4,457 个输出元素 |
| 预期错误返回 | 19 |
| 常驻窗口逐周期记录 | 1,545 行，与参考提交完全一致 |
| 非二次幂及宽通道配置 | 30 组 |
| 边界配置窗口请求 | 960 个，全部完成 |
| 边界配置数值比较 | 7,916 个输出元素 |
| 边界配置逐周期记录 | 249,411 行，与参考提交完全一致 |

FPGA 数值测试启用断言和 C++ 未定义行为检查。形式证明、数值模型及联合综合使用相同 RTL；`summarize.py` 检查源码散列值后生成 `measurement.json`。

## 联合综合

联合范围包含实际 `axi_dual_block_dma`、窗口队列、完整 im2col 前端、读取缓存及下一次访问预测器。线性 DMA、读取保护、写入保护和读取复用模块保留接口边界。参数为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、`CONV_CACHE_SETS=128`、`LANES=4`。

| 资源 | 参考提交 | 当前修改 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT 单元 | 13,113 | 13,103 | −10 |
| LUTRAM 名义位置 | 484 | 484 | 0 |
| 触发器 | 6,300 | 6,300 | 0 |
| DSP48E1 | 46 | 46 | 0 |
| RAMB18E1 | 20 | 20 | 0 |
| CARRY4 | 1,118 | 1,118 | 0 |

下表采用映射网表的实际逐输出依赖，统计寄存器之间连续组合单元数。

| 起点与终点 | 参考提交 | 当前修改 |
|---|---:|---:|
| `conv_pending → tap0` | 13 | 9 |
| `conv_pending → ky_q` | 13 | 9 |
| `conv_pending → ky0_q` | 13 | 9 |
| `conv_pending → frontend` 所有寄存器 | 15 | 9 |
| 队列 `count → tap0/ky_q/ky0_q` | 13 | 13 |
| 队列 `count → frontend` 所有寄存器 | 15 | 15 |
| 所有起点 `→ tap0` | 15 | 13 |
| 所有起点 `→ ky_q` | 14 | 14 |
| 所有起点 `→ ky0_q` | 14 | 13 |
| 整个联合范围最长路径 | 16 | 16 |

当前联合网表仍有两组 16 级路径：缓存 `fg_state[1] → row_wrap_q`，以及预测器内部 DSP 寄存器输出到 `coordinate_good_s1`。上述三项目标寄存器的全部输入路径均不超过 14 级。完整 SoC 的最终单元数和路径深度由采用相同源码的整机综合结果给出。

## 复现

在仓库根目录加载工具环境后执行：

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 test/frontend_pending_select/formal.py \
  --reference 437a8d81 --out build/r20_pending/formal
flock /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock \
  python3 test/window_descriptor_stage/synthesis.py \
  --reference 437a8d81 --out build/r20_pending/joint \
  --include-cache --include-predictor
python3 test/frontend_pending_select/paths.py \
  --joint build/r20_pending/joint --out build/r20_pending/paths.json
python3 test/window_dma/run.py \
  --out build/r20_pending/window_fpga --verilator verilator-modern \
  --jobs 1 --fpga --reference-ref 437a8d81
python3 test/frontend_ia_depth/window_boundary.py \
  --model build/r20_pending/window_fpga \
  --proof build/r20_pending/formal/summary.json \
  --verilator-include "$(verilator-modern --getenv VERILATOR_ROOT)/include" \
  --out build/r20_pending/window_boundary
python3 test/frontend_pending_select/summarize.py \
  --build build/r20_pending --out test/frontend_pending_select/measurement.json
```
