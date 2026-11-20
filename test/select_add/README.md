# 定宽选择加法验证

`select_add` 从两个有符号右操作数中选择一个，并根据 `i_add_enable` 决定
执行加法或输出左操作数。结果按 `2^p_width` 取模。模块不保存状态，输入到
输出为组合逻辑；原有接收边沿、有效标志和复位处理由调用模块保持。

七系列 FPGA 实现使用普通条件表达式选择右操作数，通过 `DSP48E1` 的
`OPMODE` 选择相加或旁路。DSP 的数据、控制和结果寄存器均旁路。
`A_INPUT` 和 `B_INPUT` 使用直接输入，`ACIN` 和 `BCIN` 固定为零。
每个实例使用一个 DSP，选择逻辑由综合工具根据 RTL 生成。

`p_width=48` 且 `p_split_12bit=1` 时，四个 12 位通道分别执行模加；
其他配置使用一个完整位宽的运算通道。通用实现保持相同的算术行为。

## 形式验证

```sh
python3 test/select_add/run_formal.py --out build/select_add_formal
```

验证直接加载 Yosys 安装目录中的 `DSP48E1` 功能模型，
覆盖 1、17、32 和 48 位配置的全部输入组合。每个配置检查扩展一位后再截断
的数学结果、通用实现与 FPGA 实现的一致性，以及 NPU 的 WS/IS 偏置选择
表达式。测试同时覆盖带符号数、模加溢出、使能旁路和奇数位宽的末位选择。

## 完整 NPU 验证

```sh
python3 test/select_add/run_npu.py --out build/select_add_npu --verilator verilator --sizes 4 --jobs 2
```

该命令使用实际 FPGA 原语运行完整 NPU 的六个用例，包括 WS、IS、INT8、
INT16、逐通道量化、尾块和 INT16 输出。内存比较检查输出值与完整存储范围。
源码、编译参数、原语库摘要和周期统计保存在输出目录中。

## 资源和组合路径

```sh
python3 scripts/fpga/open_fpga_synth.py --case-config test/select_add/cases.json \
  --cases select_add_reference select_add_candidate --out build/select_add_resources
```

测量文件在两种表达式两端加入相同的寄存器，形成可以统计的寄存器间路径。
每个配置包含 130 个测量边界寄存器，`select_add` 本身含零个寄存器。
每次测量分别记录参考表达式与当前实现的 LUT、进位单元、DSP 和组合路径，
并保存实际源码与工具库的 SHA-256。

完整 SoC 可以共享各通道的控制逻辑，其资源总数由全设计综合统计。
组合单元数描述逻辑结构，150 MHz 时钟要求使用器件布局布线后的延迟分析。
