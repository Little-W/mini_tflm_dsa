# AI‑DSA MMA 计算单元：模块端口与操作约定（v0.1）

> 目标：为 `mma_top` 及其子模块（控制、加载、阵列、累加、重量化、FIFO 等）提供**端口定义**与**操作约定**。本规范优先面向硬件联调与驱动编写；语义以**有效/就绪**握手与**Tile 级调度**为核心。

---

## 0. 全局约定（Common Conventions）

以下约定已根据当前 `top/mma_top.sv` 的控制结构调整，便于各子模块与 `mma_controller` 的一致交互。

- 时序与复位
  - `clk` 上升沿有效。
  - 顶层复位信号为 `rst_n`（低有效）；个别子模块内部使用 `rstn` 命名（例如 `vec_requant`），接口上以顶层 `rst_n` 为准并在连接处统一转换。

- 寄存器与位宽约定
  - 所有基址、维度与步幅统一使用 `REG_WIDTH`（顶层默认 32 位），用于地址、零点、移位与乘数等控制寄存器（带符号或无符号按字段说明）。
  - 零点与量化参数在接口层面使用 signed `REG_WIDTH`（s32 表示），便于直接传递到子模块并避免窄化歧义。

- 控制模型（基于新的顶层）
  - 单次任务发起：上层将 `calc_start` 拉高 1 拍以启动一次完整的 MMA 任务；`sa_ready` 由控制器输出，表示接受下次任务。
  - 配置初始化：控制器对各子模块下发单拍配置脉冲 `init_cfg_*`（例如 `init_cfg_ia`, `init_cfg_weight`, `init_cfg_bias`, `init_cfg_requant`, `init_cfg_oa`），子模块在该拍锁存配置寄存器。
  - 模块发起访存请求：权重/IA/偏置/量化参数加载器等在需要时以 `load_*_req`（模块 -> 控制器）提出访存请求；控制器在合适时刻响应 `load_*_granted`（控制器 -> 模块）授权，从而避免总线冲突。
  - 触发/送出信号：对于一次发送流程（如逐行发送 IA 或 权重），控制器使用单拍触发 `send_*_trigger`；被触发模块在接收到 trigger 后按锁存参数开始逐周期发送，发送完成由模块发回 `*_sending_done`。
  - 单拍完成脉冲：一些关键完成事件（例如 `tile_calc_over`、`ia_calc_done`、`weight_sending_done`、`bias_loading_done`、`requant_out_valid`）均采用单拍脉冲或短脉冲语义便于控制器做边沿触发处理。

- 握手与流控语义
  - 触发类信号：`*_trigger` 为单拍有效脉冲，触发一次动作（配置、发送等）。
  - 请求/授权：`load_*_req` 与 `load_*_granted` 成对使用，模块提出请求后应等待控制器授权再进行总线事务（授权通常为 1 或多拍，视控制策略）。
  - 流式数据：采用 `valid/ready` 模型（如 ICB 命令/响应握手、FIFO 输出握手等），只有当 `valid & ready` 同时为 1 时视为数据被采样。
  - 完成类指示：`*_done` / `*_sending_done` / `tile_calc_over` 等用于标识阶段结束或单次事务完成，控制器常用其边沿来驱动下一步（如写回或加载下一个 Tile）。

- ICB 与多路复用
  - 顶层使用 `icb_mux_5to1` 进行 ICB 主口多路复用，`mma_controller` 通过 `icb_sel[2:0]` 选择当前活跃的子模块。子模块均实现 ICB Master 语义（`icb_cmd_m_t` / `icb_cmd_s_t` / `icb_rsp_s_t` / `icb_rsp_m_t`）。
  - 顶层外部接口为 `sa_icb_cmd` / `sa_icb_cmd_ready` / `sa_icb_rsp` / `sa_icb_rsp_ready`，多路器负责将活跃子模块的命令映射到外部总线并将响应路由回对应子模块。
  - ICB 命令/响应为结构体类型（见 `inc/icb_types.svh`），包含 `addr`, `read`, `wdata`, `wmask`, `size` 等字段。子模块需要按规定设置 `size`（当前代码中固定为 2'b10 对应 32-bit 事务）。

- 数据宽度与对齐
  - 总线事务基于 `BUS_WIDTH`（顶层默认 32 位）。打包与写回以 32-bit 对齐，`vec_s8_to_fifo` 提供 `output_mask` 与 `output_data` 以生成 ICB 写掩码与数据。

- 数值域与量化
  - IA：`DATA_WIDTH`（默认 16 位，s16）；权重：`WEIGHT_WIDTH`（默认 8 位，s8）；累加器与偏置在 s32 域内计算。
  - 量化参数：per‑tensor 使用 `q_mult_pt/q_shift_pt`（signed `REG_WIDTH`）；per‑channel 时控制器将提供基址 `q_mult_pc_base/q_shift_pc_base`，`vec_requant` 在 per‑channel 模式下可自主读取并加载参数。

- Tile 与边界处理
  - 控制器以 `SIZE×SIZE` 切 Tile，并为边界 Tile 提供 `valid_row_num` / `valid_col_num` / `fifo_vec_valid_num_col` 等字段用于屏蔽与掩码生成。
  - 超出有效范围的位置在输出侧用 0 填充，或在生成掩码时屏蔽写入字节。

- 信号命名后一致性与模块差异说明
  - 顶层与多数子模块使用 `rst_n` 为复位命名；个别子模块使用 `rstn`，接口文档在模块段落中已注明。
  - 顶层将 `sa_icb_*` 作为统一主端口并通过 `icb_mux_5to1` 将其分发到子模块，子模块在文档中标注为拥有 ICB Master 接口（但实际上被顶层多路复用）。

---

## 1. 顶层：`mma_top`

**参数**

* `WEIGHT_WIDTH=8`，`DATA_WIDTH=16`，`SIZE=16`，`BUS_WIDTH=32`，`REG_WIDTH=32`。

**外部接口（摘要）**

| 端口 | 方向 | 位宽 / 类型 | 描述 |
| ---- | ---- | ---: | ---- |
| `clk` | In | 1 | 系统时钟（上升沿有效）。 |
| `rst_n` | In | 1 | 异步复位，低有效。 |
| `calc_start` | In | 1 | 触发一轮完整的 MMA 任务（单拍）。 |
| `sa_ready` | Out | 1 | 系统空闲/可接收下一任务（控制器输出）。 |
| `lhs_base` | In | `REG_WIDTH` | LHS 基址（字节地址，MULT_LHS_PTR）。 |
| `rhs_base` | In | `REG_WIDTH` | RHS 基址（字节地址，MULT_RHS_PTR，RHS 为 s8，N×K row‑major）。 |
| `dst_base` | In | `REG_WIDTH` | DST 基址（字节地址，MULT_DST_PTR）。 |
| `bias_base` | In | `REG_WIDTH` | bias 基址（s32，0 表示无 bias，MULT_BIAS_PTR）。 |
| `lhs_zp` | In | signed `REG_WIDTH` | LHS 零点（s32，MULT_LHS_OFFSET）。 |
| `rhs_zp` | In | signed `REG_WIDTH` | RHS 零点（s32，MULT_RHS_OFFSET）。 |
| `dst_zp` | In | signed `REG_WIDTH` | DST 零点（s32）。 |
| `q_mult_pt` | In | signed `REG_WIDTH` | per‑tensor multiplier（MULT_DST_MULT）。 |
| `q_shift_pt` | In | signed `REG_WIDTH` | per‑tensor right shift（MULT_DST_SHIFT，+N => >>N）。 |
| `use_per_channel` | In | 1 | 1：每通道量化；0：整张量量化。 |
| `k` | In | `REG_WIDTH` | K 维长度（MULT_RHS_COLS）。 |
| `n` | In | `REG_WIDTH` | N 维长度（MULT_RHS_ROWS）。 |
| `m` | In | `REG_WIDTH` | M 维长度（MULT_LHS_ROWS）。 |
| `lhs_row_stride_b` | In | `REG_WIDTH` | LHS 行跨度（字节，MULT_LHS_COLS_OFFSET）。 |
| `dst_row_stride_b` | In | `REG_WIDTH` | DST 行跨度（字节，MULT_ROW_ADDR_OFFSET）。 |
| `rhs_row_stride_b` | In | `REG_WIDTH` | RHS 行跨度（字节，MULT_RHS_ROW_STRIDE）。 |
| `act_min` | In | signed `REG_WIDTH` | 激活裁剪下限（s32，MULT_ACT_MIN）。 |
| `act_max` | In | signed `REG_WIDTH` | 激活裁剪上限（s32，MULT_ACT_MAX）。 |
| `sa_icb_cmd` | Out | `icb_cmd_m_t` | ICB 主命令端口：master -> slave 的命令负载（写/读请求）。 |
| `sa_icb_cmd_ready` | In | `icb_cmd_s_t` | ICB 从端就绪：slave -> master 的命令 ready 响应。 |
| `sa_icb_rsp` | In | `icb_rsp_s_t` | ICB 从端响应负载：slave -> master 的响应数据。 |
| `sa_icb_rsp_ready` | Out | `icb_rsp_m_t` | ICB 主端响应就绪：master -> slave 的响应 ready 信号。 |

**操作流程（高层）**

1. `calc_start` 置位 1 个周期；`sa_ready` 置 0，进入忙态。
2. 控制器分块：按 `SIZE×SIZE` 切 Tile，并为边界 Tile 设置 `valid_row_num/valid_col_num`。
3. 依次完成：权重加载 → IA 加载 → 脉动阵列计算/累加 & 加 bias → Requant → FIFO 打包 → 写回 DST。
4. 所有 Tile 完成后，`sa_ready` 置 1。

---

## 2. 控制器：`mma_controller`

**端口（与 `sub_modules/mma_controller.sv` 保持一致，已对齐顶层实例）**

| 端口                                | 方向  | 位宽 / 类型 | 描述 |
| --------------------------------- | --- | ----------: | ---- |
| `clk` / `rst_n`                   | In  | 1 / 1       | 时钟 / 异步复位（低有效）。 |
| `calc_start`                      | In  | 1           | 触发一轮 MMA 任务（单拍）。 |
| `sa_ready`                        | Out | 1           | 系统空闲指示（控制器就绪）。 |
| `tile_calc_over`                  | In  | 1           | 来自 `accumulator_array` 的 Tile 完成单拍脉冲（用于触发下一阶段）。 |
| `partial_sum_calc_over`           | In  | 1           | 累加器的部分和完成
| `icb_sel`                         | Out | [2:0]       | ICB 多路复用器选择（驱动 `icb_mux_5to1`）。 |
| `init_cfg_ia` / `init_cfg_weight` / `init_cfg_bias` / `init_cfg_requant` / `init_cfg_oa` | Out | 1 each | 向各子模块发出的单拍配置初始化脉冲。 |
| `need_bias` / `ia_use_offset` / `use_16bits` | Out | 1 each | 配置控制信号：是否使用 bias、是否对 IA 做零点补偿、是否走 16‑bit 路径。 |
| `tile_count`                      | Out | `REG_WIDTH` | 当前 Tile 计数（驱动 OA 写回地址计算等）。 |

-- IA Loader 接口 --
| `load_ia_req`                     | In  | 1           | IA 模块申请访存授权（模块发起）。 |
| `load_ia_granted`                 | Out | 1           | 控制器授权 IA 访存。 |
| `send_ia_trigger`                 | Out | 1           | 触发 IA 模块开始逐行发送 Tile（单拍）。 |
| `ia_sending_done`                 | In  | 1           | IA 模块逐行发送完成指示。 |
| `ia_row_valid`                    | In  | 1           | IA 当前行向量输出有效（供 data_setup 使用）。 |
| `ia_is_init_data`                 | In  | 1           | IA 指示本 Tile 是否为累加序列的首个（用于清零累加器）。 |
| `ia_calc_done`                    | In  | 1           | IA 表示计算触发/本 Tile 行流结束（供累加器等使用）。 |
| `ia_data_valid`                   | In  | 1           | IA 已完成当前 Tile 的所有行读取并可用于发送的指示。 |

-- Weight Loader 接口 --
| `load_weight_req`                 | In  | 1           | 权重模块申请访存授权（模块发起）。 |
| `load_weight_granted`             | Out | 1           | 控制器授权权重访存。 |
| `send_weight_trigger`             | Out | 1           | 触发权重模块逐行发送到阵列（单拍）。 |
| `weight_sending_done`             | In  | 1           | 权重逐行发送完成指示。 |
| `weight_data_valid`               | In  | 1           | 权重已预加载并可用于发送的指示。 |

-- Bias Loader 接口 --
| `load_bias_req`                   | In  | 1           | 偏置模块申请访存授权（模块发起）。 |
| `load_bias_granted`               | Out | 1           | 控制器授权偏置访存。 |
| `bias_valid`                      | In  | 1           | 偏置数据已准备好可被使用。 |

-- Requant 接口 --
| `load_quant_req`                  | In  | 1           | `vec_requant` 请求加载量化参数（per‑channel）。 |
| `load_quant_granted`              | Out | 1           | 控制器授权量化参数访存。 |
| `quant_params_valid`              | In  | 1           | `vec_requant` 表示量化参数已有效。 |
| `requant_out_valid`               | In  | 1           | `vec_requant` 输出量化结果有效（供 FIFO/写回）。 |

-- FIFO / OA Writer 接口 --
| `fifo_full_flag`                  | In  | 1           | FIFO 已满指示，控制器用于流量控制。 |
| `write_oa_req`                    | Out | 1           | 控制器向 OA 写回单元请求写回权限。 |
| `write_oa_granted`                | In  | 1           | OA 写回单元授权写回。 |
| `write_done`                      | In  | 1           | OA 写回完成指示。 |
| `oa_calc_over`                    | In  | 1           | OA 层表示写回阶段/Tile 写回结束（供控制器推进任务）。 |

### 设计约定

- 职责概述：`mma_controller` 作为全局调度器，负责（1）按 Tile 策略迭代 m/n/k，产生边界参数（`valid_*`）；（2）按优先策略仲裁子模块的访存请求 `load_*_req` 并下发 `load_*_granted`；（3）下发各子模块单拍初始化脉冲 `init_cfg_*` 与单拍发送触发 `send_*_trigger`；（4）驱动 `icb_sel` 选择 ICB 多路复用器通道并管理写回节奏。

- 初始化与配置
  - 所有配置信息（基址、步幅、零点、量化基址等）由控制器在接收到 `calc_start` 后按 Tile 先后通过单拍 `init_cfg_*` 发送给子模块，子模块在该拍内部锁存。
  - `calc_start` 为单拍脉冲；控制器在开始任务前将 `sa_ready` 置 0，任务完成后置 1。

- 访存请求/授权（load_*_req / load_*_granted）
  - 子模块在需要访问外部内存时发 `load_*_req` 并保持直到收到 `load_*_granted`。控制器根据当前阶段与优先级决定何时响应授权。
  - 授权到位后，子模块应在得到授权的周期或随后周期发起 ICB 命令（经由 `icb_mux_5to1` 与顶层 `sa_icb_*`）。
  - 控制器保证在切换 `icb_sel` 前所选通道的未完成事务已被安全终结（依据 ICB 的 `cmd_ready` / `rsp_valid` 语义）。

  - 触发/发送序列（send_*_trigger 与 *_sending_done）
  - 控制器使用 `send_*_trigger`（单拍）启动模块的逐行发送过程（IA / weight 等）；模块在发送完成后回报 `*_sending_done`。
  - `send_*_trigger` 与 `load_*_granted` 的配合是常见模式：先授权模块完成预取，再触发发送以保证数据就绪。

- Tile 级调度与累加/写回
  - `tile_calc_over`（来自累加器）为 Tile 级别完成指示：控制器以其边沿作为触发点进行写回（OA）授权或加载下一个 Tile 的权重/偏置。
  - 对于 K 方向分片（分多次累加），控制器通过 `acc_is_init_data` 控制累加器清零，仅在首个 IA Tile 时置 1。

- FIFO 与写回流量控制
  - 控制器以 `fifo_output_req` / `fifo_req_ack` 协调 FIFO 的出队；在实际写回前监控 `fifo_full_flag` 与 ICB `cmd_ready` 以避免总线拥塞。
  - 写回事务的 `sa_icb_cmd_wmask` 与 `fifo_output_mask` 直接映射，控制器负责按 `dst_row_stride_b`/`dst_base` 生成正确的写地址并发出写命令。

- ICB 多路复用与仲裁
  - 控制器通过 `icb_sel` 指明哪个子模块拥有主口权限；被选中子模块的 `icb_cmd_m` 会映射到 `sa_icb_cmd`。
  - 在高并发场景下，控制器应实现简单优先或轮询策略以避免某一子模块长期饥饿（实现细节可由控制器状态机决定）。

- 错误与异常处理
  - 若 `sa_icb_rsp` 返回错误标志，控制器应记录错误并进入安全态（可选择中断任务、重试或上报主机）；同时暂停后续授权与触发直到错误被清理。

- 时序与约定总结
  - 所有单拍触发信号（`init_cfg_*`, `send_*_trigger`）仅在一个周期内有效；模块应在该周期内捕获并锁存必要寄存器。
  - 所有请求型信号（`load_*_req`, `output_req` 等）应保持直到收到对应的响应或授权（`*_granted`, `req_ack`）。
  - 控制器对关键边沿（例如 `tile_calc_over`, `ia_calc_done`）使用下降或上升边沿检测以驱动下一个阶段，保证无竞争的阶段切换。

## 3. 权重加载：`kernel_loader`

**端口（与 `sub_modules/kernel_loader.sv` 保持一致）**

| 端口                         | 方向  | 位宽 / 类型 | 描述 |
| -------------------------- | --- | ----------: | ---- |
| `clk` / `rst_n`            | In  | 1 / 1       | 时钟 / 复位。 |
| `init_cfg`                 | In  | 1           | 配置锁存单拍触发。 |
| `load_weight_req`          | Out | 1           | 向控制器申请下一批权重访存（模块发起）。 |
| `load_weight_granted`      | In  | 1           | 控制器授权权重访存。 |
| `send_weight_trigger`      | In  | 1           | 控制器触发权重逐行发送（单拍）。 |
| `k` / `n` / `m`            | In  | `REG_WIDTH` | 矩阵维度参数（init_cfg 时锁存）。 |
| `rhs_zp`                   | In  | signed `REG_WIDTH` | 权重零点。 |
| `rhs_base` / `rhs_row_stride_b` | In | `REG_WIDTH` | 权重基址与行跨度（字节）。 |
| ICB 主接口                  | Out/In | `icb_cmd_m_t` / `icb_cmd_s_t` / `icb_rsp_s_t` / `icb_rsp_m_t` | 自主发起权重访存的 ICB Master 接口。 |
| `weight_sending_done`      | Out | 1           | 权重逐行发送完成指示。 |
| `store_weight_req`         | Out | 1           | 与 `weight_out` 同拍，控制阵列锁存权重。 |
| `weight_out[SIZE]`         | Out | `DATA_WIDTH` (s8) | 并行行输出到脉动阵列（按行输出）。 |
| `weight_data_valid`        | Out | 1           | 当前 Tile 的权重已预加载并可发送。 |


### 实现细则与设计约定（参考）

- 权重加载模块（kernel_loader）设计约定：

  1. **分块与存储格式**
     - 权重矩阵按列主序（column-major）存储，模块需按列优先读取并在内部缓冲区重排为按行输出。
     - 每次加载的 Weight Tile 为 k 行 × SIZE 列，边界 Tile 不足部分需补零或屏蔽。

  2. **地址生成与访存**
     - init_cfg 时锁存基地址、行/列跨度等参数。
     - 访存地址计算遵循：`tile_base = rhs_base + tile_col * col_stride + tile_row * row_stride`。
     - 支持按列块读取，内部缓冲区完成转置，保证输出为 row-major。

  3. **自动重触发与流水**
     - 每次 Weight Tile 发送完成后自动申请下一块权重（load_weight_req=1），获授权（load_weight_granted）后开始下一次读取。
     - 保证权重在多个 IA Tile 间复用，流水不中断。

  4. **输出与握手**
     - weight_out[SIZE] 与 store_weight_req 同步输出，表示当前周期数据有效。
     - weight_data_valid=1 表示当前 Weight Tile 已准备好可发送。
     - weight_sending_done=1 表示本 Tile 发送全部完成。

  5. **ICB 事务与错误处理**
     - 作为 ICB Master 发起读请求，严格遵循 ready/valid 握手。
     - 响应错误时进入错误处理分支并上报主控。

  6. **边界与补零**
     - 对于边界 Tile，输出无效元素需补零或按掩码屏蔽，保证阵列计算正确。

  7. **时序与流控**
     - 所有输出信号与数据保持严格同步，避免竞态。
     - 发送流程与控制器授权流程解耦，保证流水连续性。

  8. **复位与初始化**
     - 复位时清空所有内部状态与缓冲区，等待 init_cfg 重新配置。

  9. **扩展性**
     - 支持不同 SIZE、K、N 参数，适配多种矩阵尺寸。

  10. **与控制器交互**
      - 所有请求/授权/触发信号保持单拍脉冲语义，严格遵循顶层协议。

## 4. IA 加载：`ia_loader`

**端口（与 `sub_modules/ia_loader.sv` 保持一致）**

| 端口                         | 方向  | 位宽 / 类型 | 描述 |
| -------------------------- | --- | ----------: | ---- |
| `clk` / `rst_n`            | In  | 1 / 1       | 时钟 / 复位。 |
| `init_cfg`                 | In  | 1           | 配置锁存单拍触发。 |
| `load_ia_req`              | Out | 1           | 向控制器申请下一次 IA 访存授权（模块发起）。 |
| `load_ia_granted`          | In  | 1           | 控制器授权 IA 访存。 |
| `send_ia_trigger`          | In  | 1           | 控制器触发发送已经缓存的 IA Tile（单拍）。 |
| `k` / `n` / `m`            | In  | `REG_WIDTH` | 矩阵维度参数（init_cfg 时锁存）。 |
| `lhs_zp`                   | In  | signed `REG_WIDTH` | IA 零点（s32）。 |
| `lhs_row_stride_b` / `lhs_base` | In | `REG_WIDTH` | IA 基址与行跨度（字节）。 |
| `ia_use_offset` / `use_16bits` | In | 1 each    | 是否做零点补偿、是否使用 16-bit 路径。 |
| ICB 主接口                  | Out/In | `icb_cmd_m_t` / `icb_cmd_s_t` / `icb_rsp_s_t` / `icb_rsp_m_t` | 自主发起 IA 访存的 ICB Master 接口。 |
| `ia_sending_done`          | Out | 1           | 逐行发送完成指示（send 完结）。 |
| `ia_row_valid`             | Out | 1           | 当前行输出有效指示（与 `ia_out` 同步）。 |
| `ia_is_init_data`          | Out | 1           | 本 Tile 是否为累加序列的第一个 IA Tile。 |
| `ia_calc_done`             | Out | 1           | 本 Tile 的输出能触发最终累加（最后一次用于 OA 的部分和）。 |
| `ia_out[SIZE]`             | Out | `DATA_WIDTH` (signed) | 并行行向量输出至 `data_setup`。 |
| `ia_data_valid`            | Out | 1           | 内部已完成当前 Tile 的全部行读取并可用于发送。 |
### 设计约定

- **自主访存与Tile重用**
  - ia_loader模块自主维护IA Tile的访存与重用流程，无需外部逐步驱动，保证流水线高效。
  - 每个IA Tile在与不同Weight Tile配合时可重复使用，模块内部通过reuse计数器跟踪复用次数，只有在需要新Tile时才发起访存。

- **访存授权与握手**
  - 访存流程通过load_ia_req（模块发起）和load_ia_granted（控制器授权）完成，模块在需要新Tile时拉高load_ia_req，收到授权后进入LOAD状态。
  - 访存期间严格遵循ICB ready/valid握手协议，确保数据完整性和总线安全。

- **配置与参数锁存**
  - 所有关键参数（k、n、m、lhs_base、lhs_row_stride_b、lhs_zp、ia_use_offset、use_16bits）在init_cfg单拍脉冲时锁存，后续流程均使用锁存值。
  - Tile分块参数（ia_tiles_per_oa_row、weight_tiles_per_oa_col）在配置阶段计算并锁存。

- **数据缓存与输出**
  - 访存得到的IA Tile数据缓存于内部缓冲区，保证发送阶段可连续逐行输出。
  - ia_data_valid=1表示Tile已准备好可发送，send_ia_trigger收到后进入SEND状态，逐行输出ia_out并同步ia_row_valid。
  - ia_sending_done在Tile全部行发送完成后拉高，通知外部流程可进入下一阶段。

- **边界处理与补零**
  - 对于边界Tile，实际有效行/列不足SIZE时，模块在访存和输出阶段补零，保证输出宽度一致。
  - 完全无效行/列可跳过访存，部分有效则补零填充，ia_row_valid在输出周期内始终同步有效。

- **同步信号语义**
  - ia_row_valid与ia_out同步，表示当前周期输出数据有效。
  - ia_data_valid与ia_calc_done同步，表示Tile已准备好且可用于最终累加。
  - ia_is_init_data在首个Tile的有效周期内拉高，供下游累加器清零判断。
  - 所有同步信号在输出周期内保持一致，避免采样竞态。

- **时序与流控**
  - 访存、发送、重用流程通过内部状态机自动切换，保证流水线连续性。
  - 所有请求/授权/触发信号保持单拍脉冲语义，严格遵循顶层协议。

- **扩展性与参数化**
  - 支持不同SIZE、K、N参数，适配多种矩阵尺寸与分块策略。
  - 设计可扩展至更大Tile或多级缓存结构。

- **与控制器交互**
  - 所有请求/授权/触发信号与控制器保持严格时序和语义一致性，保证系统整体调度正确。

## 5. 数据对齐：`data_setup`

**端口（与 `sub_modules/data_setup.sv` 保持一致，已对齐顶层实例）**

| 端口               | 方向  | 位宽 / 类型 | 描述 |
| ------------------ | --- | ----------: | ---- |
| `clk`              | In  | 1           | 时钟。 |
| `data_in[SIZE]`    | In  | `DATA_WIDTH` | 来自 `ia_loader` 的并行向量（顶层连接名：ia_out）。 |
| `data_out[SIZE]`   | Out | `DATA_WIDTH` | 对齐后输出到阵列（顶层连接名：data_setup_out）。 |
| `input_valid_i`    | In  | 1           | 输入有效（顶层连接名：ia_row_valid）。 |
| `calc_done_i`      | In  | 1           | 输入完成（顶层连接名：ia_calc_done）。 |
| `is_init_data_i`   | In  | 1           | 输入是否为初始化（清零）数据（顶层连接名：ia_is_init_data）。 |
| `input_valid_o`    | Out | 1           | 延迟对齐后的输入有效（顶层连接名：data_setup_input_valid，连接到 accumulator_array.input_valid_i）。 |
| `calc_done_o`      | Out | 1           | 延迟对齐后的批次完成（顶层连接名：data_setup_calc_done，连接到 accumulator_array.calc_done_i）。 |
| `is_init_data_o`   | Out | 1           | 延迟对齐后的初始化指示（顶层连接名：data_setup_is_init_data，连接到 accumulator_array.is_init_data_i）。 |

### 设计约定（data_setup 模块）

- 模块实现数据与控制信号的同步延时链，适用于类似 TPU 的斜对齐（diagonalization）场景。
- 输入数据与控制信号按参数 DATA_NUM 指定的周期数进行延时；每个 data_out 对应特定的延时阶段。
- 第一个 data_out 始终为当前输入；后续输出为输入的延迟版本，以实现对角线对齐。
- 控制信号（`input_valid`、`calc_done`、`is_init_data`）延迟 `DATA_NUM-1` 周期以与相应的数据输出同步；当 `DATA_NUM == 1` 时，控制信号直接透传，无需延时。
- 模块参数化支持可配置的数据位宽与延时长度，便于在更大数据处理流水线中扩展集成。
- 所有延时均在 `clk` 的上升沿同步实现，保证时序一致性与语义正确性。

## 6. 脉动阵列：`ws_systolic_array`

**端口（与 `basic/ws_systolic_array.sv` / `basic/ws_systolic_cell.sv` 保持一致）**

| 端口             | 方向  | 位宽 / 类型 | 描述 |
| ---------------- | --- | ----------: | ---- |
| `clk`            | In  | 1           | 时钟。 |
| `store_weight_req`| In | 1           | 与 `weight_out` 同拍，阵列锁存权重到 PE 寄存器。 |
| `weight_in[SIZE]`| In  | signed [WEIGHT_WIDTH-1:0] | 列向并行权重流（每元素对应一行）。 |
| `data_in[SIZE]`  | In  | signed [DATA_WIDTH-1:0] | 行向量并行 IA 流。 |
| `sum_in[SIZE]`   | In  | signed [31:0] | 来自累加器/上一阶段的部分和反馈（可用于初始偏置）。 |
| `sum_out[SIZE]`  | Out | signed [31:0] | 每列的部分和/累加输出。 |

### 设计约定（ws_systolic_array 模块）

- 模块为 SIZE×SIZE 的脉动阵列（systolic array），数据沿行方向传播，权重沿列方向传播，部分和沿列向累加反馈到下游累加器。
- 权重锁存信号 `store_weight_req` 与 `weight_out` 同拍：当该信号为高时，各 PE 应在本周期锁存输入权重到本地寄存器以供后续周期使用。该信号通常为单拍触发以减少控制复杂度。
- 每个 PE 遵循 ws_systolic_cell 的接口约定（接收 data_in、weight_in、sum_in，输出 data_out、weight_out、sum_out），顶层保证向单元提供已对齐的输入信号与数据。
- `sum_in` 提供来自上一行的部分和或初始偏置；最底行的 `sum_out`（文档中映射为 sum_out[col]）汇出到 accumulator_array 进行列级累加与后处理。
- 边界处理：对边界 Tile 或不足的行/列，应由上游加载器（weight_loader / ia_loader）在输出端做好补零或掩码处理；阵列内部不做自动扩展或动态掩蔽假设。
- 参数化与扩展性：模块基于参数 SIZE 生成阵列结构，支持不同尺寸的扩展；实现应确保寄生路径与时序在目标工艺下满足要求。
- 时序与复位：所有数据路径与控制信号在 `clk` 上同步采样，模块假定外部复位已对各单元进行初始化（通过 PE 内部复位或外部控制）。
- 接口语义约定：输入的数据/权重/部分和应在 cycle 边界保持稳定直至被阵列内部寄存器采样；控制信号（如 `store_weight_req`）应与数据流同步以保证无竞争采样。

## 7. 累加阵列：`accumulator_array`

**端口（与 `sub_modules/accumulator_array.sv` 保持一致，已对齐顶层实例）**

| 端口               | 方向  | 位宽 / 类型 | 描述 |
| ------------------ | --- | ----------: | ---- |
| `clk`              | In  | 1           | 时钟。 |
| `data_in[SIZE]`    | In  | signed [31:0] | 来自脉动阵列的列向部分和（顶层连接名：sa_sum_out）。 |
| `input_valid_i`    | In  | 1           | 数据列有效（顶层连接名：data_setup_input_valid，由 data_setup 提供）。 |
| `calc_done_i`      | In  | 1           | 批次流结束信号（顶层连接名：data_setup_calc_done，由 data_setup 提供）。 |
| `is_init_data_i`   | In  | 1           | 是否为初始化写入（清零累加器）（顶层连接名：data_setup_is_init_data，由 data_setup 提供）。 |
| `data_out[SIZE]`   | Out | signed [31:0] | 输出到下游模块（顶层连接名：acc_data_out，作为 vec_requant 的输入）。 |
| `partial_sum_calc_over` | Out | 1       | K 方向分片的部分和完成指示（顶层连接名：partial_sum_calc_over，供控制器调度使用）。 |
| `tile_calc_over_o` | Out | 1           | 单拍脉冲，指示 Tile 级计算结束（顶层连接名：tile_calc_over，供 mma_controller 使用）。 |


## 8. 偏置加载： `bias_loader`

**端口（与 `sub_modules/bias_loader.sv` 保持一致）**

| 端口                         | 方向  | 位宽 / 类型 | 描述 |
| -------------------------- | --- | ----------: | ---- |
| `clk` / `rst_n`            | In  | 1 / 1       | 时钟 / 复位。 |
| `init_cfg`                 | In  | 1           | 配置锁存单拍触发（锁存 `need_bias` / `bias_base` 等）。 |
| `load_bias_req`            | Out | 1           | 向控制器申请下一批偏置访存。 |
| `load_bias_granted`        | In  | 1           | 控制器授权偏置访存。 |
| `need_bias`                | In  | 1           | 是否执行偏置加法。 |
| `bias_base`                | In  | `REG_WIDTH` | bias 基址（字节）。 |
| `k` / `m`                  | In  | `REG_WIDTH` | 矩阵尺寸（用于地址计算）。 |
| ICB 主接口                 | Out/In | `icb_cmd_m_t` / `icb_cmd_s_t` / `icb_rsp_s_t` / `icb_rsp_m_t` | 自主发起偏置访存的 ICB Master 接口。 |
| `ia_loader_calc_done`      | In  | 1           | 来自 IA Loader 的 calc_done 同步信号（用于触发重载节拍）。 |
| `tile_calc_start`          | In  | 1           | 上层开始 Tile 计算（用于清零/准备）。 |
| `bias_valid`               | Out | 1           | 偏置已准备好可被使用。 |
| `data_out[SIZE]`           | Out | signed [31:0] | 按列对齐的偏置向量，供加法使用。 |

### 设计约定（bias_loader 模块，自主访存版本）

- 设计目标
  - 模块自主读取偏置 Tile，并在读取完成后缓存偏置并通知上层（bias_valid），支持流水化的自动重触发以保持计算连续性。
  - 在需要时为累加输出提供逐元素偏置加法支持，或在无需偏置时跳过访存以节省带宽。

- 主要信号与语义
  - init_cfg（单拍）：锁存配置参数（need_bias、cfg_output_channels、cfg_bias_base、tile_stride 等）。
  - bias_valid：偏置 Tile 已缓存完成并可被使用；在 tile_calc_start 到来时在安全时序点清零以准备下一轮。
  - load_bias_req / load_bias_granted：请求/授权语义；模块在需要新 Tile 时保持 load_bias_req 直到收到 load_bias_granted。
  - ia_loader_calc_done：作为触发点（使用下降沿检测）启动重触发计时逻辑。
  - tile_calc_start：上层开始本 Tile 计算，模块应在此时清理 bias_valid，避免旧数据被误用。

- 地址生成与访存策略
  - init_cfg 时锁存 cfg_bias_base、cfg_output_channels 与 tile_stride 等参数。
  - 每个 Tile 的基址按约定计算：tile_base = cfg_bias_base + tile_idx * tile_stride（tile_idx 由控制/本模块维护）。
  - 支持按块或分片发起 ICB 读请求，读取有效 bias 元素后写入内部 bias_buffer[]；对不足的位使用 0 填充。

- 自动重触发逻辑
  - 采用 ia_loader_calc_done 的下降沿作为重触发起点：在检测到 1->0 边沿后启动 delay_counter（例如 SIZE-1 周期），计数完成后驱动 load_bias_req=1。
  - delay_counter 给予上层和阵列缓冲/写回时间，避免在下降沿瞬间发起访存造成资源冲突。
  - 收到 load_bias_granted 后进入 LOAD 状态，按握手完成 ICB 读事务并在完成后置 bias_valid=1。
  - 若 need_bias==0，可直接跳过 LOAD 流程并将 bias_valid 置为已准备或保持为0（以系统约定为准）。

- tile_calc_start 与 bias_valid 的关系
  - bias_valid 在 LOAD 完成后置 1；上层在检测到 bias_valid=1 后可安全开始使用偏置。
  - 在 tile_calc_start（下一个 Tile 开始）到来时，模块应在受控时序点清零 bias_valid 并准备下一轮加载。

- 边界与补零策略
  - 对于最后一个 Tile 中输出通道数不足的情况，内部 bias_buffer 应对超出部分填 0；可在地址计算时跳过无效块以节省总线带宽，但必须保证输出宽度一致。
  - 对完全无效的 Tile，可不发起实际访存并直接填充对应输出区为 0。

- ICB 与错误处理
  - 作为 ICB Master 发起读请求，严格遵循 icb_cmd_m / icb_cmd_s ready/valid 与 icb_rsp_s 的响应握手。
  - 对响应错误码需实现错误检测路径：可选择上报控制器、重试或进入安全态，且在错误清理前暂停后续 load 请求。

- 推荐实现要点
  - 使用 ia_calc_done_d 寄存器阵列检测 ia_loader_calc_done 下降沿，基于下降沿启动 delay_counter。
  - 维护 tile_idx、cur_bias_addr、load_count 等状态用于地址计算与逐块读取。
  - bias_buffer 应具有足够宽度（至少 SIZE 或 cfg_output_channels）并支持按需填充 0。
  - 确保 bias_valid 的清零由 tile_calc_start 在安全时序点完成以避免竞态。
  - 在实现中明确状态机（IDLE / WAIT_FOR_IA_DONE / DELAY / REQUEST_LOAD / LOAD / DONE）以便可验证的时序行为。

- 行为总结（流程）
  1) init_cfg：锁存配置参数；若 need_bias=1，则准备首次读取流程。
  2) WAIT_FOR_IA_DONE：监测 ia_loader_calc_done 的下降沿以作为重触发起点。
  3) DELAY：下降沿触发后执行固定周期延迟（例如 SIZE-1），以避开竞态窗口。
  4) REQUEST_LOAD：延迟完成后驱动 load_bias_req，等待 load_bias_granted。
  5) LOAD：授权到位后发起 ICB 读事务并缓存偏置，完成后置 bias_valid=1。
  6) USE_AND_CLEAR：上层使用偏置完成后在 tile_calc_start 时清零 bias_valid，模块回到 WAIT_FOR_IA_DONE 准备下一轮。

## 9. 向量量化/限幅：`vec_requant`

**端口（与 `sub_modules/vec_requant.sv` 保持一致）**

| 端口                             | 方向  | 位宽 / 类型 | 描述 |
| ------------------------------ | --- | ----------: | ---- |
| `clk` / `rstn`                 | In  | 1 / 1       | 时钟 / 复位（注意顶层为 `rst_n`，模块内使用 `rstn`）。 |
| `init_cfg`                     | In  | 1           | 装载公共量化参数（激活阈值、dst_offset）。 |
| `cfg_per_channel`              | In  | 1           | 1=per-channel，0=per-tensor。 |
| `activation_min_in/max_in`     | In  | signed [31:0] | 激活裁剪范围。 |
| `dst_offset_in`                | In  | signed [31:0] | 输出零点。 |
| `multiplier_in` / `shift_in`   | In  | signed [31:0] | per-tensor 参数值或 per-channel 基址。 |
| `load_quant_req`               | Out | 1           | 申请加载 per-channel 参数（仅 per-channel 使用）。 |
| `load_quant_granted`           | In  | 1           | 授权加载量化参数。 |
| `quant_params_valid`           | Out | 1           | 量化参数已加载并可用。 |
| `k` / `m`                      | In  | `REG_WIDTH` | 矩阵尺寸（用于参数加载与分组）。 |
| ICB 主接口                     | Out/In | `icb_cmd_m_t` / `icb_cmd_s_t` / `icb_rsp_s_t` / `icb_rsp_m_t` | per-channel 模式下用于读取每通道参数。 |
| `in_valid` / `in_vec_s32[VLEN]`| In  | 1 / VLEN×32 | 并行 s32 向量输入。 |
| `out_valid` / `out_vec_s8[VLEN]`| Out | 1 / VLEN×8 | 并行 s8 量化输出。 |

### 设计约定（vec_requant 模块，自主访存与 per-channel 支持）

- 设计目标
  - 并行对向量执行量化缩放（移位、乘法高位取整、右移四舍五入、加偏移、激活裁剪），兼容 CMSIS‑NN 风格算法。
  - 支持 per‑tensor（全局参数）与 per‑channel（每通道参数）两种模式；per‑channel 模式下可作为 ICB Master 自主访存参数以保证流水连续性。

- 主要信号与语义
  - `init_cfg`：一拍锁存配置（mode、activation_min/max、dst_offset、multiplier/shift 或其基址、输出通道数等）。
  - `cfg_per_channel`：0=per‑tensor（直接使用输入参数），1=per‑channel（参数来自访存）。
  - `load_quant_req` / `load_quant_granted`：请求/授权加载 per‑channel 参数，避免总线冲突。
  - `quant_params_valid`：当前通道/块的量化参数已就绪并可被使用；在安全时刻被上层 `tile_calc_start` 或约定信号清零。
  - ICB 接口：模块为 Master 时发起读请求并处理 `icb_cmd_s.ready` / `icb_rsp_s`。

- per‑channel 访存与地址推断策略
  - 在 `init_cfg` 时锁存参数基址与输出通道数，按 OA Tile 宽度或 VLEN 推断每次需读的参数数量（通常为 VLEN）。
  - 每次读地址步进：next_addr = base + read_count * VLEN * sizeof(param)。
  - 模块维护 `current_param_addr`、`load_count`、`ch_multiplier_r[]`/`ch_shift_r[]`，按授权发起连续 ICB 读并在全部响应到位后置 `quant_params_valid=1`。

- 自动重触发与完成检测
  - 通过捕捉 `in_valid` 的下降沿或上层显式的 `tile_calc_start` 判断 OA Tile 完成。
  - 若为 per‑channel 且有未加载参数，检测到 Tile 完成后自动驱动 `load_quant_req=1`，外部授权后开始下一批参数读取。
  - `quant_params_valid` 在参数加载完成后保持为 1，直到收到 `tile_calc_start`（或协议约定的清除信号）时清零以准备下一轮。

- 时序与握手要点
  - `load_quant_req` 必须在安全延迟后申请，`load_quant_granted` 到位才发起 ICB 事务。
  - ICB 读事务需正确处理 `icb_cmd_s.ready` 与 `icb_rsp_s`，对响应中的错误标志做处理或上报。
  - `quant_params_valid` 与数据输入/输出的握手关系必须在接口文档中明确（即何时可开始用这些参数计算，何时上层应清除）。

- 行为阶段总结
  1) init_cfg：锁存配置；per‑channel 模式下准备首次参数加载。  
  2) LOAD（per‑channel）：根据 `current_param_addr` 与 VLEN 发起 ICB 读，读完写入本地缓存并置 `quant_params_valid=1`。  
  3) COMPUTE：在 `in_valid` 上升并且 `quant_params_valid=1` 时并行量化输出，`out_valid` 与数据对齐。  
  4) TILE_COMPLETE：检测 `in_valid` 下降或 `tile_calc_start`，清理/重置并在必要时驱动下次 `load_quant_req`。

- 实现注意事项
  - 为避免竞态，`quant_params_valid` 在同一时钟域内置1，并由 `tile_calc_start` 在安全时刻清零。
  - 最后一组参数若不足 VLEN，应在内部用默认值（或复制/填零）填充，或在使用时屏蔽超出通道的计算。
  - 仿真需覆盖 per‑tensor 与 per‑channel 时序、`load_quant_req/granted` 交互及 ICB 错误路径。
  - 推荐使用延迟寄存器检测下降沿并用小状态机管理 LOAD/WAIT/COMPUTE/ERROR 状态，便于可观测与验证。

## 10. 向量到 FIFO：`vec_s8_to_fifo`

**端口（与 `sub_modules/vec_s8_to_fifo.sv` 保持一致）**

| 端口                          | 方向  | 位宽 / 类型 | 描述 |
| --------------------------- | --- | ----------: | ---- |
| `clk` / `rstn`              | In  | 1 / 1       | 时钟 / 复位。 |
| `in_valid`                  | In  | 1           | 输入向量有效（来自 vec_requant，连续高电平，下降沿为批次结束）。 |
| `in_vec_s8[VLEN]`           | In  | VLEN×8      | 并行 s8 向量输入（来自 `vec_requant`）。 |
| `output_req`                | Out | 1           | 模块向外部（oa_writer 或控制器仲裁单元）请求输出数据（top 中为 vec_s8_to_fifo 的输出信号 fifo_output_req）。 |
| `vec_valid_num_col`         | Out | ⌈log2(VLEN)⌉ | 本次向量中有效列数（由 vec_s8_to_fifo 产生，top 中作为共享信号传递给 oa_writer）。 |
| `output_valid`              | Out | 1           | 打包的 32-bit 数据有效。 |
| `output_switch_row`         | Out | 1           | 读区切换指示（每个批次结束）。 |
| `output_ready`              | In  | 1           | 接收方（oa_writer 或控制逻辑）就绪接受输出。 |
| `output_mask`               | Out | [3:0]       | 字节掩码（与 32-bit 写掩码对齐）。 |
| `output_data`               | Out | [31:0]      | 打包的写回数据（32-bit）。 |
| `fifo_full_flag`            | Out | 1           | FIFO 满指示，控制器应进行流量控制（top 中连接给 mma_controller）。 |

### 设计约定（vec_s8_to_fifo 模块）

- 设计目标
  - 将并行 s8 向量打包为 32‑bit 写回数据并生成对应字节掩码，通过双区（Ping‑Pong）FIFO 实现高吞吐的读写分离与连续流处理。

- 双区 FIFO 与数据存储
  - 采用两区轮换（Ping‑Pong），每区容量为 VLEN×VLEN（或按实现缩放），写满一区后切换到另一区写入，读区与写区可并行工作以提高吞吐。
  - 写指针与读指针分离；区域切换仅在批次结束（in_valid 下降沿 / is_last_vec）或读写完成后发生以避免冲突。

- 数据流与状态机
  - 输入阶段：在 in_valid 高电平期间连续接收 in_vec_s8，按周期将数据写入当前写区；检测到 in_valid 下降沿视为批次结束并触发写区切换准备输出。
  - 输出阶段：模块在有数据时拉高 output_req，请求主机确认（req_ack 与 vec_valid_num_col 一起有效），锁存有效字节数后进入 OUTPUT 流程，按 4 字节一组打包输出。
  - 状态机示例：IDLE（无数据）-> WRITE（接收并写入）-> WAIT_REQ（批次结束，等待主机确认）-> OUTPUT（按掩码/数据输出）-> SWITCH（切区）-> IDLE/WRITE。

- 握手与时序要点
  - 请求确认：output_req 发出后必须等待 req_ack 与 vec_valid_num_col 同周期有效；模块在该周期锁存 vec_valid_num_col。
  - 输出传输：采用标准 output_valid / output_ready 握手；每次输出携带 4 位 output_mask 与 32 位 output_data（合并为 36 位语义）。
  - output_ptr 从 0 递增到 (VLEN/4 - 1)，覆盖当前读区中所有需输出的 32‑bit 数据。
  - 区域切换：仅在批次结束且当前读区已完全输出或在写区写满且读区已空时安全切换。

- 接口语义与约束
  - in_valid：高电平期间写指针递增并写入数据；下降沿表示批次结束（is_last_vec），触发读区准备及 output_req。
  - vec_valid_num_col：由主机在 req_ack 同周期提供，表示当前向量中有效列数（用于生成最后一 32‑bit 的 output_mask）。
  - req_ack 必须与 vec_valid_num_col 同时有效；否则模块不得开始输出流程。
  - fifo_full_flag：当两区均被占用且无法切换时置 1，用于上层背压或暂停输入。

- 数据格式与掩码
  - 每次输出包含 4 字节打包为 32‑bit 数据，output_mask[3:0] 表示每字节有效性（1=有效）；例如 4'b1111 表示全部有效，4'b0111 表示低三字节有效。
  - 对于最后一组不足 4 字节的情形，应按 vec_valid_num_col 生成相应 output_mask 并以 0 填充无效字节以保证对齐写回。

- 实现建议与注意事项
  - 保持写区与读区的元数据同步（例如每区的有效字数、写满标志、已读计数），以避免切区时的数据竞态。
  - 在设计中使用显式的边沿检测寄存器捕捉 in_valid 下降沿与 req_ack 同步，以保证状态机可重现的时序行为。
  - 仔细处理复位与空闲情形：复位应清空所有指针、计数器与区状态，避免假象的 fifo_full_flag。
  - 仿真需覆盖边界条件：部分有效列、连续多批次切换、req_ack 延迟或丢失、以及 fifo_full_flag 触发情况。