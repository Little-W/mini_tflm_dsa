# im2col 前端设计与验证

前端接收卷积配置和 IA 分块描述符，生成按矩阵行列排列的十六位输入数据。INT8 输入在读取后加入配置偏移量，INT16 输入直接传递。窗口缓存、预取、输出背压和描述符排队使用同一套公开接口。

## 模块职责

| 文件 | 职责与寄存边界 |
|---|---|
| `conv_im2col_frontend.sv` | 接收任务配置，调度坐标准备、地址形成和输出传输；保存配置与当前分块上下文。 |
| `conv_im2col_geometry.sv` | 共享配置和运行期乘法，计算坐标、历史位置、通道纪元与地址增量。配置计算分为四个阶段，32×16 乘积通过两路 16×16 部分积寄存后合并。 |
| `conv_im2col_descriptor.sv` | 准备并保存分块描述符，计算窗口关系及提交坐标，选择提交时的地址增量。 |
| `conv_im2col_stream.sv` | 保存输出地址、通道范围和字内范围，生成逐通道输出掩码及缓存请求。1～16 通道共用范围寄存与固定步长选择结构。 |
| `conv_im2col_prefetch.sv` | 保存一份预取上下文，分阶段计算横纵坐标、像素和字节地址，最后发出预取请求。 |
| `conv_im2col_frontend_pkg.sv` | 定义共享状态编码。 |
| `include/conv_im2col_prepared_tile.svh` | 定义各阶段共用的描述符字段；`kernel_x` 和 `kernel_y` 各为 16 位。 |

历史位置在 `P_HISTORY` 保存范围判断和行列候选。坐标减法先保存低位及借位，再形成高位坐标。地址计算依次保存像素乘积、组合后的地址项和通道地址；`ADDRESS_MATCH` 使用已保存的地址判断缓存字命中。数据与对应控制字段在同一阶段更新。

通道纪元计算直接使用输出模块生成的独热步长选择，传输数量另行编码并保留原有用途。配置阶段只向调度模块传递乘积低 32 位，同时保留完整 48 位乘积用于溢出检查。

普通 tile 地址排列由调用接口决定。前端输出的十六位数据可以交给 IA 存储路径选择存储格式。

## 数值与协议检查

```bash
python3 test/frontend_pipeline/run_numeric.py \
  --target asic --size 16 --lanes 16 --bus-width 64 \
  --cache-sets 16 --cache-ways 2 --line-bytes 128 \
  --narrow-mode 2 --windowed --prefetch \
  --out build/frontend_pipeline/numeric16

python3 test/frontend_pipeline/run_numeric.py \
  --target fpga --size 16 --lanes 8 --bus-width 64 \
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
| ASIC 宏、16×16、16 通道、窗口与预取 | 42 | 158950 | 2160 | 2159 | 2118 | 21838 |
| FPGA 宏、16×16、8 通道、窗口与预取 | 42 | 182366 | 2160 | 2159 | 2118 | 26728 |
| FPGA 宏、4×4、2 通道、直连描述符 | 42 | 1258434 | 11573 | 11572 | 11573 | 59128 |

每种配置包含一个预期 AXI 错误任务。三种配置合计通过 126 项任务、1599750 个周期和 3072 组配置检查。八通道与十六通道配置的最小描述符接收间隔均为一个周期。

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
```

| 检查对象 | 输入范围与性质 | 结果 |
|---|---|---|
| 通道纪元计算 | 1～16 通道；完整 16 位组偏移和通道位置；传输数量为零至通道总数。 | 16 项形式证明通过。 |
| 独热步长选择 | 1～16 通道；实际输出掩码满足连续前缀性质；同时检查纪元结果和传输数量。 | 16 项形式证明通过。 |
| 通道范围与行末条件 | 1～16 通道；完整 16 位通道回绕；4/8 通道窄输出选择；连续与通用掩码选择。 | 100 项形式证明通过。 |
| 行末四态逻辑 | 1、2、4、8、16 通道；逐位生成 0、1、X、Z。 | 500000 次比较通过。 |
| 历史位置 | 完整 32 位位置、33 位位置差、完整 16 位输出宽度；配置、提交与历史保存事件互斥。 | 两步复位检查和一步无界归纳通过。 |

历史位置检查包含行范围、上限溢出和两个模行尾等式。历史上限只输出所需的进位，运算保留完整位置范围。

## 纪元选择逻辑的局部映射

`check_epoch_selection.py` 从实际 RTL 提取表达式，使用相同的输入、输出寄存器和传输数量输出，对十六通道纪元选择逻辑执行 xc7 映射。连续前缀掩码性质同时由数值回归中的协议断言检查。

| 指标 | 传输数量编码后选择 | 直接使用独热步长 |
|---|---:|---:|
| LUT | 295 | 250 |
| CARRY4 | 78 | 75 |
| 寄存器位 | 71 | 71 |
| 最长组合单元级数 | 10 | 9 |
| 输出掩码到纪元的组合单元级数 | 7 | 5 |

这些结果仅覆盖独立的纪元选择逻辑，属于布局前映射。级数包含映射后的 LUT 与进位单元；完整 SoC 的 150 MHz 时序及资源总量由综合和实现报告确定。

## RTL 结构统计

```bash
python3 test/frontend_pipeline/measure_structure.py \
  --out build/frontend_pipeline/structure
```

统计使用 16×16、16 通道、64 位总线、16 组缓存、每行 128 字节的配置。位宽优化后的前端包含 4765 个寄存器位、8 个 16×16 乘法运算和一个截断为 32 位结果的 32×31 乘法运算。这些数值描述 RTL 运算和状态规模；器件 LUT、标准单元面积和时序由对应综合及实现工具报告。

具体参数、输入摘要、通过项目与日志摘要见 [validation.json](validation.json)。
