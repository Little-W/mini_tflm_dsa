# 部分和读取请求的最终使能

## 实现

`ps_channel_read_enable` 将读取请求、地址范围、目标银行、配置访问许可和当前通路使能同时组合为一个读取条件。`ia_ps_channel_ram` 用该条件驱动固定部分和 RAM 的读取使能，并控制返回银行编号的接收。

五个输入均为单比特信号，模块采用普通逻辑与表达式。请求与访问许可直接参与最终条件，地址比较继续独立准备。存储容量、物理读写端口、读返回保持、错误检测、配置接收和请求周期保持一致。读取条件在包含 `X` 或 `Z` 的输入下与原有分组逻辑与表达式相同。

FPGA 独立返回配置使用各自的端口读取条件。通用返回配置仍保留共享读端口的组合选择。`ps_read_selection_eligible` 仅在通用返回配置中保留综合属性。

## 验证

参考提交为 `584233d8`。

- 五种完整共享通道配置分别在通用和 FPGA 编译模式下检查，共 10 项时序归纳证明。除首次采样复位外，全部功能输入和后续复位逐周期自由。比较内容包括全部物理端口的使能、地址、数据与掩码，全部读返回、配置状态、返回选择状态及容量错误。
- 五种配置在两种编译模式下各运行 8,192 个四态周期，共 81,920 个周期。测试直接实例化真实 RAM 数组，并逐周期比较全部内容和返回数据，覆盖并发请求、暂停、配置变化、容量错误及未知控制值。
- 新组合模块枚举全部 `4^5 = 1,024` 种四态输入，两种编译模式合计 2,048 次比较。

`validation.json` 保存源码摘要、形式验证记录、四态检查统计和中文注释检查结果。

## 完整通道测量

采用生产参数：物理存储块为 8 KiB，总容量为 56 KiB，启用共享写入寄存级、配对 IA 端口和独立返回。两侧使用相同的 `physical-cost` 映射设置，最大 LUT 输入数为 8，线延时参数为 300 ps，目标周期为 6,667 ps。

| 项目 | 参考设计 | 当前设计 |
| --- | ---: | ---: |
| 包含 LUTRAM 与 SRL 的名义 LUT | 1,162 | 1,146 |
| 完整通道最长寄存器间组合级数 | 9 | 10 |
| FF | 10 | 10 |
| DSP | 0 | 0 |
| RAMB36 / RAMB18 | 34 / 0 | 34 / 0 |
| PS 读取请求到固定 RAM 读取使能 | 3 | 1 |
| PS 读取请求到返回银行选择寄存器 | 2 | 1 |
| 通路使能到固定 RAM 读取使能 | 2 | 1 |

完整通道最长路径的起止状态为 `g_two_bank_layout.two_banks_q` 和 `o_capacity_fault`。定向路径通过实际映射连线计算，资源和完整路径记录见 `measurement.json`。

## 运行方法

```sh
python3 test/ps_read_selection/run.py --out build/ps_read_selection/checks
python3 test/ps_read_selection/measure.py --out build/ps_read_selection/measurement
python3 test/rtl_layout/check_comments.py --out build/ps_read_selection/comments
```

`run.py` 复用 `test/ps_shared_read_control/run_shared.py` 中的完整共享通道比较过程，增加当前读取使能模块及独立四态组合检查。通用 Slang 读取显式使用 `-USYNTHESIS -UXILINX_FPGA`，FPGA 模式显式定义二者。
