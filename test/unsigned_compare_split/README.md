# 无符号比较的分段减法

`unsigned_compare` 对 FPGA 配置中的 24～46 位输入使用两段普通无符号减法。每段增加一位零扩展，最高结果位表示该段借位。高段不相等时使用高段结果，高段相等时使用低段借位。两个差值均为零时，完整输入相等。

算术表达式由 `parallel_prefix_native_differences` 保存组合模块边界，并使用 `use_dsp="simd"` 指定资源推断偏好。源代码只声明普通减法和逻辑表达式。`p_split_compare=0` 使用按字节分组的比较；其他位宽及普通编译配置也采用分组实现。两种实现对未知输入使用相同的四态关系计算。

## 验证范围

`run.py` 检查 1、2、7、16、23、24、25、27、28、31、32、33、40、46、47、64 位输入，分别采用普通、FPGA 和 FPGA 综合三种编译条件。每种配置同时检查启用与关闭分段减法的输出。

全部 48 组二态全输入证明通过。四态检查共 178,080 组输入、356,160 次输出比较，覆盖零、全一、相等、相邻值，以及各个输入位分别包含 X 和 Z 的情况。记录见 `validation.json`。

## 独立综合

32 位比较器的输入和输出均设置寄存器，源文件与配置记录在 `measurement.json`。差值按六位独立检查零值，最后同时形成大小关系和相等关系。

| 指标 | 字节分组比较 | 分段减法比较 |
| --- | ---: | ---: |
| 逻辑 LUT | 30 | 8 |
| DSP | 0 | 1 |
| 进位单元 | 4 | 0 |
| 触发器 | 66 | 66 |
| 寄存器间最长组合级数 | 4 | 3 |

该改写不增加时钟周期。整机资源和最长组合路径采用完整 SoC 连接图另行测量。

```bash
python3 test/unsigned_compare_split/run.py --out build/unsigned_compare_split
python3 test/unsigned_compare_split/measure.py --out build/unsigned_compare_split_area
```
