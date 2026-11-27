# im2col 前端设计与验证

前端接收卷积配置和 IA 分块描述符，生成按矩阵行列排列的十六位输入数据。INT8 输入在读取后加入配置偏移量，INT16 输入直接传递。窗口缓存、预取、输出背压和描述符排队使用同一套公开接口。

## 模块职责

| 文件 | 职责与寄存边界 |
|---|---|
| `conv_im2col_frontend.sv` | 接收任务配置，调度坐标准备、地址形成和输出传输；保存配置与当前分块上下文。 |
| `conv_im2col_geometry.sv` | 共享配置和运行期乘法，计算坐标、历史位置、通道纪元与地址增量。配置计算分为四个阶段，32×16 乘积通过两路 16×16 部分积寄存后合并。 |
| `conv_im2col_descriptor.sv` | 准备并保存分块描述符，计算窗口关系及提交坐标，选择提交时的地址增量。 |
| `conv_descriptor_read_state.sv` | 保存准备项的首字请求归属和单拍范围，比较寄存请求标签并取消重复读取。 |
| `conv_descriptor_word_status.sv` | 提交时保存首字与保存字、运行字的命中关系和填充状态，当前响应先更新运行字来源。 |
| `conv_im2col_row_request.sv` | 保存下一输出行的地址、像素索引、输入行坐标和填充资格。行推进时使用两步候选，连续输出保持地址寄存边界。 |
| `conv_im2col_request_context.sv` | 并行选择请求地址、窗口索引、通道纪元和输入行坐标，统一正式请求与预读使用的元数据。 |
| `conv_im2col_stream.sv` | 保存输出地址、通道范围和字内范围，生成逐通道输出掩码及缓存请求。1～16 通道共用范围寄存与固定步长选择结构。 |
| `conv_im2col_prefetch.sv` | 保存一份预取上下文，分阶段计算横纵坐标、像素和字节地址，最后发出预取请求。 |
| `conv_im2col_frontend_pkg.sv` | 定义共享状态编码。 |
| `include/conv_im2col_prepared_tile.svh` | 定义各阶段共用的描述符字段；`kernel_x` 和 `kernel_y` 各为 16 位。 |

历史位置在 `P_HISTORY` 保存范围判断和行列候选。坐标减法先保存低位及借位，再形成高位坐标。地址计算依次保存像素乘积、组合后的地址项和通道地址；`ADDRESS_MATCH` 使用已保存的地址判断缓存字命中。数据与对应控制字段在同一阶段更新。

初始通道组位置在配置准备阶段一保存，使用已寄存的配置通道数。配置与地址步长完成前保持分块接收关闭，运行阶段可以直接使用已准备的组位置。阶段关系使用实际运行寄存器与实际组地址表达式进行两步无界归纳检查，覆盖任意配置数值和描述符更新。

通道纪元计算直接使用输出模块生成的独热步长选择，传输数量另行编码并保留原有用途。配置阶段只向调度模块传递乘积低 32 位，同时保留完整 48 位乘积用于溢出检查。

普通 tile 地址排列由调用接口决定。前端输出的十六位数据可以交给 IA 存储路径选择存储格式。

## 描述符准备与缓存读取

寄存描述符保留一个准备项和一个运行项。运行项只剩最后一拍时，准备队列可以接收后续描述符，与当前读取等待或输出背压并行。准备项保存请求状态、数据字标签和单拍资格，提交边沿把请求归属转交给运行项。

后续首字请求须保持数据的使用顺序。准备队列已有一项时，只有该项能够在一个输出拍内完成，且其首字已经请求或可复用，才允许后续项提前读取。相邻项的首字候选进入请求寄存器时，同时保存前一准备项的标签和复用资格。下一周期比较两份寄存标签，匹配时取消该候选并释放请求寄存器，准备项转为复用已有数据字。提交时同步清除已取消请求的返回依赖，随后检查实际保存字和运行字标签。多个输出拍的描述符在提交后按运行地址发出后续读取。

首字地址标签随准备项保存；提交边沿完成保存字及运行字的标签比较，并保存对应填充状态。检查周期直接读取这些寄存标志，输出格式与状态更新同时保存。当前响应与提交同周期时，运行字命中比较使用本次响应的地址。运行字与当前首字的标签分别完成比较，转发状态只选择末级匹配结果。检查周期能够直接输出已保存的数据或填充值，数据、有效位、行列位置和后续状态在背压期间保持稳定。错误状态继续接收已进入缓存的需求响应，等待需求队列清空后接收下一配置。

缓存预读地址、窗口索引和有效位在请求保存边沿一起寄存，缓存范围检查与候选地址计算分别位于寄存器两侧。正式请求使用相同的完整地址和元数据，输出停顿时保留已保存请求。需求容量为一或二时，缓存均可使用先前准备的预读结果返回或保存响应。

跨行请求使用提前保存的下一行上下文。行内等待期间保存一步候选；输出行推进或连续空间分块提交时保存两步候选。两步候选分别处理列内推进、换行一次和输出宽度为一的两次换行。三种候选并行完成地址和边界计算，输出列比较只选择最终结果。请求地址、窗口索引、输入行坐标和填充资格在同一边沿更新，随后可以与当前输出的接收同时发出下一次读取。

## 数值与协议检查

```bash
python3 test/frontend_pipeline/run_numeric.py \
  --target fpga --cache-response-depth 2 --size 16 --lanes 16 --bus-width 64 \
  --cache-sets 16 --cache-ways 2 --line-bytes 128 \
  --narrow-mode 2 --windowed --prefetch \
  --out build/frontend_pipeline/numeric16

python3 test/frontend_pipeline/run_numeric.py \
  --target fpga --cache-response-depth 2 --size 16 --lanes 8 --bus-width 64 \
  --cache-sets 16 --cache-ways 2 --line-bytes 128 \
  --narrow-mode 2 --windowed --prefetch \
  --out build/frontend_pipeline/numeric8

python3 test/frontend_pipeline/run_numeric.py \
  --target fpga --register-descriptor 0 --size 4 --lanes 2 --bus-width 32 \
  --cache-sets 4 --cache-ways 2 --line-bytes 16 \
  --narrow-mode 2 --prefetch \
  --out build/frontend_pipeline/numeric_direct4
```

每种配置使用直接卷积方程生成 42 项任务的期望数据，并执行 1024 组配置检查。输入描述符、AXI 请求与响应、输出接收均施加随机等待。检查项目包括数据、槽位、行列位置、通道掩码、最后一拍、错误响应，以及背压期间的输出稳定性。

| 配置 | 任务数 | 周期数 | 描述符接收数 | 正常完成数 | 提交与接收同周期次数 | 输出拍数 |
|---|---:|---:|---:|---:|---:|---:|
| FPGA 宏、16×16、16 通道、窗口与预取、需求容量 2 | 42 | 128742 | 2160 | 2159 | 1404 | 21838 |
| FPGA 宏、16×16、8 通道、窗口与预取、需求容量 2 | 42 | 144428 | 2160 | 2159 | 1404 | 26728 |

每种配置包含一个预期 AXI 错误任务。两种配置合计通过 84 项任务、273170 个周期和 2048 组配置检查。请求顺序检查独立保存每个已接受需求的地址，响应被使用时核对运行地址；数据、输出元数据和背压稳定性同时检查。行请求断言逐周期比较已保存候选与运行项直接计算的地址、像素索引、输入行坐标及填充标志。

`--source-root` 可以指定独立的源码目录。脚本补齐模块依赖和头文件搜索目录，记录全部 RTL 输入及共享头文件的 SHA-256，并检查运行期间这些文件是否发生变化。编译采用一个进程，定时仿真使用 C++20。

## 形式与四态检查

```bash
python3 test/conv_frontend/tools/check_epoch_shared.py \
  --out build/frontend_pipeline/epoch

python3 test/frontend_group_feedback/check.py \
  --out build/frontend_pipeline/group

python3 test/conv_frontend/tools/check_history_delta.py \
  --source-root . --out build/frontend_pipeline/history

python3 test/frontend_pipeline/check_epoch_selection.py \
  --source-root . --out build/frontend_pipeline/epoch_selection

python3 test/frontend_pipeline/check_request_context.py \
  --out build/frontend_pipeline/request_context

python3 test/frontend_pipeline/check_row_request.py \
  --out build/frontend_pipeline/row_request

python3 test/frontend_pipeline/check_cfg_group.py \
  --out build/frontend_pipeline/cfg_group

python3 test/frontend_pipeline/check_cfg_phase.py \
  --out build/frontend_pipeline/cfg_phase

python3 test/frontend_pipeline/check_descriptor_commit.py \
  --out build/frontend_pipeline/descriptor_commit

python3 test/frontend_pipeline/check_word_status.py \
  --out build/frontend_pipeline/word_status

python3 test/frontend_pipeline/measure_descriptor_commit.py \
  --out build/frontend_pipeline/descriptor_commit_mapping

python3 test/frontend_pipeline/check_word_forward.py \
  --out build/frontend_pipeline/word_forward

python3 test/frontend_pipeline/check_descriptor_read_state.py \
  --out build/frontend_pipeline/descriptor_read_state
```

| 检查对象 | 输入范围与性质 | 结果 |
|---|---|---|
| 通道纪元计算 | 1～16 通道；完整 16 位组偏移和通道位置；传输数量为零至通道总数。 | 16 项形式证明通过。 |
| 独热步长选择 | 1～16 通道；实际输出掩码满足连续前缀性质；同时检查纪元结果和传输数量。 | 16 项形式证明通过。 |
| 通道范围与行末条件 | 1～16 通道；完整 16 位通道回绕；4/8 通道窄输出选择；连续与通用掩码选择。 | 166 项形式证明通过。 |
| 行末四态逻辑 | 1、2、4、8、16 通道；逐位生成 0、1、X、Z。 | 500000 次比较通过。 |
| 描述符提交模块 | 33、35、40 位坐标；寄存和直接模式；完整描述符与全部配置输入。 | 6 项完整输出形式比较与 8192 次四态比较通过。 |
| 描述符读取归属 | 4、8、16 字节数据字；8、16 通道；4、8 个窄输出通道；使能和直接配置。 | 15 项时序归纳、32768 次四态比较及接受、保持、同时提交覆盖通过。 |
| 描述符字状态 | 28、29、30 位标签；任意提交、保存字、运行字和响应更新。 | 3 项两步无界归纳与 16384 次四态比较通过。 |
| 配置跨组位置 | 完整 32 位归约起点与 16 位组宽度；33 位结果保留最高进位。 | 1 项形式证明与 16384 次四态比较通过。 |
| 行请求候选与寄存器 | 33、35、40 位坐标；完整字节与像素索引；参考模型逐次推进两个输出位置。 | 3 项形式证明与 8192 次完整寄存器四态比较通过。 |
| 请求上下文 | 33、35、40 位坐标；16、128 字节缓存行；两种描述符配置；1943 位完整四态输入。 | 12 项完整输出形式证明与 8192 次逐位四态比较通过。 |
| 历史位置 | 完整 32 位位置、33 位位置差、完整 16 位输出宽度；配置、提交与历史保存事件互斥。 | 两步复位检查和一步无界归纳通过。 |

历史位置检查包含行范围、上限溢出和两个模行尾等式。历史上限只输出所需的进位，运算保留完整位置范围。

## 纪元选择逻辑的局部映射

`check_epoch_selection.py` 从实际 RTL 提取表达式，使用相同的输入、输出寄存器和传输数量输出，对十六通道纪元选择逻辑执行启用 `SYNTHESIS=1` 与 `XILINX_FPGA=1` 的 xc7 映射。连续前缀掩码性质同时由数值回归中的协议断言检查。

| 指标 | 传输数量编码后求和 | 直接使用独热步长 |
|---|---:|---:|
| LUT | 48 | 171 |
| CARRY4 | 5 | 26 |
| 寄存器位 | 71 | 71 |
| 最长组合单元级数 | 9 | 8 |
| 输出掩码到纪元的组合单元级数 | 9 | 6 |

这些结果仅覆盖独立的纪元选择逻辑，属于布局前映射。级数包含映射后的 LUT 与进位单元；完整 SoC 的 150 MHz 时序及资源总量由综合和实现报告确定。

## 行请求模块的局部映射

`check_row_request.py` 对实际行请求模块加入输入和输出寄存器后执行 xc7 ABC9 映射。35 位坐标配置使用 902 个逻辑 LUT、0 个 DSP48E1，最长寄存器之间组合路径为 10 级。两步边界条件和地址结果均在原有寄存边沿保存，输出与请求周期保持一致。完整 SoC 的总资源与布局后时序另行测量。

## 描述符提交坐标的局部映射

提交坐标把输入进位编码到低段操作数，两段加法同时计算。高段分组独立使用低段进位，完整坐标保留原有提交周期。8 通道、35 位坐标配置使用物理 LUT 成本和 6.667 ns ABC9 目标进行布局前映射。

| 指标 | 分段和值再修正输入进位 | 输入进位编码后并行修正高段 |
|---|---:|---:|
| 完整提交模块逻辑 LUT | 602 | 626 |
| DSP48E1 | 4 | 4 |
| 坐标输出最长组合级数 | 9 | 7 |
| 模块全部输出最长组合级数 | 10 | 10 |

## RTL 结构统计

```bash
python3 test/frontend_pipeline/measure_structure.py \
  --out build/frontend_pipeline/structure
```

脚本使用 16×16、16 通道、64 位总线、16 组缓存、每行 128 字节的配置，报告展开后的寄存器位数和算术运算规模。器件 LUT、标准单元面积和时序由对应综合及实现工具报告。

算术和结构统计见 [validation.json](validation.json)。当前描述符读取状态、84 项数值检查、两个完整算子与包含缓存的前端映射见 [descriptor_read_state_validation.json](descriptor_read_state_validation.json)。

## 请求索引的寄存位置

`conv_request_index_register` 在原有请求保存边沿记录未缩放的像素位置，以及由短像素模式确定的有效右移位数。动态移位在寄存器之后完成，地址候选计算和像素来源选择在寄存器之前完成。写入使能与请求地址及其他元数据一致，缓存停顿时保存同一个请求。请求发送周期保持不变。

`check_index_register.py` 连接完整的 `conv_im2col_request_context`，以原边沿保存的完整索引作为参考，对坐标宽度 33、35、40 位，缓存行 16、128 字节及两种描述符模式执行 12 组无输入限制的时序归纳证明。三种编译配置共检查 24,576 组四态输入及写入停顿。刺激向量由实际展开端口计算为 1,943 位，每一位均覆盖 0、1、X、Z，保存、保持和未知写入使能分别统计。完整前端的数值和周期结果由对应提交的性能报告记录。详细输入摘要和结果保存在 [index_register_validation.json](index_register_validation.json)。

```bash
python3 test/frontend_pipeline/check_index_register.py --out build/frontend_pipeline/index_register
python3 test/frontend_pipeline/measure_frontend.py --out build/frontend_pipeline/mapped_soc8
```

`measure_frontend.py` 使用 SoC 的实际 8 通道、64 位读取、4 KiB 缓存和两项需求队列参数，检查包含缓存的完整前端寄存器连接图。

## 数据字转发比较

`check_word_forward.py` 检查运行字和描述符首字的并行标签比较。读取字宽度覆盖 4、8、16 字节，直接、寄存和提前读取模式分别检查转发的两种确定取值，共 18 组完整输出证明；另完成 24576 组四态比较，覆盖全部候选地址和公开匹配输出。

四态检查先展开每个输入字段的实际位宽，再以明确的正整数生成刺激向量。仿真再次核对连接总宽度，并逐位统计 0、1、X、Z，只有全部输入位均覆盖四种值才记录通过结果。标签转发、行请求、描述符提交的输入向量分别为 409、732、1819 位，详细统计保存在各项验证记录中。

## 描述符范围和数据字比较

五位通道余量保留低三位和高两位的并行比较边界；坐标区间按三位分组比较低十六位；数据字标签把低段进位放在完整等值归并的末级。各项均保持原有请求、提交和输出周期。数据字比较通过 18 组完整输出证明和 24576 次四态比较；8 通道前端通过 42 项任务及 1024 项配置检查，总周期为 144428。完整前端参数、输入摘要和映射结果见 [descriptor_control_validation.json](descriptor_control_validation.json)。

## 请求像素与纪元选择

`conv_request_pixel_select` 将十个描述符像素候选分成四组，运行时的行、卷积核位置和当前像素独立归并，末级同时选择来源与完整结果。请求纪元保留各组归并结果，继续使用原有请求保存边沿。完整请求上下文的 12 组形式比较与 8192 组四态比较通过；相连的索引保存模块通过 12 组时序归纳及三种编译配置共 24576 组四态比较。每组刺激覆盖全部 1943 个输入位的 0、1、X、Z。详细结果见 [request_pixel_selection_validation.json](request_pixel_selection_validation.json)。

解码末项比较按相邻两位检查加一关系，再分组归并完整结果。`check_increment_equal.py` 覆盖 1 至 64 位的 13 种宽度、直接归并和每组六项比较结果的归并；每种宽度完成无输入限制的形式证明、16384 组四态刺激及全部输入位的四种状态覆盖。结果见 [decode_increment_validation.json](decode_increment_validation.json)。

## 独立算术与共享操作数检查

以下入口直接读取现有模块，并自动展开实例依赖。算术和准备元数据检查包含 9 组配置，共享乘法器操作数及窗口目标保存关系包含 9 组配置，描述符首字匹配包含 28 组字宽与寄存配置。详细结果见 [public_entry_validation.json](public_entry_validation.json)。

```bash
python3 test/frontend_pipeline/check_arithmetic.py --source-root . --out build/frontend_pipeline/arithmetic
python3 test/frontend_pipeline/check_shared.py --source-root . --out build/frontend_pipeline/shared
python3 test/frontend_pipeline/check_direct.py --source-root . --out build/frontend_pipeline/direct
python3 test/conv_descriptor_timing/check_increment_equal.py --out build/frontend_pipeline/decode_increment
```

## 完整算术与窗口目标检查

```bash
python3 test/frontend_pipeline/check_critical_paths.py \
  --out build/frontend_pipeline/critical_arithmetic

python3 test/frontend_pipeline/check_window_match.py \
  --out build/frontend_pipeline/window_match

python3 test/frontend_address_arithmetic/run.py \
  --out build/frontend_pipeline/address_and_prefetch
```

`check_critical_paths.py` 直接实例化 `conv_descriptor_addresses` 的公开行字匹配接口，并展开实际模块依赖。坐标宽度覆盖 33、35、40 位，字地址移位覆盖 1～7 位。预取横向数学模型包含低位准备、低位和值及高位进位修正，检查两阶段合成后的完整定宽关系；真实预取阶段由 `frontend_address_arithmetic/run.py` 对完整模块状态和全部输出进行检查。

`check_window_match.py` 按配置保存、窗口准备和描述符查询顺序推进实际目标寄存器。三个目标均保留 33 位结果；直接描述符模式同时保存位置资格。配置更新使旧窗口失效，窗口准备和目标值使用同一时钟边沿。形式检查包含配置上下文、已保存目标、位置资格及匹配结果，覆盖两种描述符模式和普通、FPGA 两种编译方式。四态运行检查两种描述符模式的匹配和有效结果，在时钟边沿前后分别比较，并统计配置、准备、保持和三个目标的成功匹配。

| 入口 | 形式检查 | 四态范围 | 结果比较 |
|---|---:|---|---:|
| 完整坐标、移动、行地址与横向预取算术 | 14 组 | 320 位输入，41,280 个向量 | 371,520 次 |
| 窗口目标保存与查询 | 4 组无界归纳 | 131 位输入，120,526 个周期 | 482,104 次 |

两个入口均逐位覆盖 `0`、`1`、`X`、`Z`。窗口运行完成 7,500 次配置、7,500 次准备和 105,000 个有效保持周期；三个目标的成功匹配次数分别为 30,026、36,035、36,041。生成的寄存器测量模块保留实际窗口状态，并检查四个测量入口均可编译。详细结果见 [critical_arithmetic_validation.json](critical_arithmetic_validation.json) 和 [window_match_validation.json](window_match_validation.json)。

## 描述符候选与流式接收

描述符地址先分别计算十种来源与运行字、保存字的匹配关系，再由互斥来源选择位形成首字复用结果。固定字步长同样先比较保存标签，描述符转发条件只选择最终结果。填充判断分别检查坐标范围，并使用独立的候选选择。

接收条件将空闲阶段、输出末拍和提前准备分开计算，列末及快速复用标志参与最后的组合选择。短通道剩余数量采用分组借位，范围与数据格式提前准备。配置、描述符、缓存请求和输出的寄存边沿保持一致。

`check_descriptor_selection.py` 包含完整标签匹配、固定步长、坐标范围、借位、接收资格和填充选择的 54 项形式证明，以及 442368 次四态比较。每个输入位均覆盖 0、1、X、Z。8 通道、64 位总线、4 KiB 缓存和两项需求队列配置完成 42 项数值任务及 1024 项配置检查，总周期为 144428。完整候选地址、来源译码与保存字转发连接在 4、8、16 字节配置下通过 3 项形式证明和 49152 次四态比较；请求上下文通过 12 项形式证明及 8192 次四态比较。详细参数和源码摘要见 [descriptor_parallel_validation.json](descriptor_parallel_validation.json)。

```bash
python3 test/frontend_pipeline/check_descriptor_selection.py --out build/frontend_pipeline/descriptor_selection
python3 test/frontend_pipeline/check_candidate_word_hit.py --out build/frontend_pipeline/candidate_word_hit
python3 test/frontend_pipeline/check_address_select.py --out build/frontend_pipeline/address_select
python3 test/frontend_pipeline/check_remaining_range.py --out build/frontend_pipeline/remaining_range
```
