# 定宽加法与四态进位传播

`parallel_prefix_add` 对两个 `p_width` 位无符号输入及一位输入进位执行完整加法，同时输出 `p_width` 位和值和最高位进位。该模块为组合逻辑。

综合主体使用显式零扩展的普通加法。仿真输入含 X/Z 时，按照分组产生、传播与进位关系计算可确定的结果位。`p_group_width` 指定组宽，`p_preserve_groups` 选择分组进位的组织形式；最高组可小于配置组宽。

```bash
python3 test/parallel_prefix_add/run.py --out build/parallel_prefix_add
python3 test/parallel_prefix_add/run.py --asic --out build/parallel_prefix_add_asic
```

每种编译配置完成 28 组全部输入 SAT 证明，覆盖 1、2、3、4、5、8、17、23、24、32、33、47、48、64 位，以及 1 位和 8 位分组。任意输入进位与最高位溢出均参与比较。脚本同时生成输入、输出带寄存器的独立测量电路。

四态传播由 [公共算术验证](../resource_neutral_arithmetic/README.md) 检查。各次运行在输出目录保存具体源码摘要、参数和日志；完整设计的时序与资源使用集成综合结果。
