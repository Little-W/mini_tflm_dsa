# 权重描述符准备与接收检查

权重加载器并行计算地址匹配、尾部分块和 DMA 描述符，在 `ext_dma_start` 有效的接收边沿提交完整描述符。`load_weight_req` 直接选择已准备的描述符，仲裁授权参与接收控制。数据选择无需等待授权信号经过启动条件后再次返回描述符选择逻辑。

## 组合计算与状态准备

`add3_equal` 将三个操作数压缩为两个操作数，再调用 `add_equal` 检查各位进位与目标和值。比较保留参数指定的模加法位宽。控制器导出已有的列组起点、组内列偏移，以及分组地址、行偏移和列偏移寄存器，描述符匹配直接使用这些操作数。

`PF_EMPTY` 状态比较新预取候选，其他状态比较已保存的预取描述符。尾部分块条件分别检查行坐标和列组坐标，配置使用现有 `S_IDLE`、`S_INIT` 和 `S_RUN` 状态准备步长。列号比较使用平衡的相等与大小关系树。

`port_descriptor` 在请求有效时提供 `issue_descriptor`；已经启动的传输使用 `active_descriptor`。所有描述符字段在实际接收边沿与请求、授权及缓冲区状态一致。

## 形式检查

`run_acceptance_formal.py` 比较当前加载器与参考提交 `422090be`。两侧使用相同的当前控制器、缓冲区和组合辅助模块，比较全部时序状态、控制输出，以及 `ext_dma_start` 有效时的十项公开描述符字段。无接收事件时，描述符载荷不被消费者使用；相应比较输出置零，内部状态与控制输出仍持续比较。

证明对输入和握手不增加假设，覆盖以下三组参数：

| SIZE | COUNT_WIDTH | BUS_WIDTH | 已证明的状态和输出位 |
| ---: | ---: | ---: | ---: |
| 4 | 8 | 32 | 4,582 |
| 16 | 29 | 64 | 18,785 |
| 16 | 32 | 128 | 19,079 |

控制器的递增和比较由 [权重遍历检查](../kernel_traversal_depth/README.md) 独立验证。脚本记录实际源文件、参考文件、证明脚本和日志的 SHA256。

## 数值检查

生产参数 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29` 已完成 29,443 个周期，检查 285 个输出分块和 72,960 个数值。312 次 DMA 启动全部完成，覆盖 100 次预取、73 次缓存命中、25 次候选丢弃、12 次重叠启动和 1,649 个传输与输出重叠周期。

数值检查同时覆盖 INT8、INT16、im2col、尾部分块、缓存命中、在途命中、预测延迟和清空。仿真启用 C++ 未定义行为检查。

## 运行

```bash
python test/kernel_descriptor_timing/run_acceptance_formal.py \
  --reference 422090be --out build/kernel_descriptor_acceptance
python test/kernel_traversal_depth/run.py \
  --out build/kernel_traversal_depth
python test/kernel_prefetch/run.py \
  --bus-width 64 --count-width 29 --verilator verilator \
  --out build/kernel_descriptor_numeric
```

形式检查和数值检查分别记录输入文件摘要。完整 SoC 的最长组合路径由整机综合网表统计，加载器的局部结果不替代整机结果。
