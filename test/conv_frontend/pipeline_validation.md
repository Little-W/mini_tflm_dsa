# 卷积前端的请求保存与描述符计算

生产配置为 `SIZE=16`、`BUS_WIDTH=64`、`READ_WIDTH=64`、`LANES=8`、`CACHE_SETS=16`、`CACHE_WAYS=2`、`LINE_BYTES=128`。描述符寄存和缓存请求寄存均启用，缓存返回队列深度为 2。

## 请求与返回

缓存请求的地址、几何标志、窗口索引、代次、进度和行坐标共同保存在一个请求寄存级。请求有效且下游未接收时，全部字段保持；下游接收的同一边沿可以保存下一请求。该级容量为一项，输出请求完整经过寄存器。

缓存的返回队列具有两个条目。标签数据和请求地址分别保存后再比较；单条目参数分支保持其独立实现。生产缓存的持续命中测试中，请求接收间隔和响应返回间隔均为一个周期。

## 描述符与几何运算

描述符可以在空闲状态或当前分块末拍接收，已经准备的描述符在空闲状态提交。当前分块完成后，状态寄存器先进入空闲状态，再将准备项更新到执行状态。接收与提交可以在同一边沿发生，使准备寄存器接收后续描述符。

准备阶段选择行地址和分组地址，并保存独热操作类型。提交阶段根据操作类型选择当前任务的固定步长，使用两组完整地址加法。输入坐标同样保存基坐标，提交时选择对应步长并完成两个坐标的求和和范围检查。已保存的窗口保留其填充标志。寄存描述符分支只生成实际使用的坐标候选；直接描述符分支保留独立候选计算。

核位置、核行列与像素编号分别保存基值，提交阶段根据同一操作类型选择增量，并共用四组模加法，核末列根据提交的核列值判断。四个历史坐标条目使用一组可推断的分布式存储，分别保存位置键和行列坐标，有效位随配置清除。

通道范围由完整十七位剩余数量生成，配置和执行上下文分别提前保存。描述符准备使用同一份十七位剩余通道数判断完整分块与尾部分块，窗口上下文单独保存该数量。通道、分组偏移和本次数量共用一组十八位加法生成下一通道位置。输出掩码使用连续通道范围，末列位置通过相邻列资格位确定。固定短步长地址采用逐位和值表达，完整进位保留到高位地址选择。行末、有效列余量和跨字判断各保留完整计算结果，供输出状态选择使用。五位除三译码同时产生商和余数，供三通道和三列卷积核的坐标解码使用。

保存字标签按三个比特分组比较。字命中状态使用地址更新的互斥事件独立保存，响应、配置、通道更新和描述符提交分别选择完整命中结果。配置只在空闲状态接收，运行期更新直接使用对应状态和传输条件；直接描述符模式保留末拍提交优先次序。

预取横坐标的核行片段与跨步窗口共用一组完整加法，模式先选择对应步长。预取纵坐标以及配置阶段的行间和抽头像素步长各自经过已有寄存器。宽算术采用普通可综合表达式及 `use_dsp` 属性。RTL 保留所有配置位宽和算术结果，不实例化器件算术或存储原语。

## 已执行的检查

| 检查 | 配置与结果 |
| --- | --- |
| 独立数值及所有公开输出逐周期比较 | 168 项，合计 1,803,070 周期，通过 |
| 直接描述符及请求模式逐周期比较 | 42 项，972,912 周期，通过 |
| 配置与运行更新事件 | 两种描述符模式、21 个事件选择和使能结果的完整输入证明通过；全部状态赋值保持独热 |
| 预取横坐标共享与配置步长 | 33、35、40 位坐标共 6 组完整输入证明通过 |
| 连续描述符数值与握手 | 普通、窗口模式共 84 项，通过 |
| 连续描述符普通模式 | 216,837 周期，203,008 个背压提供周期，35 次末拍接收 |
| 连续描述符窗口模式 | 167,025 周期，153,171 个背压提供周期，35 次末拍接收 |
| 描述符在途数量 | 最大两项，接收、完成和输出数量一致 |
| 请求元数据 | 147 位，复位检查、无界归纳及 20,000 组四态输入通过 |
| 通道范围 | 4 种通道数、两种算术配置，共 8 组完整输入证明通过 |
| 输出掩码及列末判断 | 20 组尺寸与通道数组合证明通过，掩码另有 20,000 组四态检查 |
| 坐标范围 | 描述符寄存开关和两种算术配置，共 4 组证明通过 |
| 提交填充判断 | 两种算术配置的完整输入证明通过 |
| 地址更新与保存字命中 | 地址更新 8 组证明；保存字命中 6 组复位检查和无界归纳通过 |
| 准备阶段剩余通道数 | 17 组尺寸与位宽组合的完整输入证明，以及配置保存的复位检查和无界归纳通过 |
| 通道位置共享运算 | 通道数 1 至 8、普通与连续掩码两类，共 16 组证明通过 |
| 操作类型及完整结果 | 33、35、40 位坐标共三组证明，覆盖地址、坐标、像素和核位置及独热选择；采用同一任务的配置系数 |
| 描述符共享运算 | 四组结果共 128 位，完整输入证明通过 |
| 历史坐标存储 | 四个 64 位条目的有效数据通过复位检查和无界归纳 |
| 固定短步长加法 | 2 至 9 位输入、完整进位结果的 8 组证明通过 |
| 五位除三 | 32 个二态输入、1,024 个四态输入及完整输入证明通过 |
| 缓存标签与协议 | 两种路数和三种行宽的标签证明通过；生产深度 1、2 的协议测试通过 |

各项记录分别保存被测源码散列。连续描述符测试采用的前端实现与当前实现具有相同的请求和描述符寄存结构，当前实现另执行了上表的逐周期比较和共享算术证明。连续提供描述符的测试检查每个输出坐标和数值、重复写入、返回顺序、完成次数和最大在途数量。测试同时提供随机数据返回延迟及输出背压，并检查读错误传播和后续配置恢复。

## 综合结果

采用生产参数进行独立 `xc7` 映射，仅对 RTL 中标有 `use_dsp="yes"` 的算术执行 DSP 映射：逻辑 LUT 为 9,483，分布式存储占用的标称 LUT 为 364，总计 9,847，触发器为 5,937，DSP 为 111，RAMB18 为 9。完整连接图得到的寄存器间最长组合路径为 13 个单元，尚未满足 10 级要求。150 MHz 需要目标器件的综合、布局布线和静态时序分析结果确认。

源码散列、配置、各项结果和综合统计保存在 [pipeline_validation.json](pipeline_validation.json)。

## 复现入口

```sh
python3 test/conv_frontend/tools/run_numeric.py --fpga --out build/frontend_numeric
python3 test/conv_frontend/tools/run_numeric.py --fpga --sizes 16 --continuous --out build/frontend_continuous
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
python3 test/conv_frontend/tools/check_small_decode.py --out build/frontend_divide_three
python3 test/cache_storage/check_tag_stage.py --out build/cache_tag_stage
```

`compare_frontend.py` 的 `--reference-source-root` 参数指定固定参考源码。`check_descriptor_padding.py` 的 `--reference-root` 参数指定含独立坐标候选检查的参考源码。各项测试通过 `--source-root` 选择待测源码目录。
