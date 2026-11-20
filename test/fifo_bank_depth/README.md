# FIFO 银行状态更新与组结束条件

`vec_s8_to_fifo_full` 为每个银行分别计算写入完成、合并组释放和普通输出释放条件。每个银行的 `bank_count` 与 `bank_ready` 在同一个时钟边沿更新，释放保持较高优先级。复位、同周期写入与释放、银行切换和计数回绕均保留原有行为。

FPGA 实现并行计算组结束所需的行列比较，再使用一个 `LUT6_2` 合并结果。所选银行的行结束判断只经过最后一级组合。通用实现使用相同的逻辑表达式。

生产配置为 `VLEN=16`、32 个银行、64 位总线和循环存储布局，FIFO 数据容量为 8,192 字节。存储体、地址、使能、数据、掩码与两项输出寄存保持相同，接口周期不变。

## 完整结构测量

参考提交为 `eaba7635`。联合测量实例化实际 `oa_writer` 与完整 `vec_s8_to_fifo`，包含外层两项输出寄存，写回计数宽度为28位。参考与当前实现使用相同公共依赖、原语库和综合参数。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 原生映射逻辑 LUT | 3,002 | 2,740 |
| 原生映射 `co_current_bank` 至 `bank_count` | 12级 | 8级 |
| 原生映射 `bank_count` 至 `bank_count` | 13级 | 9级 |
| 原生映射 `co_row_limit_q` 至 `bank_count` | 13级 | 9级 |
| 原生映射全部 FIFO 同步端点的最长路径 | 13级 | 12级 |
| 物理成本映射逻辑 LUT | 2,788 | 2,572 |
| 物理成本映射 `co_current_bank` 至 `bank_count` | 13级 | 10级 |
| 物理成本映射 `bank_count` 至 `bank_count` | 13级 | 10级 |
| 物理成本映射 `co_row_limit_q` 至 `bank_count` | 13级 | 10级 |
| 物理成本映射全部 FIFO 同步端点的最长路径 | 13级 | 11级 |
| 触发器 | 1,057 | 1,057 |
| RAM LUT | 52 | 52 |
| RAMB18E1 | 8 | 8 |
| DSP48E1 | 0 | 0 |

物理成本映射减少216个逻辑LUT，FIFO各同步端点的路径均不超过15级。上述LUT数量为放置前原语计数。物理成本映射的联合模块最长路径为16级，位于 `oa_writer.cfg_is_mode` 至 `vec_valid_num_col_next_r`；本次修改文件为 `vec_s8_to_fifo.sv`。

`measurement.json` 同时保存 R18 固定源码 `3f78c674` 中 `co_current_bank` 至 `bank_count` 的18级完整SoC路径。完整SoC面积与时序由合入当前源码后的整机报告记录；150 MHz需要器件布局布线时序分析。

当前RTL文件的SHA256：

```text
7e195e9c28acd849d2ad16eed704af06480ac06da16e57d0484dee7c920dd6d7
```

## 功能验证

七组形式比较全部通过，合计检查10,493位控制状态、公开输出和存储读写端口。参数覆盖3、8、16、32个银行，32位与64位总线，循环与普通存储布局，以及FPGA与通用实现。外部输入和存储读数据不增加取值约束，存储模块源码保持相同。

实际FPGA分支完成16/32个银行与32/64位总线的四组逐周期比较。每组81个场景、12,392个输出字节，合计324个场景、49,568个输出字节。数据、掩码、有效信号、行切换、请求和满状态均与参考实现一致。

两份物理成本映射的功能比较均通过。报告收集程序核对源码与公共依赖、形式日志、数值日志、可执行文件、映射网表和路径文件的SHA256。

## 运行命令

```sh
python3 test/fifo_byte_rotation/run_formal.py \
  --reference eaba7635 --out build/fifo_bank_depth/formal
for banks in 16 32; do
  for bus in 32 64; do
    python3 test/writeback_cyclic/run.py --reference-rev eaba7635 \
      --banks "$banks" --bus-width "$bus" --fpga \
      --out "build/fifo_bank_depth/numeric${banks}_${bus}"
  done
done

python3 test/fifo_bank_depth/prepare_measurement.py \
  --reference eaba7635 --out build/fifo_bank_depth/wrapped_inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/fifo_bank_depth/wrapped_inputs/cases.json \
  --cases reference current --out build/fifo_bank_depth/wrapped_synthesis \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/fifo_bank_depth/measure_paths.py \
  --reference build/fifo_bank_depth/wrapped_synthesis/reference \
  --current build/fifo_bank_depth/wrapped_synthesis/current \
  --out build/fifo_bank_depth/wrapped_native_paths.json

for name in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "build/fifo_bank_depth/wrapped_synthesis/$name" \
    --out "build/fifo_bank_depth/wrapped_cost/$name" --mode physical-cost \
    --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
  ln -sfn "../../wrapped_synthesis/$name/pre_lut.il" \
    "build/fifo_bank_depth/wrapped_cost/$name/pre_lut.il"
done
python3 test/fifo_bank_depth/measure_paths.py \
  --reference build/fifo_bank_depth/wrapped_cost/reference \
  --current build/fifo_bank_depth/wrapped_cost/current \
  --out build/fifo_bank_depth/wrapped_cost_paths.json
python3 test/fifo_bank_depth/collect_report.py --results build/fifo_bank_depth
```
