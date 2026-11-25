# IA 发送资格寄存验证

`ia_loader_ctrl` 在状态接收边沿同时保存 `ia_data_valid`。更新值使用该边沿之后的状态、组就绪标志和连续输出标志，保持原有接收优先级、异步复位和输出周期。`cache_l1_start` 由 `send_ia_trigger` 与保存的发送资格共同产生。

发送资格参与 NPU 发送调度及偏置读取使能。将资格计算移入原有寄存器输入侧，可以减少公开输出后的组合计算。该修改增加一个资格触发器，全部公开接口、缓存容量和加载事务保持原有行为。

参考提交为 `45c6caec46d94015209140f422bc1338b547c23a`。完整 IA 模块和控制模块的比较分别读取参考与当前源码；参考依赖独立命名，输入文件保存 SHA-256。

## 完整 IA 综合结果

两个配置共同使用 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`DMA_LANES=8`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、`ORDERED_JOB=1`、`RAM_WORD_ADDR_WIDTH=12`、`PS_FRAME_COUNT=16`，以及 `p_dma_source_layout=1`、`p_shared_write_stage=1`、`p_register_dma_request=1`。所有公开端口均参与综合，实际参数通过 `read_slang -G` 传入。

| 指标 | SoC 配置参考 | SoC 配置当前 | 紧凑扩展参考 | 紧凑扩展当前 |
| --- | ---: | ---: | ---: | ---: |
| `COMPACT_S8` | 0 | 0 | 1 | 1 |
| 逻辑 LUT | 4,488 | 4,496 | 5,373 | 5,366 |
| 分布式存储 LUT | 12 | 12 | 20 | 20 |
| 触发器 | 2,375 | 2,376 | 2,816 | 2,817 |
| DSP48 | 9 | 9 | 13 | 13 |
| RAMB36 | 2 | 2 | 2 | 2 |
| RAMB18 | 1 | 1 | 1 | 1 |
| 寄存器之间最长组合逻辑级数 | 10 | 10 | 10 | 10 |
| 寄存器至 `ia_data_valid` 输出组合逻辑级数 | 2 | 0 | 2 | 0 |

当前 SoC 使用 32 个普通槽位。紧凑扩展支持 32 个普通槽位或 64 个紧凑槽位。综合采用 Yosys `0.71+40`、`read_slang`、`synth_xilinx` 和 ABC9，使用 `--abc9-batch-size 256 --abc9-isolate-leaves`。表中级数来自映射网表的实际连接；完整 SoC 的跨模块最长路径由完整 SoC 网表单独统计，150 MHz 时序由器件布局布线延迟分析确认。

## 功能与周期检查

| 检查 | 完成结果 |
| --- | --- |
| 状态与资格局部形式比较 | 无限时序等价通过，公开输入不增加约束 |
| 状态与资格局部四态比较 | 100,004 周期，比较状态、组就绪、连续输出、发送资格和启动脉冲 |
| 完整控制模块四态比较 | 两个配置各 20,004 周期，每周期比较全部 43 个公开输出 |
| 完整控制模块状态覆盖 | 两个配置均访问全部五个 FSM 状态，各有 1,576 个发送有效周期 |
| 完整 IA 形式比较 | 五组参数、62,980 个等价位通过，公开输入不增加约束 |
| 完整 IA 接口比较 | 239,923 周期，每周期比较全部 40 个公开输出 |
| 完整 IA 数值比较 | 1,083,872 个值全部一致 |

局部与完整控制四态测试在异步复位变化后、时钟上升沿后分别比较输出，逐个向输入注入 `X/Z`，保留复位、并发完成、发送、输出保持和优先级检查。完整控制测试启用 `SYNTHESIS`、`XILINX_FPGA` 和生产配置的预计算参数；输入端口全部显式连接。仿真副本将常量零数组展开为逐项连接，原始依赖与仿真副本分别记录内容摘要。

完整 IA 形式参数覆盖当前 SoC 配置、紧凑扩展、32 位计数、32 位与 128 位总线，以及通用调度。接口测试包含普通预取、有序预取、分组任务、S8/S16、DMA 命令与 PS 输出，运行时启用 C++ 未定义行为检查。

## 复现

从仓库根目录运行，需要 `python`、包含 `read_slang` 的 `pyosys`、Icarus Verilog、`vvp` 和配置好 C++20 编译环境的 Verilator。

```sh
ia_result=/tmp/ia_state_outputs
ia_verilator=verilator

python test/ia_state_outputs/run_local.py \
  --reference 45c6caec --out "$ia_result/local"

python test/ia_state_outputs/run_control_four_state.py \
  --reference 45c6caec --out "$ia_result/control_four_state"

python test/ia_optimization/compare_formal.py \
  --reference 45c6caec --out "$ia_result/formal"

python test/ia_optimization/compare_interface.py \
  --reference 45c6caec --verilator "$ia_verilator" \
  --out "$ia_result/interface"

python test/ia_step_product/prepare_measurement.py \
  --reference 45c6caec --out "$ia_result/inputs"

for ia_variant in reference current; do
  for ia_profile in soc compact; do
    python scripts/fpga/open_fpga_synth.py \
      --source-root "$ia_result/inputs/$ia_variant" \
      --case-config "$ia_result/inputs/cases.json" \
      --cases "${ia_profile}_${ia_variant}" \
      --abc9-batch-size 256 --abc9-isolate-leaves \
      --out "$ia_result/synthesis" \
      --lock-file "$ia_result/synthesis.lock"
  done
done
```

验证脚本在指定输出目录保存 `summary.json`、固定源码、执行脚本和日志。综合输出保存 `metrics.json`、`manifest.json` 和阶段脚本；输入目录的 `source_sha256.json` 记录参考及当前全部依赖文件的内容摘要。
