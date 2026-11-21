# 输出写回的配置与行组计算

## 当前结构

`oa_writer` 在配置接收、请求准备和 DMA 启动之间准备行组信息，输出数据、顺序、背压、请求、启动和完成事件均保持逐周期一致。

首块末尾判断分别读取两个维度的商与余数，再由 WS/IS 模式选择一位结果。计算保留计数宽度截断及向上取整产生的模回绕。初始行数的两个候选分别计算分块数量，完整范围比较仅选择已经完成的候选。

`co_initial_row_tiles_q`、`co_current_row_tiles_q` 和 `co_next_row_tiles_q` 保存模式生效后的行组分块数量。WS 保存对应行数的分块数量，IS 保存 1。输出 FIFO 直接读取 `co_current_row_tiles_q`。

配置接收时保存连续输出资格和行数右移量。合并写回描述符共用每 256 字节对应的行数，进一步右移得到 512、1024、2048 字节段的行数。整除条件由行数低位的零判断生成，保留原有描述符选择顺序和参数位宽语义。

行步长及复用数量在配置接收时保存，组步长在随后已有的 `cfg_lat_tick` 周期计算。首次 DMA 请求消费组步长之前，地址准备流水线已经保存对应结果。范围比较采用完整扩展减法，最高位表示无符号借位；宽减法及末尾索引递减使用行为级 `use_dsp` 属性。

四态仿真保留关系运算与候选合并的未知值传播。综合分支对二值输入的完整模块等价关系单独证明。

## 验证结果

### 形式证明

`run_formal.py` 逐周期比较全部公开输出，并比较共同状态、WS/IS 生效分块值以及消费周期内的地址准备结果。证明包含当前列地址关系、低字节和进位关系、组步长准备关系、下一块选择和配置预计算关系。从复位开始执行时序归纳，配置和握手输入均不施加范围限制。

综合分支通过 11 组参数：`4:32:4`、`8:64:6`、`16:32:7`、`16:64:8`、`16:64:16`、`16:64:29`、`16:64:32`、`32:64:32`、`4:32:4:4`、`8:64:8:8`、`8:64:9:9`。

仿真分支另通过 6 组参数：`4:32:4`、`16:64:29`、`16:64:1`、`12:64:29`、`16:128:29`、`16:64:29:40`。参数依次表示 `VLEN:BUS_WIDTH:COUNT_WIDTH[:REG_WIDTH]`；未指定地址宽度时使用 32 位。

### 逐周期与四态检查

`run_equivalence.py` 使用 Verilator 同时执行当前模块和参考模块，比较全部 21 项公开输出，包括暂停、无效周期、重新配置和复位期间的数据。编译使用 C++20 和未定义行为检查器。

| 检查内容 | 数量 |
|---|---:|
| 参数配置 | 8 |
| 配置场景 | 4,096 |
| 比较周期 | 4,178,136 |
| DMA 命令 | 128,375 |
| 合并组启动 | 19,793 |
| 任务完成 | 2,214 |
| 运行期间重新配置 | 1,429 |

四态检查执行实际 RTL，覆盖每个维度、复用数量和步长输入位的 X/Z 值，以及未知模式、未知列数、数据和字节掩码。四组参数共运行 4,096 个配置、102,780 个周期和 205,556 次公开输出集合严格比较。

`test/oa_fifo_timing/run_formal.py` 复用当前写回几何证明，并保留 FIFO 截断乘积的独立性质检查。生产参数入口及 1～12 位截断乘积的 12 组证明通过。

## 原生 RTL 测量

生产实例参数为 `VLEN=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`REG_WIDTH=32`。采用相同的 Xilinx 原生算术映射与 ABC9 配置，行为级属性选择宽算术映射，完整模块连接图满足完整性检查。

| 项目 | R6 保存的参考模块 | 当前模块 |
|---|---:|---:|
| 逻辑 LUT | 1,235 | 1,138 |
| 触发器 | 940 | 944 |
| DSP48E1 | 8 | 16 |
| CARRY4 | 77 | 41 |
| 最长寄存器间组合级数 | 10 | 8 |

逻辑 LUT 减少 97 个。现有八个行为级 DSP 运算保留，新增宽比较和索引递减使用八个 DSP。实际器件的 150 MHz 时序由完整 SoC 的 Vivado 布局布线报告确认。

`validation.json` 保存参数、通过数量、源码 SHA256、原报告位置与 SHA256。详细报告位于 `build/oa_geometry_r1`；数值与形式脚本也支持从 Git 提交或指定 RTL 文件加载参考模块。

## 运行方法

需要 Python 3、提供 `read_slang` 的 `pyosys`、Verilator、Icarus Verilog 和 C++ 编译器。

```sh
python3 test/oa_writer_geometry/run_formal.py --synthesis \
  --out build/oa_writer_geometry/formal_synthesis

python3 test/oa_writer_geometry/run_formal.py \
  --profiles 4:32:4 16:64:29 16:64:1 12:64:29 16:128:29 16:64:29:40 \
  --out build/oa_writer_geometry/formal_simulation

python3 test/oa_writer_geometry/run_equivalence.py \
  --out build/oa_writer_geometry/numeric

python3 test/oa_writer_geometry/run_four_state.py \
  --out build/oa_writer_geometry/four_state

python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/oa_writer_geometry/synthesis_cases.json --cases oa_writer \
  --out build/oa_writer_geometry/synthesis \
  --wide-alu-dsp-budget 740 --rtl-dsp-attributes \
  --max-register-path-cells 10 --require-register-path-limit

python3 test/oa_fifo_timing/run_formal.py --writer-profiles 16:64:29 \
  --out build/oa_writer_geometry/fifo_integration
```

证明和数值脚本默认参考提交为 `9bb1e28a`。本次保存的完整比较报告使用 R6 源码文件作为参考，其摘要记录在 `validation.json`。Icarus 运行时将正整数宽度参数的 `int unsigned` 声明转写为其支持的 `integer` 形式，模块逻辑保持原样。
