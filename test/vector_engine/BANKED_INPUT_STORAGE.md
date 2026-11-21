# 向量输入银行与 Softmax 指数存储

## 当前结构

生产配置采用 16 通道、8 个 PE、64 位总线和 8 路窗口响应。输入存储由 8 个银行组成，每个银行保存 4 个完整的 16 位元素。向量、Add 和 Softmax 共用各银行的读取端口，标量输入字节在使用前经过寄存。数组由普通 SystemVerilog 读写语句描述。

窗口响应的数据、银行地址、有效掩码、标签和结束信息一起保存。下一时钟边沿写入输入存储并发布该窗口的完成状态。`win_rsp_ready` 连续有效，能够每周期接受一个已发送窗口的数据响应；异常结束时等待已保存响应提交后释放输入预留。

Add 在限幅和结果写入阶段准备下一项输入。Softmax 的 `INPUT_REGISTERED` 参数控制同步输入读取，生产配置启用该参数。最大值搜索和指数表请求分别设置读取准备状态，每个输入元素各增加一个准备周期。参数默认值为零，适用于原有组合读取接口。

Softmax 指数存放于独立的 `TILE × 32` 普通数组，使用一个写入端口和一个异步读取端口。指数写入资格、输出写入资格及对应下标保存一个周期，数值由已有的指数响应和舍入结果寄存器提供。累加数组保存 PE、池化和最终字节结果。

写回请求先保存地址、长度及结果所属位置，内部接收事件经过寄存后释放结果存储。银行写回模块在发布请求时保存首拍掩码、尾拍掩码和总拍数；发送过程中按剩余拍数更新掩码，暂停期间保存当前数据与掩码。

坐标范围、下一通道位置、窗口读取阶段和全局池化完成条件提前保存。配置检查器在计算部分乘积的周期同时保存图像尺寸和填充量，随后执行范围比较。

## 独立综合结果

使用生产参数、Xilinx 7 系列映射以及 RTL 算术属性处理。共享量化关闭，共享权重和部分和存储开启。

| 项目 | 数值 |
|---|---:|
| 逻辑 LUT | 12,132 |
| 分布式存储名义 LUT | 176 |
| 名义 LUT 总数 | 12,308 |
| 触发器 | 6,283 |
| DSP48E1 | 52 |
| RAMB18E1 | 9 |
| 寄存器间最长组合单元数 | 10 |

连接图遍历完整。与提交 `42a820c7` 的同参数独立测量比较，名义 LUT 减少 586，触发器减少 402。名义资源数量来自映射网表，完整 SoC 的资源数量与 150 MHz 布局布线结果由整机测量确定。

## 功能与协议验证

- 生产参数回归通过 615 个任务、170,668 个数值输出，包含 143 个 Add 任务和 273 个 Softmax 任务，启用内部断言及共享权重预取地址和内容检查。
- Softmax 同步读取在最大深度 1、16、256 下通过 130,581 个任务和 14,717,968 个元素，启用整数未定义行为检查。
- Softmax 默认输入参数在两种乘法器延迟和两种算术配置下通过完整公开接口形式等价检查。
- 配置检查器在 `TILE=4/16/64` 下通过逐周期等价检查，任务处理期间保持配置有效；激活范围检查覆盖全部 64 位输入组合。
- 32 位和 64 位总线共通过 96 个窗口异常及恢复任务，包含 48 次异常注入及 48 个后续正确任务，覆盖所有字节偏移、跨页位置、固定和随机暂停、共享量化并发及完成后停止发送。
- 银行写回通过 9 种参数配置、11,940 个请求和 721,931 个输出字节，覆盖 656 次错误响应和 7 次部分请求取消，并检查连续发送和暂停期间负载稳定。

615 个数值任务的周期总数为 3,258,441；同一组任务在提交 `42a820c7` 下为 3,249,476，增加 8,965 个周期，约 0.276%。增加的准备和完成周期不改变已接受窗口响应的连续接收能力及写总线连续发送能力。

精确源码散列、各项报告散列及连接图统计保存在 `banked_input_validation.json`。

## 复现

以下命令在仓库根目录执行，工具需位于 `PATH`。

```bash
python scripts/fpga/open_fpga_synth.py --out build/vector_input_measurement --case-config test/vector_engine/production_synthesis_cases.json --cases vector --wide-alu-dsp-budget 740 --rtl-dsp-attributes --max-register-path-cells 10 --require-register-path-limit
python test/vector_engine/run.py --out build/vector_input_production --pes 8 --tile 16 --jobs 1 --cache-sets 16 --cache-policy 3 --cache-line-bytes 128 --bus-width 64 --window-lanes 8 --shared-storage --shared-bank-bytes 8192 --shared-bank-count 7 --shared-ia-banks 2 --check-weight-prefetch --rtl-assertions --stable-stimulus --xilinx
python test/vector_softmax/run.py --out build/vector_softmax_registered --depths 1 16 256 --input-registered --jobs 1 --xilinx
python test/vector_softmax/run_formal.py --out build/vector_softmax_default_formal --reference-rev 42a820c7
python test/vector_config_ranges/run.py --out build/vector_configuration_formal --reference 42a820c7 --stable-config
python test/vector_engine/run_window_error.py --out build/vector_window64 --bus-width 64 --window-lanes 8 --shared-quant --cache-sets 16 --cache-line-bytes 128 --rtl-assertions --jobs 1
python test/vector_engine/run_window_error.py --out build/vector_window32 --bus-width 32 --window-lanes 8 --shared-quant --cache-sets 16 --cache-line-bytes 128 --rtl-assertions --jobs 1
python test/vector_banked_writeback/run.py --out build/vector_banked_writeback_current --jobs 1
```
