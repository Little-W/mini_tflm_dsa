# 权重加载器请求资格与分组边界

需求请求和预取请求先独立检查控制状态，槽位可写信号在末端参与请求选择。分组结束与重复结束各自保留完成资格，列位置递增独立形成结果。计数递增仅保留实际参与结果进位的完整分组，最高组的越界进位可由综合工具删除。

`kernel_count_next_reaches` 使用相邻两位的加一比较，完整计数回绕仍由无符号边界关系处理。所有接口、计数宽度、数据容量与逐周期行为保持一致。

## 完整模块测量

使用 `SIZE=16`、`COUNT_WIDTH=29`、`BUS_WIDTH=64`，同时定义 `SYNTHESIS` 和 `XILINX_FPGA`。参照提交为 `142a7226`。两份完整加载器使用相同映射设置：6667 ps 目标、300 ps 连线成本和最多八输入 LUT 的物理位置成本；ABC9 映射功能检查均通过。

| 项目 | 参照实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 2,902 | 2,908 |
| 完整模块最长组合路径 | 10 | 10 |
| 槽位状态到装载请求 | 5 | 4 |
| 槽位状态到 DMA 启动 | 6 | 5 |
| 分组边界到列位置 | 10 | 9 |
| 列位置到下一列位置 | 8 | 7 |
| 预取状态到传输长度 | 7 | 6 |
| 行步长到 DMA 地址 | 4 | 4 |

端口路径在分析副本中连接到观察终点，生产 RTL 的接口时延没有增加。完整 SoC 的实际路径与资源另行综合检查。原始输入摘要、映射结果和逐项路径见 `measurement.json`。

## 功能检查

- 八种完整控制器配置通过 58,557 个等价点，四种完整加载器配置通过 49,107 个等价点。通用模式显式取消 `SYNTHESIS` 和 `XILINX_FPGA`，FPGA 模式显式定义两者，全部公开输出和共同状态参与比较。
- 六种计数宽度分别在通用与 FPGA 条件下完成任意输入证明，共十二项，并完成 98,304 次四态比较。递增结果与参照模块比较，完成资格与完整模宽加一后的无符号关系比较。
- 从生产源码提取请求计算，完成任意输入证明，并穷举全部 16,384 种四态控制组合。
- 完成条件穷举 262,144 种四态组合；请求和描述符选择检查 4,194,304 种四态控制组合，执行 67,108,864 次描述符位比较。

结果见 `validation.json`。复现命令如下：

```bash
python3 test/kernel_completion/run.py --reference 142a7226 --out build/kernel_eligibility/control
python3 test/kernel_port_selection/run.py --reference 142a7226 --out build/kernel_eligibility/parent
python3 test/kernel_eligibility/check_arithmetic.py --out build/kernel_eligibility/arithmetic
python3 test/kernel_eligibility/check_request.py --out build/kernel_eligibility/request
python3 test/kernel_eligibility/measure.py --out build/kernel_eligibility/measurement
```
