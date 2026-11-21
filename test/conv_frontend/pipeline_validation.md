# 卷积前端的请求保存与描述符计算

生产配置为 `SIZE=16`、`BUS_WIDTH=64`、`READ_WIDTH=64`、`LANES=8`、`CACHE_SETS=16`、`CACHE_WAYS=2`、`LINE_BYTES=128`。描述符寄存和缓存请求寄存均启用，缓存返回队列深度为 2。

## 请求与返回

缓存请求的地址、几何标志、窗口索引、代次、进度和行坐标共同保存在一个请求寄存级。请求有效且下游未接收时，全部字段保持；下游接收的同一边沿可以保存下一请求。该级容量为一项，输出请求完整经过寄存器。

缓存的返回队列具有两个条目。标签数据和请求地址分别保存后再比较；单条目参数分支保持其独立实现。生产缓存的持续命中测试中，请求接收间隔和响应返回间隔均为一个周期。

## 描述符与几何运算

启用 `REGISTER_DESCRIPTOR` 时，描述符在空闲状态接收，并在空闲状态提交。当前分块完成后，状态寄存器进入空闲状态；已经准备的描述符可以在提交的同一边沿接收下一项，保留当前执行项和准备项共两项在途容量。描述符保存的数据字读取已经完成的缓存返回寄存器。直接描述符模式保留当前分块末拍接收和提交。

输出宽度、分组通道数和卷积核宽度的移位量随配置同时保存。分组覆盖完整输入通道、分组偏移为零且横向膨胀为一的连续通道条件也在该边沿保存。运行阶段直接读取这些配置结果；通道余数与分组范围准备共用保存的配置掩码。配置接收条件、描述符周期和缓存请求周期保持。

准备阶段选择行地址和分组地址，并保存独热操作类型。提交阶段根据操作类型选择当前任务的固定步长，使用两组完整地址加法。输入坐标同样保存基坐标，提交时选择对应步长并完成两个坐标的求和和范围检查。已保存的窗口保留其填充标志。寄存描述符分支只生成实际使用的坐标候选；直接描述符分支保留独立候选计算。

核位置、核行列与像素编号分别保存基值，提交阶段根据同一操作类型选择增量，并共用四组模加法，核末列根据提交的核列值判断。四个历史坐标条目使用一组可推断的分布式存储，分别保存位置键和行列坐标，有效位随配置清除。寄存描述符与请求模式在描述符提交边沿保存历史命中和行列坐标，执行解码使用该保存结果；历史表写入时，保存结果同步更新。位置差使用完整三十三位结果，描述符提交时保存，历史位置更新时归零。历史行末保留三十二位位置溢出条件。

通道范围由完整十七位剩余数量生成，配置和执行上下文分别提前保存。每个来源共用剩余数量的高位非零判断，各通道只比较低位与固定通道编号。描述符准备使用同一份十七位剩余通道数判断完整分块与尾部分块，窗口上下文单独保存该数量。通道、分组偏移和本次数量共用一组十八位加法生成下一通道位置。输出掩码使用连续通道范围，末列位置通过相邻列资格位确定。固定短步长地址采用逐位和值表达，完整进位保留到高位地址选择。行末、有效列余量和跨字判断各保留完整计算结果，供输出状态选择使用。缓存字输出状态与主状态在同一条寄存赋值中保存，通道资格直接使用该状态标志。通道数量与范围标志的数据选择依据任务阶段和列末条件，传输、有效性和行末条件共同控制保存使能。字节地址高位、归约位置高位、两项解码递增与配置位置边界使用完整定宽算术结果。五位除三译码同时产生商和余数，供三通道和三列卷积核的坐标解码使用。

描述符的保存字标签按三个比特分组比较。短步长地址共用相邻数据字的标签匹配，字内进位选择已经完成的匹配结果。准备列数使用完整三十二位差值，同时保留低位借位；S8 与 S16 的字末及列末条件分别归并后选择。字内剩余字节范围与地址在同一边沿保存，S8、S16 的通道资格及短步长跨字条件读取范围位。行切换、组切换和通道递增的组范围先形成一位选择条件，再合并候选数据。字命中状态使用地址更新的互斥事件独立保存，响应、配置、通道更新和描述符提交分别选择完整命中结果。配置只在空闲状态接收，运行期更新直接使用对应状态和传输条件；直接描述符模式保留末拍提交优先次序。

预取横坐标的核行片段与跨步窗口共用一组完整加法，模式先选择对应步长。片段位移、距离和负一常量先压缩为两个操作数，再用完整三十三位加法保存结果。历史行范围使用完整无符号比较。预取纵坐标以及配置阶段的行间和抽头像素步长各自经过已有寄存器。历史横坐标和两个退休行位置的完整进位结果也使用独立算术表达式。FPGA 综合分支采用普通加法及 `use_dsp` 属性，事件仿真和通用分支保留分组进位表达式；两种表示在完整二态输入上等价。宽算术采用普通可综合表达式及 `use_dsp` 属性。RTL 保留所有配置位宽和算术结果，不实例化器件算术或存储原语。

配置通道范围将分组偏移、分组数量和输入通道上限逐位压缩，再使用完整十八位加法判断范围。配置末列条件直接比较坐标加一与对应宽度，下一组位置使用完整三十三位加法。八位输入的偏移范围通过符号扩展部分和低字节范围并行判断；输出数据在允许的偏移范围 −127 至 128 内形成完整九位有符号和值，再符号扩展为十六位输出。综合实现和事件仿真的完整表达式均执行了独立验证。

## 已执行的检查

| 检查 | 配置与结果 |
| --- | --- |
| 配置保存逐周期比较 | 尺寸 4、8、16，普通与窗口预取共 168 项、1,803,070 周期，所有公开输出一致 |
| 配置保存关系 | 六项配置派生关系通过复位检查和无界归纳，30,000 个四态周期、180,000 次比较通过 |
| 寄存描述符连续数值与握手 | FPGA 综合配置，尺寸 4、8、16，共 168 项、1,759,478 周期，通过 |
| 直接描述符及请求模式逐周期比较 | 普通和窗口预取共 84 项、336,725 周期，所有公开输出一致，控制检查通过 |
| 配置与运行更新事件 | 两种描述符模式、21 个事件选择和使能结果的完整输入证明通过；全部状态赋值保持独热 |
| 预取横坐标共享与配置步长 | 33、35、40 位坐标共 6 组完整输入证明通过 |
| 连续描述符数值与握手 | 普通、窗口模式共 84 项，通过 |
| 连续描述符普通模式 | 216,837 周期，203,013 个背压提供周期，2,083 次接收与提交同时发生 |
| 连续描述符窗口模式 | 167,025 周期，153,208 个背压提供周期，2,083 次接收与提交同时发生 |
| 描述符在途数量 | 最大两项，接收、完成和输出数量一致 |
| 请求元数据 | 147 位，复位检查、无界归纳及 20,000 组四态输入通过 |
| 通道范围 | 4 种通道数、两种算术配置，共 8 组完整输入证明通过 |
| 输出掩码及列末判断 | 20 组尺寸与通道数组合分别验证通用和 FPGA 综合配置，共 40 组证明通过，掩码另有 20,000 组四态检查 |
| 坐标范围 | 描述符寄存开关和两种算术配置，共 4 组证明通过 |
| 提交填充判断 | 两种算术配置的完整输入证明通过 |
| 地址更新与保存字命中 | 地址更新 8 组证明；保存字命中 6 组复位检查和无界归纳通过 |
| 准备阶段剩余通道数 | 17 组尺寸与位宽组合的完整输入证明，以及配置保存的复位检查和无界归纳通过 |
| 通道位置共享运算 | 通道数 1 至 8、普通与连续掩码两类，共 16 组证明通过 |
| 操作类型及完整结果 | 33、35、40 位坐标共三组证明，覆盖地址、坐标、像素和核位置及独热选择；采用同一任务的配置系数 |
| 描述符共享运算 | 四组结果共 128 位，完整输入证明通过 |
| 历史坐标存储 | 四个 64 位条目的有效数据通过复位检查和无界归纳 |
| 历史位置差和行末 | 完整 33 位差值、32 位模行末及溢出条件、两项 16 位模相等关系通过复位检查和无界归纳 |
| 历史查询保存 | 9 种索引移位，逐周期命中及命中坐标通过复位检查和无界归纳 |
| 缓存字输出状态 | 55 处状态赋值共同保存输出类别；无界归纳和 20,001 个四态周期通过 |
| 八位输入修正 | 配置允许范围内的完整二态输入证明，以及 524,288 次 RTL 数值检查通过 |
| 短位宽完整加法 | 18、19 位完整结果的综合分支输入证明通过；通用、FPGA 和 ASIC 事件配置共 60,000 次四态检查通过 |
| 通用配置连续数值与握手 | 42 项、216,837 周期，通过 |
| 准备列数、相邻字匹配和格式条件 | 19 组参数的完整综合输入证明、684,000 次四态比较通过 |
| 历史行范围和预取片段 | 通用、FPGA、ASIC 三种综合配置的完整输入证明，120,000 次四态比较通过 |
| 通道范围的共享高位判断 | 通道数 1 至 8 的完整综合输入证明，288,000 次四态比较通过 |
| 字内剩余范围保存 | 两种描述符模式的更新互斥证明，读取字宽 2 至 8 字节的复位检查和无界归纳通过 |
| 组范围选择 | 4 种范围位宽的完整输入证明及 80,000 次四态比较通过 |
| 固定握手周期统计 | 普通和窗口预取共 84 项、4,320 个分块，逐项数值与周期记录通过 |
| 描述符接收与数据字选择 | 两种描述符模式的完整输入证明通过；寄存模式只在空闲状态接收，直接模式周期保持 |
| 配置算术与范围 | 通道范围、三项末列、偏移范围和下一组位置共 38 个结果位的完整输入证明，以及 60,000 次四态检查通过 |
| 通道数据与保存使能 | 6 种计数位宽、2 种描述符模式，共 12 组复位检查及无界归纳，40,002 个四态周期通过 |
| 固定短步长加法 | 2 至 9 位输入、完整进位结果的 8 组证明通过 |
| 五位除三 | 32 个二态输入、1,024 个四态输入及完整输入证明通过 |
| 缓存标签与协议 | 两种路数和三种行宽的标签证明通过；生产深度 1、2 的协议测试通过 |

各项记录分别保存被测源码散列。当前配置保存实现执行了 168 项逐周期数值比较，并检查配置保存、更新事件与数据字选择关系。描述符接口的连续测试和直接模式比较保留各自被测源码散列。连续请求测试检查每个输出坐标和数值、重复写入、返回顺序、完成次数和两项在途容量，分别覆盖随机返回延迟、输出背压、固定握手、读错误传播和后续配置恢复。

固定握手的普通模式包含 42 个任务、2,160 个分块，总周期由 199,627 增至 199,662；窗口预取同样包含 42 个任务、2,160 个分块，总周期由 151,588 增至 151,621。每个任务增加 0 或 1 个周期。持续接收时，已有准备项提交与下一项接收重叠；在当前末拍才到达的描述符等待后续空闲周期。随机握手下，两种模式的总周期分别为 216,837 和 167,025。

## 综合结果

采用生产参数和 JSON 中记录的固定依赖版本进行独立 `xc7` 映射，仅对 RTL 中标有 `use_dsp="yes"` 的算术执行 DSP 映射：逻辑 LUT 为 8,831，分布式存储占用的标称 LUT 为 368，总计 9,199，触发器为 5,922，DSP 为 134，RAMB36 为 1，RAMB18 为 10。同一依赖的配置组合解码参考实现使用 9,181 个标称 LUT 和 5,913 个触发器；配置结果保存增加 18 个标称 LUT、9 个触发器，DSP 数量保持。

寄存器间最长组合路径由 13 级降至 12 级，当前主要涉及输入横坐标范围、通道有效状态与字内范围更新。目标为 10 级。150 MHz 需要目标器件的布局布线与静态时序分析结果确认。

源码散列、配置、各项结果和综合统计保存在 [pipeline_validation.json](pipeline_validation.json)。

## 复现入口

```sh
python3 test/conv_frontend/tools/run_numeric.py --fpga --out build/frontend_numeric
python3 test/conv_frontend/tools/run_numeric.py --fpga --synthesis --sizes 16 --continuous --out build/frontend_continuous
python3 test/conv_frontend/tools/run_numeric.py --fpga --synthesis --sizes 16 --continuous --fixed-ready --out build/frontend_fixed
python3 test/conv_frontend/tools/check_descriptor_admission.py --source-root . --reference-root /path/to/fixed_reference --out build/frontend_admission
python3 test/conv_frontend/tools/check_decode_configuration.py --source-root . --out build/frontend_decode_configuration
python3 test/conv_frontend/tools/check_request_stage.py --out build/frontend_request
python3 test/conv_frontend/tools/check_channel_ranges.py --out build/frontend_channels
python3 test/conv_frontend/tools/check_chunk_mask.py --out build/frontend_mask
python3 test/conv_frontend/tools/check_coordinate_bounds.py --out build/frontend_coordinates
python3 test/conv_frontend/tools/check_frontend_address.py --out build/frontend_address
python3 test/conv_frontend/tools/check_saved_word.py --out build/frontend_saved_word
python3 test/conv_frontend/tools/check_descriptor_shared.py --out build/frontend_descriptor_shared
python3 test/conv_frontend/tools/check_operation_stage.py --reference-root /path/to/fixed_reference --source-root . --out build/frontend_operation
python3 test/conv_frontend/tools/check_prepare_shared.py --reference-root /path/to/fixed_reference --out build/frontend_prepare_shared
python3 test/conv_frontend/tools/check_epoch_shared.py --reference-root /path/to/fixed_reference --out build/frontend_epoch_shared
python3 test/conv_frontend/tools/check_frontend_event_domains.py --source-root . --reference-root /path/to/fixed_reference --out build/frontend_event_domains
python3 test/conv_frontend/tools/check_prefetch_shared.py --source-root . --reference-root /path/to/fixed_reference --out build/frontend_prefetch_shared
python3 test/conv_frontend/tools/check_short_address_sum.py --source-root . --out build/frontend_short_address
python3 test/conv_frontend/tools/check_word_state.py --source-root . --reference-root /path/to/fixed_reference --out build/frontend_word_state
python3 test/conv_frontend/tools/check_history_delta.py --source-root . --out build/frontend_history_position
python3 test/conv_frontend/tools/check_position_snapshot.py --source-root . --out build/frontend_position_snapshot
python3 test/conv_frontend/tools/check_s8_formatter.py --source-root . --reference-root /path/to/fixed_reference --out build/frontend_s8_formatter
python3 test/conv_frontend/tools/check_short_sums.py --source-root . --out build/frontend_short_sums
python3 test/conv_frontend/tools/check_configuration_arithmetic.py --source-root . --out build/frontend_configuration_arithmetic
python3 test/conv_frontend/tools/check_active_data_selection.py --source-root . --reference-root /path/to/fixed_reference --out build/frontend_active_data
python3 test/conv_frontend/tools/check_stream_arithmetic.py --source-root . --reference-root /path/to/fixed_reference --out build/frontend_stream_arithmetic
python3 test/conv_frontend/tools/check_history_prefetch.py --source-root . --out build/frontend_history_prefetch
python3 test/conv_frontend/tools/check_group_ranges.py --source-root . --reference-root /path/to/fixed_reference --out build/frontend_group_ranges
python3 test/conv_frontend/tools/check_word_range.py --source-root . --out build/frontend_word_range
python3 test/conv_frontend/tools/check_group_selection.py --source-root . --reference-root /path/to/fixed_reference --out build/frontend_group_selection
python3 test/conv_frontend/tools/check_small_decode.py --out build/frontend_divide_three
python3 test/cache_storage/check_tag_stage.py --out build/cache_tag_stage
```

`compare_frontend.py` 的 `--reference-source-root` 参数指定固定参考源码。`check_descriptor_padding.py` 的 `--reference-root` 参数指定含独立坐标候选检查的参考源码。各项测试通过 `--source-root` 选择待测源码目录。

`compare_frontend.py --fpga --synthesis` 在两个比较实例上启用综合条件，同时保持测试观察模块、数值检查和接口比较有效。
