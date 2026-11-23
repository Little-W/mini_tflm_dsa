# IS 量化移位参数存储

`vec_requant` 的 IS 参数表保存预处理后的 32-bit 乘数和 7-bit 右移量。
每个参数 bank 使用一个 `regfile` 保存右移量，静态深度决定每个存储字容纳的参数数量。

| 每个 bank 的逻辑深度 | 每个存储字的参数数量 | 数据宽度 | 存储深度 |
|---|---:|---:|---:|
| 不超过 128 | 1 | 7 bit | 逻辑深度 |
| 大于 128 | 2 | 14 bit | 逻辑深度除以 2 后向上取整 |

浅表直接逐条写入，数据和控制行为与普通同步 `regfile` 一致。
较深的表在收到偶数地址参数时保存一个 7-bit 暂存值，在收到相邻的奇数地址参数时组成完整的 14-bit 字。
暂存值可以跨越 DMA 响应空拍和突发边界。每个 bank 的最后一条参数由完整 33-bit 末端比较识别，最后不足两条时在响应当拍完成写入，未使用的高半字复制有效值。

读取使用相同的同步使能周期。成对存储时，地址低位与 RAM 读取在同一边沿采样，随后选择对应的 7-bit 半字。
初始化取消未完成的参数对。计算消费的参数索引必须小于该组有效参数数量，尾部填充不进入计算。
原始 32-bit 参数观察接口由 `p_parameter_output` 控制，INT8 和 INT16 使用统一量化算术通道。

## 容量

在 16×16 阵列、64-bit 总线、7 个 8 KiB 共享存储 bank 的配置下：

| IA 紧凑存储 | 最大行分块复用数 | 每个量化 bank 的右移量形状 | ASIC 存储选择 |
|---|---:|---|---|
| 关闭 | 16 | 128×7 bit | 标准单元寄存器阵列 |
| 开启 | 32 | 128×14 bit，保存 256 条参数 | 一个 128×16 bit SRAM |

256 条参数对应 1792 bit 逻辑数据，每个 bank 使用 2048 bit SRAM，容量利用率为 87.5%。
两个 bank 合计 448 B 逻辑数据、512 B 物理 SRAM，位宽填充合计 64 B。
这些数值描述存储几何；完整 ASIC 面积需要包含存储控制、标准单元和宏的实际综合结果。

## 验证

`run_storage.py` 从生产源码提取实际存储逻辑，检查深度 1、2、3、7、8、63、128、255、256、257 和 512。
普通 RTL 模型及严格 SRAM 功能模型均覆盖所有 128 种 7-bit 数据、X/Z 数据、响应空拍、尾部、初始化取消和同步读保持。
SRAM 模型遇到物理端口同地址读写时立即报告失败。

`run_shallow_formal.py` 比较浅表的完整存储状态与输出，不约束读写地址、数据或控制输入。
`run_integration.py` 同时运行当前和指定提交中的 `vec_requant`，两份实现共用当前算术子模块及 `regfile`。
测试逐周期比较 DMA、参数有效信号、组接收许可、原始参数观察输出和量化结果。
数值结果同时与独立整数参考计算比较，覆盖装载中取消和复位、INT8/INT16、WS/IS、整张量/逐通道参数及输出尾部。

```bash
python3 test/requant_parameter_packing/run_storage.py \
  --out build/requant_parameter_packing/storage

python3 test/requant_parameter_packing/run_shallow_formal.py \
  --reference 820c2b18 \
  --out build/requant_parameter_packing/shallow_formal

python3 test/requant_parameter_packing/run_integration.py \
  --reference 820c2b18 \
  --profiles 16:2:16:64:asic 16:2:32:64:asic 16:2:32:64:rtl \
             2:1:1:64:rtl 4:1:3:128:asic 4:1:4:32:asic \
  --out build/requant_parameter_packing/integration

python3 test/requant_parameter_packing/measure.py --depth 128 \
  --out build/requant_parameter_packing/measure128
python3 test/requant_parameter_packing/measure.py --depth 256 \
  --out build/requant_parameter_packing/measure256
```

`measure.py` 统计一个参数 bank 的 ASIC 宏与寄存器结构，并运行 XC7 资源映射。
局部测量将尾部判断作为输入，因此完整模块中的参数末端比较需要在 NPU 综合中评估。
构建产物和完整日志保留在指定输出目录，版本库仅保存源文件及验证摘要。

## 验证结果

当前源码及测试摘要保存在 [`validation.json`](validation.json)。

| 检查 | 结果 |
|---|---|
| 存储四态检查 | 22 个配置，2,922,844 周期，2,877,312 次数据比较通过 |
| 浅表完整状态形式等价 | 6 个深度，1744 个等价位通过 |
| 参数读取选择形式检查 | 32/64/96/128-bit 总线与观察接口开关，共 8 个配置通过 |
| 完整量化逐周期比较 | 6 个配置，1,682,922 周期，390,151 输出行，12,143,600 次数值比较通过 |
| 装载阶段取消 | 60 次初始化清空、60 次复位，重新装载及输出比较通过 |
| 逻辑容量单元测试 | 4 项通过，包含 IA 紧凑存储开关两种配置 |

单个参数 bank 的局部测量如下。ASIC 列统计实际展开的宏及寄存器位数，FPGA 列来自 XC7 综合映射。

| 逻辑深度与实现 | ASIC 宏 | ASIC 寄存器位数 | FPGA LUT | FPGA FF | FPGA RAMB18 |
|---|---:|---:|---:|---:|---:|
| 深度 128，`820c2b18` | 0 | 903 | 0 | 0 | 1 |
| 深度 128，当前实现 | 0 | 903 | 0 | 0 | 1 |
| 深度 256，`820c2b18` | 0 | 1799 | 0 | 0 | 1 |
| 深度 256，当前实现 | 1 个 128×16 | 45 | 17 | 8 | 1 |

深度 128 的寄存器位数包含 896 bit 数据和 7 bit 同步读出寄存器。
深度 256 的 45 个寄存器位用于参数暂存、同步读出选择及通用 SRAM 接口控制，数据阵列位于 SRAM 内。
浅表的 FPGA 存储映射保持不变；较深表为完整字装载和读取选择增加每个 bank 17 LUT、8 FF，局部最长寄存器路径为 1 个组合单元。
