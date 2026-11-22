# 权重缓存的 ASIC 同步存储

`kernel_loader_buffer` 在 `ASIC_SYNTHESIS` 配置下采用列存储。生产参数为 `SIZE=16`、`DATA_WIDTH=16`，每列包含 48 个元素，由公共 `regfile` 提供一个同步读取端口和一个写入端口。`ASIC_SRAM` 配置通过现有 SRAM 封装实现这类存储。

两个逻辑槽位保存预取权重，第三个物理槽位保存正在发送的矩阵。每个物理槽位仍保存完整的 16×16 矩阵，共 12,288 个逻辑数据位。槽位交换、输入行接收、有效列屏蔽、丢弃、刷新和输出顺序保持原有周期。发送请求后的第二个周期输出首组权重，后续每周期输出一组。

FPGA 配置继续采用同步行存储。存储布局专用的读取选择寄存器放在相应的生成分支中。

## 当前验证结果

源文件 SHA256：`6766457a21276ab1f722e39ca3928e6025e0929732f1638b145b8b35b35a935e`。

| 检查 | 覆盖范围 | 结果 |
| --- | --- | --- |
| ASIC 布局等价 | SIZE 3、4、16；全部公共输出、公共控制状态和每个物理矩阵元素 | 通过 |
| FPGA 布局等价 | SIZE 3、4、16；全部公共输出、公共控制状态和每个物理矩阵元素 | 通过 |
| SRAM 逐周期数值对照 | SIZE/DATA_WIDTH 为 3/8、4/16、16/8、16/16、32/16；共 500,015 周期 | 通过 |
| SRAM 四态对照 | 同上 5 组参数；709,565 次检查，包含 X/Z、未初始化读取、刷新、复位和同地址读写 | 通过 |
| 完整 kernel_loader 数值测试 | BUS_WIDTH 32、64、128；855 个 tile、218,880 个输出值 | 通过 |
| 存储结构检查 | ASIC 16 个 RAMTP128X16；FPGA 16 个同步矩阵存储体 | 通过 |

完整模块测试覆盖有符号 8 位和 16 位权重、im2col、尾部矩阵、缓存命中、预取进行期间的需求到达、延迟预测、缓存丢弃、刷新，以及 DMA 写入和阵列输出同时进行的情况。三个总线配置均覆盖两个有效逻辑槽位和两个并发 DMA 上下文。C++ 数值测试启用未定义行为检查。

生产配置的 ASIC 状态证明比较 12,895 个状态和输出位，其中矩阵数据占 12,288 位。FPGA 状态证明比较 13,231 位。生产配置的输出证明分成 16 组，各组的位集合完整且互不重叠，外部输入未添加限制。

公共 `regfile` 的 SRAM 实现保存写入请求并转发待提交数据，使逻辑读端保持读取写入前数据的行为。功能 SRAM 模型在物理端口发生同地址读写时终止仿真，以上测试均通过该检查。

## 面积结构

生产配置展开得到 16 个 `RAMTP128X16`、32,768 个物理 SRAM 数据位和 852 个存储外寄存器位。逻辑容量维持 12,288 位。FPGA 展开仍包含 16 个深度 48、宽度 16 的同步矩阵存储体。

上传的 DC 报告中，`kernel_loader/u_buf` 面积为 121,606.2636，宏面积为零。当前修改已经验证 SRAM 结构，修改后的标准单元总面积需由同一 DC 流程重新测量。

## 运行方式

`run_formal.py` 接收包含完整参考文件的目录和待验证源码目录。两个目录均需包含 `kernel_loader_buffer.sv` 与对应的 `regfile.v`，相对路径保持与仓库一致。

```bash
python test/kernel_asic_storage/run_formal.py \
  --reference-root build/kernel_asic_storage/reference \
  --source-root build/kernel_asic_storage/candidate \
  --out build/kernel_asic_storage/formal_partitioned

python test/kernel_asic_storage/run_formal.py \
  --reference-root build/kernel_asic_storage/reference \
  --source-root build/kernel_asic_storage/candidate \
  --fpga --out build/kernel_asic_storage/fpga_formal

python test/kernel_asic_storage/check_structure.py \
  --source-root . --out build/kernel_asic_storage/structure
```

`test/kernel_row_storage/run_numeric.py` 和 `run_four_state.py` 支持重复的 `--define` 与 `--extra-source` 参数，可加入 `ASIC_SYNTHESIS=1`、`ASIC_SRAM=1`、生产 SRAM 封装及 `test/asic_regfile/sram_model.sv`。`test/kernel_prefetch/run.py` 的 `--asic` 参数启用相同 ASIC 配置，`--extra-source` 添加功能宏模型。

`validation.json` 保存源码摘要、各项测试结果、参数、计数和测试报告摘要。
