# DMA 返回标签选择

`axi_dual_block_dma` 根据当前前端返回、窗口占用和卷积完成状态选择返回标签：

```systemverilog
((fe_wr_valid && !win_frontend_active) || conv_done_r)
    ? conv_tag_q : linear_response_tag
```

FPGA 实现对每个标签位使用一个 LUT6，五个有效输入分别为上述三个控制条件及两个候选标签位。第六输入固定为零，INIT 为 `64'hff0d_f200_ff0d_f200`。通用实现保留相同的条件表达式。全部标签位及无效周期的输出值保持原行为，没有增加寄存器或接口周期。

## 形式检查

`run_formal.py` 从参考提交和当前文件提取实际标签选择，核对其他源码完全相同，然后使用官方 LUT6 模型比较全部输出位。覆盖 `RD_TAG_WIDTH=1/2/3/4/7/8/16/32`，每个宽度分别检查通用和 FPGA 实现，共 16 组。三个控制输入和全部标签位均无约束，因此也覆盖窗口占用、前端返回和完成信号同时出现的组合，以及没有有效返回时的输出。

```sh
python3 test/dma_response_tag/run_formal.py --out build/dma_response_tag/formal
```

## 实际 DMA 测试

BUS32 和 BUS64 均使用完整 DMA、仲裁器及官方 FPGA 原语模型。每个配置完成 21 项任务、905 次检查，覆盖五个读客户端的启动前取消、等待地址接收时取消、完成与取消同时发生、已有事务按序排空、后续事务恢复、请求撤回和四个返回上下文同时占用。连续命令接收间隔保持两个周期。

```sh
python3 test/dma_read_permission/run_numeric.py --out build/dma_response_tag/numeric
```

## 局部映射

`prepare_measurement.py` 提取缓存响应错误数组选择、前端 `wr_valid`、DMA 返回标签以及仲裁器 `dw_raw_valid` 的实际表达式，并在输入和输出处放置寄存器。

| 映射配置 | 参考逻辑 LUT | 当前逻辑 LUT | FF | 最长组合级数 | 响应错误到向量返回有效 |
|---|---:|---:|---:|---:|---:|
| 原生 ABC9 | 10 | 9 | 25 → 25 | 5 → 4 | 5 → 4 |
| 生产 physical-cost | 8 | 7 | 25 → 25 | 5 → 5 | 5 → 5 |

生产成本映射通过 ABC9 功能等价检查。此表描述所列局部组合模块，完整 SoC 的资源及路径级数由整机测量记录。

```sh
python3 test/dma_response_tag/prepare_measurement.py --out build/dma_response_tag/local
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/dma_response_tag/local/cases.json --cases reference current \
  --out build/dma_response_tag/local/results \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock

for label in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "build/dma_response_tag/local/results/$label" \
    --out "build/dma_response_tag/cost/$label" --mode physical-cost \
    --delay-target-ps 6667 \
    --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
done

python3 test/dma_response_tag/collect_report.py --build build/dma_response_tag \
  --out test/dma_response_tag/measurement.json
```

`measurement.json` 保存同一份 RTL 的摘要、全部形式检查、实际 DMA 结果、局部路径、工具命令和文件 SHA256。收集程序重新核对源码、可执行文件、日志和映射输入。
