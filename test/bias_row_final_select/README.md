# 偏置行索引的末级选择

`npu_top` 先并行计算偏置行索引的保持、递增与回绕结果，再以每位一个 `LUT6_2` 处理配置初始化和组首清零。`send_ia_trigger`、`init_cfg_ia` 与 `bias_sleep` 直接进入寄存器前的最后一级组合。

行索引使用独立的 `always_ff`，保留 `core_rst_n` 的异步低有效复位、全部位宽和原有采样边沿。偏置组基址、末组基址、末组行数、当前有效行数和待生效有效行数继续使用原有状态更新。组合读取索引和偏置缓冲区接口保持原有行为。

## 生产参数映射

测量从实际 `npu_top.sv` 提取完整偏置组状态和行索引，参数为 `SIZE=16`、`REG_WIDTH=32`、`BIAS_GROUP_BLOCKS_MAX=32`。参考提交为 `e5ae51f1`。两侧使用相同依赖、综合选项和官方原语模型，宽算术映射的DSP预算为740、最小算术位宽为8。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 原生映射逻辑 LUT | 230 | 230 |
| 物理成本映射逻辑 LUT | 201 | 208 |
| 触发器 | 103 | 103 |
| DSP48E1 | 4 | 4 |
| CARRY4 | 12 | 12 |
| 原生映射完整控制块最长路径 | 10级 | 10级 |
| 物理成本映射完整控制块最长路径 | 9级 | 9级 |
| 两种映射的 `send_ia_trigger` 至行索引寄存器 | 2级 | 1级 |
| 两种映射的 `init_cfg_ia` 至行索引寄存器 | 2级 | 1级 |
| 两种映射的 `bias_sleep` 至行索引寄存器 | 2级 | 1级 |

路径分析仅在分析图中标记输入端口，实际RTL没有增加寄存器或周期。报告保留 R18 固定源码 `3f78c674` 的16级完整SoC路径，起点为偏置基址寄存器的映射别名，终点为 `is_bias_row_idx`。完整SoC结果由合入当前结构后的整机综合与布局布线报告记录。

当前顶层文件的SHA256：

```text
5643295304d6bf03b36a9412bb30389ecc2be701f8f4423ab3e746b00ef03eae
```

## 状态与数值验证

| 验证范围 | 配置或场景数量 | 结果 |
| --- | ---: | --- |
| 实际顶层完整偏置组状态与行索引 | 16组 | 5,944位等价比较通过 |
| 组首读取与完整偏置缓冲区 | 6组 | 8,549位等价比较通过 |
| 完整偏置加载器、寄存器与存储位 | 6组 | 114,313位等价比较通过 |
| 偏置加载数值测试 | 392个场景 | 193,571个周期、880个DMA命令通过 |
| 完整FPGA NPU的WS/IS局部数值测试 | 7项 | 222,579个周期、244个INT32结果比较通过 |

行索引状态比较同时覆盖FPGA与通用实现，包含1/4/16/32行阵列、1/4/32/64个分块容量以及16/32/64位寄存器。时序证明不对外部输入施加取值或握手约束，并比较读取索引及其余五项偏置组状态。

NPU数值测试使用当前完整文件列表和官方FPGA原语模型，阵列为4×4，覆盖WS、IS、不同复用设置、AXI错误恢复与单个归约分块。测试记录源码、编译程序和可执行文件的SHA256。原生映射和物理成本映射的资源、输入边界与具体连接路径保存在 `measurement.json`。

## 运行命令

```sh
python3 test/bias_row_final_select/run_formal.py \
  --out build/bias_row_final_select/formal
python3 test/bias_group_index/run_formal.py \
  --out build/bias_row_final_select/group_index_formal
python3 test/bias_residency_timing/run_formal.py \
  --out build/bias_row_final_select/residency_formal
python3 test/bias_loader_reuse/run.py \
  --out build/bias_row_final_select/bias_numeric --jobs 1
python3 test/bias_row_final_select/run_npu.py \
  --out build/bias_row_final_select/npu --verilator verilator-modern \
  --size 4 --jobs 1 --build-timeout 1800

python3 test/bias_row_final_select/prepare_measurement.py \
  --out build/bias_row_final_select/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/bias_row_final_select/inputs/cases.json \
  --cases reference current --out build/bias_row_final_select/synthesis \
  --wide-alu-dsp-budget 740 --wide-alu-minimum-width 8 \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/bias_row_final_select/measure_paths.py \
  --reference build/bias_row_final_select/synthesis/reference \
  --current build/bias_row_final_select/synthesis/current \
  --out build/bias_row_final_select/native_paths.json
for name in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "build/bias_row_final_select/synthesis/$name" \
    --out "build/bias_row_final_select/cost/$name" --mode physical-cost \
    --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
  ln -sfn "../../synthesis/$name/pre_lut.il" \
    "build/bias_row_final_select/cost/$name/pre_lut.il"
done
python3 test/bias_row_final_select/measure_paths.py \
  --reference build/bias_row_final_select/cost/reference \
  --current build/bias_row_final_select/cost/current \
  --out build/bias_row_final_select/cost_paths.json
python3 test/bias_row_final_select/collect_report.py \
  --results build/bias_row_final_select
```
