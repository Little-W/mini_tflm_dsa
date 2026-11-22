# 公共算术与模块文件

公共算术模块使用明确位宽的普通 SystemVerilog 表达式。综合工具根据目标工艺选择实现资源。各模块的组合接口、结果位宽、输入进位和模运算语义由功能参数定义。

## 公共模块

| 模块 | 参数 | 功能 |
| --- | --- | --- |
| `add_equal` | `p_width` | 检查 `i_a + i_b + i_carry_in` 的低 `p_width` 位是否等于 `i_target` |
| `unsigned_compare` | `p_width` | 同时产生无符号小于与相等结果 |
| `onehot_check` | `p_width`、`p_allow_zero` | 检查一位置位；可配置同时接受零 |
| `parallel_prefix_add` | `p_width`、`p_group_width`、`p_preserve_groups` | 产生完整定宽和值与最高位进位 |
| `ia_ordered_coordinate_equal` | `p_width`、`p_low_width` | 比较定宽坐标和的高位，包含被省略低位产生的进位 |

`parallel_prefix_add` 的可综合主体为完整加法。仿真遇到 X/Z 输入时，使用分组进位产生和传播关系保留可确定的结果位；分组参数描述该四态传播关系。通用、ASIC 和 FPGA 编译配置采用相同的算术主体。`add_equal` 并行检查各位所需的进位与相邻低位实际产生的进位，再对逐位结果执行归约与。

## 独立模块文件

以下每个模块分别保存在同名 `.sv` 文件中。父模块保留公共端口，辅助模块保持原有信号连接、寄存边沿与参数含义。

| 目录 | 独立辅助模块 |
| --- | --- |
| `rtl/npu/dma` | `dma_register_buffer` |
| `rtl/npu/dma/cache` | `conv_read_cache_reference`、`conv_windowed_cache`、`conv_cache_rank_table` |
| `rtl/npu/loaders` | `ia_ordered_coordinate_equal`、`kernel_request_idle`、`kernel_candidate_equal`、`kernel_burst_encode`、`kernel_count_increment`、`kernel_count_compare`、`kernel_count_next_reaches` |
| `rtl/npu/buffers` | `shared_ram_read_mux`、`ia_ps_channel_ram`、`ps_buffer_wide_fifo`、`ps_buffer_exact_ram` |
| `rtl/npu/control` | `ps_scheduler_any`、`ps_scheduler_priority` |

17 个辅助模块和 8 个父模块共 25 个模块体均完成文件拆分前后的逐字核对。每个文件具有独立的网络类型设置；需要时间单位的共享存储模块保持原有时间单位。文件与模块的对应关系、模块体摘要及 35 个相关 RTL 文件的摘要保存在 [validation.json](validation.json)。

## 验证

公共算术及有序坐标比较的跨配置证明覆盖 1、3、8、17、24、32、33、47、48、64 位，以及 1、3、8 位分组和两种分组进位组织。30 组组合 SAT 比较均保持外部输入自由。四态比较执行 200,000 次，其中 61,988 次包含未知结果，逐位比较结果与通用四态参考表达式一致。

公共模块的独立入口另完成 170 组 SAT 与 435,296 次四态比较，包含 1 位和 2 位模加比较的全部四态输入、1 至 128 位的一位置位检查及 1 至 64 位的无符号比较。缓存状态与接口的专用验证参见 [缓存说明](../cache_bram_reset/README.md)，ASIC 列存储参见 [权重存储说明](../kernel_asic_storage/README.md)。完整 NPU 在 `SYNTHESIS`、`ASIC_SYNTHESIS`、`ASIC_SRAM`、`NPU_SIM_ASSERT` 同时启用时完成语法和接口检查。

```bash
python3 test/resource_neutral_arithmetic/run.py \
  --source-root . \
  --reference-root build/resource_neutral_cache/reference \
  --out build/resource_neutral_arithmetic

python3 test/add_equal/run_formal.py --out build/add_equal_formal
python3 test/add_equal/run_four_state.py --out build/add_equal_four_state
python3 test/add_equal/run_inferred.py --out build/add_equal_configurations
python3 test/parallel_prefix_add/run.py --out build/parallel_prefix_add
python3 test/parallel_prefix_add/run.py --asic --out build/parallel_prefix_add_asic
python3 test/unsigned_compare/run.py --out build/unsigned_compare
python3 test/config_onehot/run.py --out build/config_onehot
```

参考目录需要包含对应的公共算术模块及有序坐标比较模块。测试分别保存源码、比较模型、日志及摘要。完整设计的资源数量、组合级数和工作频率由同一源码的综合及静态时序报告给出。
