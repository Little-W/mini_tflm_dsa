# 偏置存储容量与访问验证

`bias_loader_buffer` 使用 64 位存储行，两个 bank 分别保存执行和装载所需的偏置。
写入使用逐字节掩码，读取保留一个时钟周期的同步延迟。
`regfile` 将整个存储字的写入掩码转换为 SRAM 位掩码，按逻辑深度选择宏。

在 `SIZE=16` 时，存储配置如下。

| `GROUP_BLOCKS_MAX` | 每个 bank 的 INT32 数量 | 逻辑形状 | ASIC 宏 | 物理容量 | 容量利用率 |
| ---: | ---: | --- | --- | ---: | ---: |
| 16 | 256 | 256×64 bit | 8 个 `RAMTP128X16` | 2 KiB | 100% |
| 32 | 512 | 512×64 bit | 4 个 `RAMTP1024X16` | 8 KiB | 50% |

宏选择同时考虑工艺面积和容量。512 行配置使用较深的宏，以减少宏面积和深度选择逻辑。
具体面积与时序由目标工艺库的综合结果确认。

## 读取与写入

存储使用 `regfile.p_no_change_collision=1`。同一周期对同一物理地址执行
读取和有效字节写入时，保持存储器的 64 位输出；写入掩码未选择的数据位保持原值。
零掩码不会阻止读取。未知有效位按照行为级数组的 `if` 规则处理。

WS 模式在装载期间直接从 DMA 数据准备当前偏置向量，驻留向量读取在 bank
装载完成后进行。IS 模式在 `group_read_start` 保存执行 bank，后台装载使用另一个 bank。
`group_read_start` 必须等待 `bias_group_valid`。验证程序同时检查有效读取与物理写入地址的关系。

## 验证程序

| 程序 | 检查内容 |
| --- | --- |
| `run.py` | 当前 ASIC 与行为级存储的所有公开输出逐周期四态比较，覆盖任意字节掩码、单字节写入、同一 bank 访问、重置、模式切换和未知输入 |
| `compare_protocol.py` | 在实际装载控制器和 DMA 序列中，与指定提交比较全部控制输出、执行上下文存活期间的 IS 标量，以及有效的 WS 向量 |
| `measure.py` | 在相同参数下检查 ASIC 实际宏数量与容量，并比较 FPGA 映射资源和寄存器间组合单元级数 |
| `../bias_vivado150/run_numeric.py --asic` | 使用带物理同址冲突检查的 SRAM 功能模型，验证偏置数值、驻留复用、DMA 请求次数与访问范围 |

协议比较保留原始数值测试，并独立检查新旧实现之间的数据和周期关系。
初次装载时尚未建立执行上下文的读取碰撞可以保持存储输出；执行阶段使用的读取发生碰撞会直接使测试失败。
SRAM 功能模型还会检查宏的物理端口，禁止向宏发出同址读写请求。

## 验证结果

`validation.json` 保存源码散列、配置及各项结果。

| 项目 | 完成结果 |
| --- | --- |
| ASIC 与行为级存储四态比较 | 6 个配置，199,158 个周期，3,584,844 次公开输出严格比较 |
| 与 `820c2b18` 的实际协议比较 | 8 个配置，116,720 个控制周期，46,121 个 IS 标量和 553,984 个 WS 向量元素 |
| 数值与 DMA 检查 | 216 个装载、驻留复用及尾部场景，覆盖 16、32 和 3 个分块的容量 |
| 有效读取地址检查 | 50,278 个 IS 读取周期和 6,192 个 WS 存储读取周期，均未与写入地址冲突 |
| 控制及逻辑存储端口形式比较 | 4 个配置，共 8,124 个等价位 |

相同配置下的独立 FPGA 映射结果如下。

| 分块容量 | 项目 | `820c2b18` | 当前实现 |
| ---: | --- | ---: | ---: |
| 16 | LUT | 613 | 611 |
| 16 | FF | 743 | 743 |
| 16 | `RAMB36E1` | 1 | 1 |
| 16 | 最长寄存器间组合单元数 | 8 | 10 |
| 32 | LUT | 594 | 625 |
| 32 | FF | 747 | 747 |
| 32 | `RAMB36E1` | 1 | 1 |
| 32 | 最长寄存器间组合单元数 | 9 | 10 |

## 运行方法

在仓库根目录运行：

```sh
python3 test/bias_sram_storage/run.py --out build/bias_sram_four_state
python3 test/bias_sram_storage/compare_protocol.py --out build/bias_sram_protocol
python3 test/bias_sram_storage/measure.py --out build/bias_sram_mapping
python3 test/bias_sram_storage/measure.py --group-blocks 32 --out build/bias_sram_mapping32
python3 test/bias_vivado150/run_numeric.py --asic --out build/bias_sram_numeric
```

每次执行均保存源码快照、SHA-256、构建和运行日志，以及 `summary.json`。
FPGA 结构级数记录实际映射后的组合单元连接；工作频率由器件时序分析确认。
