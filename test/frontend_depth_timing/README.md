# 图像前端与 DMA 的组合深度验证

## 数据准备与传输

`conv_im2col_frontend` 默认采用 `REGISTER_DESCRIPTOR=1`、`REGISTER_CACHE_REQUEST=0`、`REGISTER_ROW_ADDRESS=1` 和 `CACHE_RESPONSE_DEPTH=1`。描述符准备、请求保存和响应队列分别配置。描述符接收后，坐标基址、步长、地址、核位置、通道范围及候选选择进入一项准备寄存器。执行端接收该项时，同一周期可以保存下一描述符。执行端暂停时，准备项及其数据保持稳定；配置、复位和错误清除对应有效位。

准备项同时保存其命中的数据字。准备项等待期间，即使执行中的窗口更换了当前数据字，提交时仍使用与准备地址对应的数据。当前窗口最后一次缓存响应与下一窗口使用相同数据字时，提交条件可以直接使用该次有效响应，避免再次读取。该选择与描述符地址、输出末拍和缓存响应有效条件共同验证。

`axi_dual_block_dma` 将图像输出的数据、掩码、行列位置、所属窗口和末拍标志共同保存在弹性输出寄存器中。接收端停止时，所有有效输出保持稳定；前一拍被接收的同一周期可以装入下一拍。普通读取、窗口读取和错误排空均将这一级待输出数据计入完成条件。

`conv_window_queue` 的已发送窗口容量由 `p_frontend_outstanding` 指定，范围为一项至队列深度。完整 DMA 使用 `min(WINDOW_OUTSTANDING, 3)`，分别容纳准备中的描述符、执行中的窗口及等待外部接收的末拍。队首及响应标签只在外部末拍响应被接收后推进。发送与完成同时发生时，在途数量保持；配置清除和错误排空分别处理未发送与已发送条目。环形指针支持非二次幂的队列深度。

## 算术与选择结构

地址使用完整 32 位模运算，输入坐标保持 35 位有符号范围。分组加法分别计算局部进位条件，并在关键实例保留平衡前缀的中间结果。`parallel_prefix_add` 的 `p_group_width` 指定局部分组的位数，末组可以不足一个完整组宽。`p_preserve_groups` 默认关闭；时序敏感实例显式启用。

每拍输出通道数不超过八时，组内范围随通道索引保存。各种可能的传输数量分别计算下一范围、字边界及字命中，通道掩码只选择最终结果。范围计算保留原有 17 位下溢行为。组末判断直接使用已保存的范围，不再等待通道数编码后的加法。

列末条件与通道资格并行计算。组内范围使用独立的寄存器更新逻辑，保持配置、描述符提交、连续输出和通用解码的原有更新优先次序。准备地址从十组独立地址候选中按互斥条件选择。短字节增量逐位计算常量进位，数据字边界按位比较，使晚到的有效通道条件只参与候选选择。两项位级函数分别与完整定宽加法、大小比较进行全部二值输入证明，并检查四态仿真行为。

历史列位置同时计算普通增量和减去输出宽度的候选。后者先压缩三个操作数，再进行一次完整进位加法。预读步长按每种缓存行容纳数量分别计算，与输入元素宽度相关的常量比较并行完成。`stride_w` 与 `dilation_w` 分别产生预读距离，卷积核宽度只选择最终结果。配置接收时的通道范围使用 17 位加法等式，完整保留越界与溢出条件。八位有符号输入的偏移计算将低字节和值与进位分开，高字节候选提前计算。

缓存命中比较按三个标签位分组。单项需求队列的查询有效位与标签在同一边沿保存，并转发同拍有效位写入。当前填充组与查询组是否相同的比较结果也随两组地址的实际下一值保存，返回路径直接使用这一位状态。该状态与完整当前地址比较之间的恒等关系参加归纳证明。请求范围、元数据冲突、替换状态与数据选择保留各自的计算边界。缓存有效响应、实际保存的响应数据、描述符、错误和状态均参加功能检查；公开数据在对应有效信号成立时比较。

线性 DMA 对同一行继续读取和下一行读取分别计算地址、跨页限制及后续拍数，最后选择对应候选。AXI 读长度的减一编码与后续地址计算保留独立短算术，限制晚到选择之后的连续进位。列范围资格在 AXI 返回握手边沿与数据、列基址和描述符一起保存，输出通道直接读取对应资格位。块内尾列保持 `wr_valid=1` 并写入零。描述符非空和可接收标志与计数在同一边沿更新，使完成判断直接读取保存状态。返回列资格说明见 [linear_return.md](linear_return.md)；读长度的完整模块证明和 4 KiB 读写测试见 [读长度验证](../dma_read_length_depth/README.md)。

## 证明入口

| 入口 | 检查范围 |
|---|---|
| `check.py` | 通道范围、预读分段、配置步长、完整加法及最终进位 |
| `control_check.py` | 字边界、字命中、窗口纪元，以及预测器坐标计算 |
| `stream_check.py` | 任意有效通道掩码下的传输数量、行尾与连续请求条件 |
| `stream_select_check.py` | 输出掩码与组末判断，保留完整 17 位计算 |
| `range_write_check.py` / `range_four_state.py` | 全部 22 位状态编码及任意握手条件下的完整组内范围下一值，含四态控制优先次序 |
| `address_check.py` | 通道地址、横坐标递增、预读坐标及历史列位置 |
| `offset_check.py` | 任意输入字节和 16 位偏移的完整输出值 |
| `prepared_check.py` | 描述符准备两侧的 35 位坐标及填充、字命中选择 |
| `prepared_address_check.py` | 十组准备地址选择的完整 64 位结果及四态行为 |
| `descriptor_pipeline_check.py` | 准备项的接收、提交、保存、同拍替换及完整描述符和数据字内容 |
| `word_limit_check.py` / `byte_step_check.py` | 数据字边界比较、短常量地址加法及四态行为 |
| `check_event_first.py` | 请求地址与 `event_first` 的对应关系 |
| `check_configuration_selection.py` | 配置通道范围及预读步长的完整输入证明与四态检查 |
| `queue_check.py` | 深度 2、3、4、7、8 和一项至三项在途窗口的全部合法组合归纳证明 |
| `output_check.py` | 弹性输出保存、替换和背压行为 |
| `linear_check.py` | 线性 DMA 全部公开输出、共享时钟状态及展开后的存储 |
| `linear_count_check.py` | 完整线性 DMA 等价，以及保存的非空、可接收标志与计数的恒等关系 |
| `linear_return_check.py` | 完整线性 DMA 等价，以及每个保存的列资格与已接收列信息的恒等关系 |
| `linear_return_measure.py` | 返回数据公开接口、列资格寄存器输入及整个模块的实际组合路径 |

这些入口从指定目录读取实际 RTL。独立算术的组合检查覆盖全部输入取值。`check_event_first.py` 对寄存请求分支使用合法状态与请求有效条件；队列证明从复位状态开始，在复位后允许任意接口输入。线性 DMA 的配置组合包含两种矩阵尺寸、32/64 位总线、读写各一项或四项在途事务，以及一项或四项描述符。

```sh
python test/frontend_depth_timing/check.py --out build/frontend_depth14/arithmetic
python test/frontend_depth_timing/stream_check.py --out build/frontend_depth14/stream
python test/frontend_depth_timing/stream_select_check.py --out build/frontend_depth14/selection
python test/frontend_depth_timing/address_check.py --out build/frontend_depth14/address
python test/frontend_depth_timing/range_write_check.py --out build/frontend_depth14/range_write
python test/frontend_depth_timing/range_four_state.py --out build/frontend_depth14/range_four_state
python test/frontend_depth_timing/descriptor_pipeline_check.py --out build/frontend_depth14/descriptor
python test/frontend_depth_timing/prepared_address_check.py --out build/frontend_depth14/prepared_address
python test/frontend_depth_timing/word_limit_check.py --out build/frontend_depth14/word_limit
python test/frontend_depth_timing/byte_step_check.py --out build/frontend_depth14/byte_step
python test/frontend_depth_timing/offset_check.py --out build/frontend_depth14/offset
python test/frontend_depth_timing/prepared_check.py --out build/frontend_depth14/prepared
python test/frontend_depth_timing/queue_check.py --out build/frontend_depth14/queue
python test/frontend_depth_timing/output_check.py --out build/frontend_depth14/output
```

`--source-root` 可指定固定源码目录。两个范围更新入口使用随测试保存的完整参考表达式，通过 `--candidate` 指定前端文件；其余前端入口读取对应的源码根目录。线性 DMA 比较入口通过 `--reference`、`--candidate` 指定待比较文件，`--sizes 16 64` 选择两种矩阵尺寸。

## 实际事务与吞吐检查

```sh
python test/frontend_depth_timing/transactions.py \
  --out build/frontend_depth14/transactions_l16 \
  --register-cache-request 0 --register-descriptor 1 --cache-response-depth 1 \
  --lanes 8 --cache-line-bytes 16 --cache-sets 128 --cases window s16
python test/frontend_depth_timing/transactions.py \
  --out build/frontend_depth14/transactions_l128 \
  --register-cache-request 0 --register-descriptor 1 --cache-response-depth 1 \
  --lanes 8 --cache-line-bytes 128 --cache-sets 16 --cases window s16
python test/window_dma/run.py --fpga --jobs 1 \
  --out build/frontend_depth14/window_dma \
  --single-response-interval 1 --descriptor-response-interval 3
python test/linear_dma_4k/run.py --bus-width 64 --outstanding 4 \
  --out build/frontend_depth14/linear_read
```

前端数值测试检查输出元素、行列顺序、掩码、背压保持、描述符准备内容、保存的组内范围及字命中状态。窗口 DMA 测试覆盖普通读取与窗口读取并发、配置切换、错误返回、中止和复位，并检查张量地址范围及 4 KiB 边界。

暖命中测试使用 32 位 AXI、四个输出通道，严格要求单拍窗口每周期返回。S8 的 128 个四拍窗口返回 512 拍、2,048 个元素，首拍至末拍共 639 个周期，其中相邻周期返回 384 次，窗口内间隔为一个周期，描述符边界间隔为两个周期。S8 的 256 个单拍窗口返回 1,024 个元素，共 256 个周期，连续返回 255 次。S16 的 128 个单拍窗口返回 256 个元素，共 128 个周期，连续返回 127 次。

完整窗口测试接收 915 个请求，完成 907 个，复位取消 8 个，检查 6,642 个输出元素和 23 个错误响应。S8 和 S16 均包含随机坐标、响应背压、读取错误及复位后重新配置。性能参数和实际返回间隔分别保存在测试摘要中；单拍返回上限为一个周期，窗口内和描述符边界的上限分别为三个周期。

真实向量回归分别使用 PE8 共享存储和 PE16 共享量化配置。每组保留 615 个通用场景、143 个 Add 场景和 273 个 Softmax 场景，以及连续响应、多个在途窗口和请求响应重叠检查。测试结果与所用 RTL 的 SHA256 一起保存。

## 实际配置下的完整 DMA 测量

| 参数 | 向量回归配置 | SoC 配置 |
|---|---:|---:|
| `SIZE` / `IM2COL_SIZE` | 64 / 16 | 64 / 16 |
| `BUS_WIDTH` | 64 | 64 |
| `DATA_LANES` / `WINDOW_LANES` | 8 / 8 | 8 / 8 |
| `CONV_CACHE_SETS` | 128 | 16 |
| `CONV_CACHE_WAYS` | 2 | 2 |
| `CONV_LINE_BYTES` | 16 | 128 |
| `CACHE_BLOCKS` | 4 | 64 |

```sh
python scripts/fpga/open_fpga_synth.py \
  --case-config test/frontend_depth_timing/synthesis_cases.json \
  --cases dma_stream_w8_l16 dma_stream_soc \
  --max-register-path-cells 14 --out build/frontend_depth14/synthesis
python test/frontend_depth_timing/boundary_paths.py \
  --folder build/frontend_depth14/synthesis/dma_stream_soc \
  --out build/frontend_depth14/synthesis/dma_stream_soc/boundary_paths.json
python test/frontend_depth_timing/target_paths.py \
  --folder build/frontend_depth14/synthesis/dma_stream_soc \
  --out build/frontend_depth14/synthesis/dma_stream_soc/target_paths.json
```

测量使用完整 `axi_dual_block_dma`，包含前端、缓存、窗口队列、线性 DMA、读通道选择及输出寄存器。判断寄存器间深度使用 `metrics.paths.longest_register_path_cells`。公开端口分析分别记录全部起点和图像输出寄存器起点的路径，端点标记仅存在于分析过程，不写入综合网表。

`target_paths.py` 保存准备描述符、组内范围、图像输出数据、填充组匹配状态和两种缓存字匹配寄存器的完整连接路径，并单独过滤队列 `q0` 描述符 RAM 到字匹配寄存器的组合连接。准备寄存器将后两类连接分开，报告以 `connected_path_exists=false` 表示所选起终点之间没有单段组合路径。

资源数和组合级数由映射后的实际连接图统计。完整 SoC 的跨模块路径继续由整机综合检查；150 MHz 建立时间使用目标器件的布局布线结果检查。
