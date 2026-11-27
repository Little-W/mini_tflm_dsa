# FIFO 合并输出的行结束判断

## 设计

对于不少于 8 个且数量为二的整数次幂的存储体，FIFO 分别保存各存储体完成写入时的有效行数。计数与原行数存储接收同一写入事件，原有 `bank_ready` 管理复位和释放后的有效性。每个存储体先比较当前行上限与有效行数，再通过固定四选一树选择当前存储体的行结束结果。

| 模块 | 作用 |
|---|---|
| `vec_s8_fifo_row_match` | 保存完成行数，并行比较各存储体的行结束条件，选择当前存储体结果 |
| `vec_s8_fifo_group_end` | 归并输出行、转置行、矩阵块行及所选存储体的结束条件 |
| `vec_s8_fifo_read_enable` | 并行准备普通输出和合并输出的读取请求，组结束状态在末级控制继续读取 |
| `vec_s8_to_fifo_full` | 连接上述结果，维护原有输出、存储体释放和读写状态 |

无效存储体按零行参与比较。有效位包含未知值时，先对完整行数进行条件合并，再比较行上限，保留四态运算规则。计数写入的未知使能和未知地址继续使用过程式 `if` 及数组写入的行为。

新的计数保存状态与原有效计数的关系参与完整时序归纳证明。模块公开端口和外部周期逐周期一致；其他存储体数量使用原有索引计数分支。所有存储和组合结构均由 RTL 推断。

## 验证

### 完整时序关系

18 组形式检查全部通过，包含 generic 和 FPGA 宏模式、1／3／8／16／32／64 个存储体、8／16 路向量、32／64 位总线，以及普通和循环存储布局。

验证同时比较全部公开输出、共同寄存状态、数据存储读写地址与使能、写数据、有效行数及新增并行计数关系。首个证明周期复位，后续复位与功能输入均无额外限制，数据存储读数据也无取值约束。全部配置在一个归纳步骤中完成证明。

### 四态行为

| 检查 | 配置 | 比较次数 |
|---|---|---:|
| 并行计数及行结束 | 8／16／32／64 个存储体，4／5／7 位计数，四种宏组合 | 1,613,936 |
| 组结束与读取使能 | 九项控制信号的全部四态组合，四种宏组合 | 1,048,576 |
| 合计 |  | 2,662,512 |

计数测试逐周期比较全部保存计数和输出结果，包含未知及高阻态的地址、数据、有效位和控制信号。组结束与读取使能测试枚举每项控制的零、一、未知和高阻态。

### 实际数值及周期

使用 Verilator 5.054 和完整数据存储，四组参数均通过原输出参考实现的逐周期比较。

| 存储体数量 | 总线宽度 | 场景数量 | 比较字节数 | 比较周期数 |
|---:|---:|---:|---:|---:|
| 16 | 32 | 81 | 12,392 | 7,196 |
| 16 | 64 | 81 | 12,392 | 4,522 |
| 32 | 32 | 81 | 12,392 | 7,196 |
| 32 | 64 | 81 | 12,392 | 4,522 |
| 合计 |  | 324 | 49,568 | 23,436 |

测试比较数据、字节掩码、有效信号、行切换、请求及容量状态，覆盖普通输出、转置、行合并和返回反压。全部公开输出保持相同周期。

## 完整写回与 FIFO 联合映射

测量实例化实际 `oa_writer`、外层 `vec_s8_to_fifo` 和内部数据存储，采用 16 路向量、32 个存储体、64 位总线、28 位写回计数、循环存储和预先计算的容量阈值。参考提交为 `8fe8b96991259ef9c7f0e18ad9fc326a1353fa8e`。

映射使用 6,667 ps 目标、300 ps 连线估计和最多八输入逻辑。全部保留层次在连接图中展开，路径统计从真实寄存器延伸到真实寄存器或存储端口。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 2,175 | 2,337 |
| LUTRAM 名义 LUT | 60 | 56 |
| 合计名义 LUT | 2,235 | 2,393 |
| 触发器 | 1,093 | 1,248 |
| DSP48E1 | 9 | 9 |
| RAMB18E1 | 8 | 8 |
| 最长寄存器间组合级数 | 11 | 10 |
| `co_current_bank` 到完成存储体计数 | 11 | 7 |
| `co_current_bank` 到数据存储端口 | 10 | 7 |
| `co_current_bank` 到任意实际终点 | 11 | 7 |
| `co_row_limit_q` 到任意实际终点 | 8 | 10 |
| `bank_ready` 到任意实际终点 | 11 | 9 |

新增并行计数和选择逻辑增加 158 个名义 LUT、155 个触发器。完整连接图无组合环路，所有路径均完成分类。目标器件布局布线后的建立时间裕量由整机时序分析确认。

`validation.json` 保存当前源码摘要、全部形式与四态结果、逐周期数值结果、资源数量和路径级数。

## 复现

```bash
python3 test/fifo_coalesced_row/run_formal.py --out build/fifo_coalesced_row/formal
python3 test/fifo_coalesced_row/run_four_state.py --out build/fifo_coalesced_row/four_state
python3 test/fifo_coalesced_row/check_controls.py --out build/fifo_coalesced_row/controls
python3 test/fifo_coalesced_row/run_cycle.py --banks 32 --bus-width 64 \
  --verilator "$VERILATOR_ROOT/bin/verilator" --out build/fifo_coalesced_row/cycle32_64
python3 test/fifo_coalesced_row/measure.py --out build/fifo_coalesced_row/mapping
python3 test/fifo_coalesced_row/inspect_paths.py \
  --reference-source build/fifo_coalesced_row/mapping/reference \
  --reference-mapped build/fifo_coalesced_row/mapping/reference_mapped \
  --current-source build/fifo_coalesced_row/mapping/current \
  --current-mapped build/fifo_coalesced_row/mapping/current_mapped \
  --out build/fifo_coalesced_row/paths
```
