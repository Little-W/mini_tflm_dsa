# 卷积前端与 DMA 的可综合 RTL

## 结构

卷积描述符的范围比较采用三位分组和高位优先的组合树。描述符等值比较按字段分组，快速接收、地址步长和低位进位使用同一比较结果。十七位条件递增使用并行前缀；五位位置的除三运算使用精确的移位加法，商和余数共用乘以 11 的结果。

AXI 读取保护器按两位一组计算页地址的进位和传播条件。末拍、末行、返回标签、读请求授予和总线错误均由明确的布尔表达式生成。权重行组装共用每列的数据选择，完成事件独立控制累积数据清除。权重计数器每六位组成一个加法分组，组间进位与完整计数在同一时钟边沿保存。

以上模块保持公开接口、存储容量、复位行为、协议优先级和输出周期。普通逻辑由综合工具选择器件资源，RTL 不实例化 LUT 原语。

## 验证

`formal.py` 固定参考提交及当前源码，对整个模块展开后的状态和公开输出执行等价证明。读取输入不添加约束，使用实际 FPGA 编译定义和官方原语模型；参考版本与当前版本分别读取各自的依赖文件。

```sh
python3 test/frontend_rtl_structure/formal.py \
  --reference 653477ed --retimed-kernel-buffer \
  --out /tmp/frontend_structure_formal

python3 test/conv_guard/run_control_formal.py \
  --reference-ref 653477ed --fpga \
  --out /tmp/frontend_guard_formal

python3 test/kernel_prefetch/run_control_formal.py \
  --reference 653477ed --fpga --seq 2 \
  --out /tmp/frontend_kernel_control

python3 test/window_dma/run.py \
  --reference-ref 653477ed --fpga --verilator verilator-modern --jobs 1 \
  --out /tmp/frontend_window

python3 test/kernel_prefetch/run.py \
  --fpga --bus-width 64 --verilator verilator-modern \
  --out /tmp/frontend_kernel_prefetch
```

窗口 DMA 检查覆盖四个在途请求、连续命中、随机坐标与反压、配置切换、读取错误、无效描述符和复位恢复。权重加载检查覆盖 INT8、INT16、尾组、预取命中、候选替换、取消和传输重叠。结果及源码 SHA-256 记录在 `measurement.json`。

## 同步存储器

权重缓冲区按列使用同步块 RAM。读取数据、输出列号和有效列掩码在同一时钟边沿保存，随后根据已保存的列号完成组合旋转。两个逻辑预取槽位和三个物理存储槽位维持原有的占用、释放及发送周期。缓存的填充代次与命中代次也使用同步块 RAM，读写地址、使能和同址读写行为保持一致。

`--retimed-kernel-buffer` 使内部 RAM 读端口按照各自的寄存边界展开。公开权重输出、存储内容和其余对应状态均参加证明，输入不添加约束。

```sh
python3 test/frontend_rtl_structure/formal.py \
  --reference 72e24c71 --cases cache128 kernel64 --retimed-kernel-buffer \
  --out /tmp/frontend_storage_formal

python3 test/kernel_prefetch/run_buffer_equivalence.py \
  --reference 72e24c71 --profiles 3:8 16:16 32:16 --cycles 100000 \
  --out /tmp/frontend_buffer_equivalence
```

两个生产配置的等价检查通过 97,272 个状态及输出位。三个缓冲区参数组合各运行 100,003 周期；完整权重预取检查通过 285 个块及 72,960 个数值，包含同时读写、尾组、刷新和复位恢复。

独立综合使用 xc7 映射和相同输入参数。权重缓冲区的 LUT 位点估计为 994，寄存器为 332，RAMB18 为 16，寄存器之间的最长组合路径为 7 级；128 组、两路缓存的对应结果为 3,938 个 LUT 位点、1,832 个寄存器、24 个 RAMB18 和 14 级。相同配置的存储调整分别减少 146 和 95 个 LUT 位点。上述位点统计包含普通逻辑和分布式存储，完整 SoC 使用统一综合结果。具体配置、源码摘要和验证结果记录于 `storage_measurement.json`。

## 窗口队列计数

窗口队列的计数位分别计算加一进位和减一借位，非空结果由当前计数的零值、一值和最大值边界独立决定。两个结果在同一时钟边沿保存，队列深度、同时接收与完成的行为以及所有输出周期保持一致。

深度 2、3、4、7、8 的完整状态与输出比较通过 3,367 个等价位，输入不添加约束。实际 FPGA 窗口 DMA 检查完成 422 次接收、418 次完成、4 次取消和 4,457 个数据元素，当前与参考版本的连续响应周期文件完全一致。四项队列的独立综合为 125 个普通 LUT、112 个寄存器，最长内部组合路径从 6 级降至 4 级。记录见 `window_count_measurement.json`。

```sh
python3 test/frontend_rtl_structure/formal.py \
  --reference da4cd2e2 --cases window_d2 window_d3 window_d4 window_d7 window_d8 \
  --out /tmp/window_count_formal

python3 test/window_dma/run.py \
  --reference-ref da4cd2e2 --fpga --verilator verilator-modern --jobs 1 \
  --out /tmp/window_count_numeric

python3 test/frontend_tile_input_depth/queue_synthesis.py \
  --reference da4cd2e2 --out /tmp/window_count_synthesis \
  --lock-file /tmp/window_count_synthesis.lock
```

## 窗口描述符存储

窗口队列的三个 32 位描述符字段分别使用同步 `regfile`，综合属性选择块 RAM。写入与请求接收在同一边沿发生，读端口按当前准备项地址保存数据；未读取时保持输出，同址读写返回写入前的内容。列范围标志、标签和队列控制保持原有的寄存周期。

参考提交 `6f4b51c4` 与当前四项队列使用相同参数及综合选项：

| 项目 | 参考队列 | 当前队列 |
|---|---:|---:|
| 普通 LUT | 125 | 133 |
| 分布式存储 LUT 位点 | 76 | 4 |
| 合计 LUT 位点估计 | 201 | 137 |
| 寄存器 | 112 | 16 |
| RAMB18E1 | 0 | 3 |
| 寄存器之间的最长组合路径 | 4 | 5 |

深度 2、3、4、7、8 的完整状态、所有存储字和公开输出通过 3,382 个等价位，输入不添加约束。实际 FPGA 窗口检查完成 422 次接收、418 次完成、4 次取消和 4,457 个数值，连续响应周期文件与参考版本完全一致。完整结果记录于 `window_storage_measurement.json`。

```sh
python3 test/frontend_rtl_structure/formal.py \
  --reference 6f4b51c4 --cases window_d2 window_d3 window_d4 window_d7 window_d8 \
  --out /tmp/window_storage_formal
python3 test/frontend_tile_input_depth/queue_synthesis.py \
  --reference 6f4b51c4 --out /tmp/window_storage_synthesis \
  --lock-file /tmp/window_storage_synthesis.lock
python3 test/window_dma/run.py \
  --reference-ref 6f4b51c4 --fpga --verilator verilator-modern --jobs 1 \
  --out /tmp/window_storage_numeric
```

## 前端定宽算术

五位位置乘以 11 后右移五位得到除三的商，余数通过两位模加运算形成。坐标高字节将两个九位补数相加，再对九位结果取反，完整得到两个八位操作数与固定输入进位一的和。

七组完整坐标各使用一个加法器，范围判断使用独立的字节进位与边界关系并行生成。请求和预取各保留一个退休行号计算端口；两个预取阶段按照原有采样周期共用端口，分别在第 3、4 阶段保存结果。

参考提交 `cd312b48` 与当前前端使用同一公共 RTL、缓存和预测器版本，相同参数、原语模型及综合脚本。源文件散列逐项核对，只有前端源码不同。`SIZE=16`、`BUS_WIDTH=64`、`LANES=4` 的独立结果如下，缓存及预测器保持接口边界：

| 项目 | 参考提交 | 当前前端 |
|---|---:|---:|
| 普通 LUT | 7,566 | 7,443 |
| 寄存器 | 3,279 | 3,279 |
| DSP48E1 | 30 | 30 |
| CARRY4 | 839 | 784 |
| 寄存器之间的最长组合路径 | 15 | 15 |

共享算术减少 123 个独立模块逻辑 LUT 和 55 个 CARRY4，寄存器之间的最长组合路径保持 15 级。完整 SoC 的 DSP 分配和物理 LUT 使用统一测量结果。

`LANES=1/2/3/4` 的完整状态与公开输出比较通过 80,951 个等价位，输入不添加约束。实际 FPGA 窗口检查完成 422 次请求接收、418 次完成、4 次取消和 4,457 个数值，连续响应周期文件与参考版本完全一致。详细数据与源码摘要保存在 `shared_arithmetic_measurement.json`。

```sh
python3 test/conv_frontend/tools/synthesis.py \
  --reference-ref cd312b48 --lanes 4 --out /tmp/frontend_shared_reference
python3 test/conv_frontend/tools/synthesis.py \
  --lanes 4 --out /tmp/frontend_shared_current
python3 test/frontend_rtl_structure/formal.py \
  --reference cd312b48 --cases frontend_l1 frontend_l2 frontend_l3 frontend_l4 \
  --out /tmp/frontend_shared_formal
python3 test/window_dma/run.py \
  --reference-ref cd312b48 --fpga --verilator verilator-modern --jobs 1 \
  --out /tmp/frontend_shared_numeric
```
