# 深度卷积窗口槽位调度

输入槽位的 `input_ready` 保存当前窗口的数据归属，`input_reserved` 保存后续读取请求。
少于十六路 PE 的深度卷积允许两者同时有效：当前窗口继续供乘加单元读取，后续窗口先进入现有描述符队列。
十六路及以上 PE 在槽位空闲或当前末组消费的同一边沿提交后续请求。
返回数据在当前窗口末组操作数被捕获、对应 `input_ready` 清空后写入。
四个槽位、窗口队列深度和存储容量保持原有配置。

`FAILED` 状态和错误响应允许继续接收已提交请求，随后按原有任务排空条件清空槽位。
其他空间运算保持原有请求资格和响应接收行为。

## 十六路 PE 数值与周期

上传性能环境采用十六路 PE、十六个窗口通道、64 位总线、共享量化、九个 4096 字节共享存储银行，
以及 256 组、两路、128 字节缓存行。外存首次读取延迟为 8 周期，连续数据拍间隔为 1 周期。
使用 `e4415016` 的全部其他生产源码、同一配置和张量重新编译，窗口请求资格是唯一的功能差异。

| 任务 | `e4415016` 周期 | 按槽位消费预约的周期 | 减少周期 |
| --- | ---: | ---: | ---: |
| DW 3×3、48×48、8 通道 | 32,882 | 30,165 | 2,717 |
| Conv 3×3、32×32、16 输入和输出通道 | 28,092 | 28,092 | 0 |

两项任务完整输出文件的 SHA-256 均与相同输入的参考结果一致。
DW48c8 的窗口请求和计算发射均为 20,164 次，缓存请求为 13,348 次，
AXI 读取为 148 次、18,600 字节，输出为 18,432 字节。
等待输入数据的周期从 9,435 减少至 6,718；返回接口没有产生等待周期。

`pe16_validation.json` 保存生产重编译结果、固定源码摘要、完整向量回归和错误恢复结果。

## 八路 PE 数值与周期

两组性能使用上传环境的 Verilator 5.054、相同输入和外存服务重新编译运行。
比较版本为 `f8dc8dd7`，候选只修改窗口请求、返回及预留资格。
每个任务检查完整输出存储内容和输出文件 SHA-256。

| 任务 | 修改前周期 | 提前预约周期 | 减少周期 | 输出字节 |
| --- | ---: | ---: | ---: | ---: |
| DW 3×3、48×48、8 通道 | 27,922 | 26,291 | 1,631 | 18,432 |
| DW 3×3、11×13、17 通道 | 5,564 | 5,449 | 115 | 2,431 |

DW48c8 的 AXI 读取保持 148 次、18,600 字节，缓存读取保持 13,348 次。
等待输入数据的周期从 4,475 减少到 2,844。

完整 `test/vector_engine` 在 BUS32 和 BUS64 各通过 616 项任务，各检查 170,743 个输出。
覆盖深度卷积、池化、S8/S16 向量、Add、Softmax、随机总线等待、参数错误和读写错误恢复。
BUS64 使用八个 PE、八个窗口通道、共享量化和七个 8192 字节共享存储银行；
BUS32 使用八个 PE、四个窗口通道和本地量化。
旧窗口仍标记为就绪时，BUS64 接受 18,163 次请求，BUS32 接受 18,748 次请求；
两种配置分别出现 14,182 和 14,565 个就绪数据与后续预约并存的周期，以及 299 和 611 次返回背压。
窗口错误定向测试另外通过 64 项任务，包括 32 次错误注入和 32 次后续任务恢复。

观察模块分别保存请求中的位置与 tap、已完成返回的位置与 tap，在每次计算发射时
检查实际读取槽位和数据归属。提前预约不会覆盖当前数据的元数据。

## 槽位控制检查

`run_control.py` 直接提取生产模块的请求表达式、响应表达式及全部槽位状态更新。
八路 PE 的直接写入和寄存写入配置分别执行以下情形：

- 四个槽位均已有当前数据，并且各自保留一个后续请求。
- 返回等待期间，当前就绪数据和请求预留保持稳定。
- 当前末组消费只释放数据，后续返回随后形成新的完整窗口。
- 三个槽位仍有当前数据时进入失败状态，继续接受所有待完成返回并排空。
- 清空已结束任务后，再次请求和接收窗口。

十六路 PE 的直接写入配置另外检查已有窗口阻止新请求、末组消费同拍接受请求，
以及已接受请求在失败状态继续完成。三种配置总计完成 983,040 次四态比较和 151 次顺序控制检查。
返回资格遍历全部四态组合，请求资格包括未知槽号、未知预留位、同拍消费和任务错误。

## 资源与路径

完整向量引擎采用 `TILE=16、BUS_WIDTH=64、PE_COUNT=8、WINDOW_LANES=8`、
共享存储和本地量化，使用相同 ABC9 映射参数检查。

| 指标 | 修改前 | 提前预约 |
| --- | ---: | ---: |
| 逻辑 LUT | 9,798 | 9,796 |
| 分布式 RAM LUT | 176 | 176 |
| 触发器 | 6,313 | 6,313 |
| DSP48E1 | 42 | 42 |
| RAMB18E1 | 9 | 9 |
| 最长完整寄存器组合路径 | 10 | 10 |
| 寄存器至窗口请求有效输出 | 7 | 7 |
| 寄存器至窗口响应就绪输出 | 0 | 2 |

两次 ABC9 映射均通过功能验证。响应就绪输出增加两级槽位保护逻辑。
完整 SoC 的连接路径和 150 MHz 布局布线时序由整机报告检查。

## 复跑入口

```sh
python test/vector_window_supply/run_control.py --out build/vector_window_control
python test/vector_window_supply/measure.py --out build/vector_window_mapping

python test/vector_engine/run.py --out build/vector_window_bus64 \
  --pes 8 --bus-width 64 --window-lanes 8 --cache-sets 16 --cache-line-bytes 128 \
  --shared-quant --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7 \
  --stable-stimulus --rtl-assertions --jobs 2

python test/vector_engine/run.py --out build/vector_window_bus32 \
  --pes 8 --bus-width 32 --window-lanes 4 --cache-sets 16 --cache-line-bytes 128 \
  --stable-stimulus --rtl-assertions --jobs 2

python test/vector_engine/run_window_error.py --out build/vector_window_error64 \
  --pes 8 --bus-width 64 --window-lanes 8 --shared-quant \
  --cache-sets 16 --cache-line-bytes 128 --rtl-assertions --jobs 2

python test/vector_engine/run.py --out build/vector_window_pe16_bus64 \
  --pes 16 --bus-width 64 --window-lanes 16 --cache-sets 16 --cache-line-bytes 128 \
  --shared-quant --shared-storage --shared-bank-bytes 4096 --shared-bank-count 9 \
  --stable-stimulus --rtl-assertions --jobs 2

python test/vector_engine/run.py --out build/vector_window_pe16_bus32 \
  --pes 16 --bus-width 32 --window-lanes 4 --cache-sets 16 --cache-line-bytes 128 \
  --stable-stimulus --rtl-assertions --jobs 2

python test/vector_engine/run_window_error.py --out build/vector_window_pe16_error64 \
  --pes 16 --bus-width 64 --window-lanes 16 --shared-quant \
  --cache-sets 16 --cache-line-bytes 128 --rtl-assertions --jobs 2
```

上述仿真入口均支持 `--verilator` 指定工具路径。`validation.json` 保存测试结果、
生产源码摘要、数值输出摘要及映射报告摘要。
