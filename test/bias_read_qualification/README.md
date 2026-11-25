# 偏置驻留判断与同步读取资格

`bias_loader_buffer` 分别计算 IS 组首、IS 后续、WS 首次和 WS 后续读取地址与当前写入地址的相等关系。四个比较结果提前形成，组首触发和读取模式只选择已经完成的同址判断。实际写入资格由有效地址和字节掩码共同确定；发生实际同址写入时，读取资格关闭，同步读输出保持原值。

未知选择输入采用原读取地址的完整相等比较。写入资格按照原有 `if` 规则逐字节计算，保留 X/Z 控制、零掩码写入和输出保持的事件仿真行为。地址计算保留原位宽、索引截断和回绕顺序。

`bias_loader_ctrl` 保留共享加减单元的完整组合模块边界，使状态选择、加减结果和目的寄存器选择按完整函数映射。全部状态寄存器、读写时钟边沿及 DMA 握手周期保持相同。存储器继续使用 `regfile` 的行为描述，由综合工具推断资源。

驻留范围通过三个完整组合函数形成：请求起点与存储体起点比较、请求末端与存储体末端比较，以及初始化清除和存储体有效状态的资格判断。末端比较使用扩展一位的三操作数进位，起点和末端的分组传播条件保持在各自函数内部。已有 `resident_bank` 寄存器仍在原时钟边沿更新；新装载优先撤销相应存储体的有效状态，初始化优先清除驻留资格。

令扩展宽度为 `R = COUNT_WIDTH + 1`，零扩展的请求起点、请求分块数和存储体末端分别为 `A`、`B`、`E`。末端函数计算 `A + B + (2^R - 1 - E)` 的最高进位；由于 `A + B < 2^R`，该进位恰好表示 `A + B > E`。三操作数压缩和最终并行进位保持全部低位及扩展位，完整输入范围参与形式证明。

## 当前 SoC 配置

| 参数 | 值 |
| --- | ---: |
| `SIZE` | 16 |
| `DATA_WIDTH` | 32 |
| `BUS_WIDTH` | 64 |
| `REG_WIDTH` | 32 |
| `COUNT_WIDTH` | 29 |
| `GROUP_BLOCKS_MAX` | 16 |

对照提交为 `87c506be4d2efde77fd94946a3b98bcdd228d235`。两侧采用相同的完整模块依赖和当前 SoC 参数，参数通过实际 `-G` 选项传入 Slang。映射使用 256 个模块一批、组合叶模块隔离及逐模块证明、原生组合辅助模块定义复用。

## 完整偏置加载器映射

| 项目 | 对照版本 | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,307 | 1,315 |
| INV | 14 | 14 |
| FF | 1,148 | 1,148 |
| CARRY4 | 40 | 40 |
| DSP48E1 | 1 | 1 |
| RAMB36E1 | 1 | 1 |
| RAMB18E1 | 0 | 0 |
| 寄存器到寄存器最长组合级数 | 10 | 10 |
| 输入到寄存器最长组合级数 | 10 | 7 |
| 寄存器到输出最长组合级数 | 6 | 5 |
| 输入到输出最长组合级数 | 3 | 2 |

下面的路径均以完整偏置加载器内实际 RAM 的 `ENARDEN` 端口为终点。分析输入端口时，在连接图中加入分析用寄存器标记，未向 RTL 或资源统计添加寄存器。

| 起点 | 对照版本组合级数 | 当前版本组合级数 |
| --- | ---: | ---: |
| `group_read_start` | 5 | 2 |
| `group_read_idx` | 6 | 6 |
| `is_mode` | 6 | 3 |
| 模块内全部寄存器 | 9 | 7 |

完整 SoC 提交 `35408bcf` 的实际连接图中，`o_frame_mode_q` 到偏置 RAM 使能为 15 级，`current_block_idx` 到同一终点为 14 级，`load_block_idx` 到 `resident_bank` 为 13 级。这些路径经过读取资格选择或驻留范围判断，构成本次改写的优化对象。上表记录完整偏置模块内的结果；集成后的整机组合深度由整机连接图重新计算。布局前 LUT 数和组合级数记录于 [validation.json](validation.json)，150 MHz 需要目标器件的布局布线时序报告确认。

## 功能与周期验证

- `run_formal.py` 对 8 组完整加载器配置完成无限时序等价证明，共 9,923 个位关系。参数覆盖 8、16、32、64 位寄存器，1、8、12、29、32、64 位计数器，32、64、128 位总线，以及 1、3、4、16、32 分块容量。外部输入没有范围或握手假设。
- 形式模型保留实际存储器的读写资格及同步输出寄存器，存储字数据使用两侧共用的任意 64 位输入。实际读取资格、完整读写地址、写入数据、字节掩码和写入使能均参与比较。内部对应只使用真实寄存器输出，组合信号全部排除。
- `check_four_state.py` 对 8 组完整缓冲区配置完成 65,552 个周期、131,104 次时钟前后比较。检查所有公开输出、全部状态寄存器、实际存储内容和读取资格。覆盖共享及独立装载索引、组合及寄存驻留模式、1/2/8/29/32/64 位计数器、X/Z 输入、X/Z 复位及初始化、装载与完成同拍。明确发生的同址写入检查为 18,012 次，已知读数据保持检查为 42,351 次。
- 复用 `test/bias_shared_arithmetic/run_numeric.py`，两侧运行相同的 392 项实际存储事务。WS、IS、32/64 位总线和 1/2/4/8/16/32 分块容量的数值、DMA 请求数量及每项周期数全部一致，各用例周期合计均为 193,571。该事务模型使用 `SIZE=16`、`REG_WIDTH=32`、`COUNT_WIDTH=12`。

## 复现

在仓库根目录执行。Python 环境需要 Pyosys/Slang；四态检查使用 Icarus Verilog，数值事务使用支持 C++20 的 Verilator。

```bash
BIAS_READ_OUT=/tmp/bias_read_qualification
BIAS_REFERENCE=87c506be4d2efde77fd94946a3b98bcdd228d235

python test/bias_read_qualification/run_formal.py \
  --reference "$BIAS_REFERENCE" --out "$BIAS_READ_OUT/formal"
python test/bias_read_qualification/check_four_state.py \
  --reference "$BIAS_REFERENCE" --out "$BIAS_READ_OUT/four_state"
python test/bias_shared_arithmetic/run_numeric.py \
  --reference "$BIAS_REFERENCE" --out "$BIAS_READ_OUT/transactions" --jobs 1
python test/bias_shared_arithmetic/prepare_measurement.py \
  --reference "$BIAS_REFERENCE" --out "$BIAS_READ_OUT/inputs"

for version in reference current; do
  python scripts/fpga/open_fpga_synth.py \
    --source-root "$BIAS_READ_OUT/inputs/$version" \
    --case-config "$BIAS_READ_OUT/inputs/cases.json" --cases "$version" \
    --out "$BIAS_READ_OUT/mapping" --lock-file "$BIAS_READ_OUT/mapping.lock" \
    --abc9-batch-size 256 --abc9-isolate-leaves --native-combinational-helpers \
    --require-register-path-limit --max-register-path-cells 10
  python test/bias_read_qualification/analyze_paths.py \
    --netlist "$BIAS_READ_OUT/mapping/$version/mapped.json" \
    --pre-lut "$BIAS_READ_OUT/mapping/$version/pre_lut.il" \
    --out "$BIAS_READ_OUT/mapping/$version/qualification_paths.json"
done
```

功能脚本接受 `--source-root` 和 `--reference`，综合输入准备脚本同时保存全部依赖的 SHA-256。数值脚本支持 `--verilator` 和 `--resume`，只复用源文件及仿真二进制摘要均匹配的已通过结果。路径分析脚本支持普通和 gzip 压缩网表。
