# 窗口分区编号与有效位选择

`vector_window_bank_map` 为八个窗口存储分区同时计算循环起点及来源通道。三个比特的加法进位和减法借位使用并行布尔表达式，保留全部起点、列号余数和按八取模的结果。`vector_window_valid_mux` 保存每个半组的四路有效位选择层次。完整操作数存储模块继续按原有效条件更新地址寄存器，数据存储容量、读写周期及返回通道数量均保持不变。

```sh
python3 test/vector_window_bank_map/run.py --out build/vector_window_bank_map
```

验证包含普通编译和 `SYNTHESIS` 编译两种模式。每种模式对两个辅助模块分别穷举六个输入比特的全部四态组合，共执行 16384 次输出向量比较。完整 `vector_engine_operand_store` 与提交 `4f0fbf93` 进行逐周期形式等价证明，外部输入不受约束，比较全部公开输出。

生产配置采用 `p_tile=16`、`p_pe_count=8`、`p_window_lanes=8`、64 位总线与 DMA、共享量化和共享数据存储。按 6667 ps 延迟目标、300 ps 导线延迟权重及相同 LUT 资源权重映射，完整模块使用 2802 个逻辑 LUT、2825 个触发器。对应参考实现使用 2786 个逻辑 LUT、2825 个触发器。

下表统计公开输入到 `window_bank_index` 地址寄存器的数据及使能捕获端之间的最长组合单元数量。统计从输入端口开始，整机上游电路由完整 SoC 测量另行计入。

| 输入 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| `i_win_rsp_col` | 9 | 8 |
| `i_win_rsp_mask` | 5 | 4 |
| `i_window_response_fire` | 5 | 4 |
| `i_active` | 9 | 8 |

`validation.json` 保存验证结果与源文件 SHA-256。`measurement.json` 保存配置、完整模块资源统计和路径结果。
