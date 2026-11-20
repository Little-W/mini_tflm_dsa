# 输出 FIFO 检查

S8 输出 FIFO 先选择普通读取或合并读取所需的行列坐标，再共用宽数据选择网络。存储器通过 `REGFILE` 封装，具体资源由综合工具推断。空间检查直接比较预留分组数和已占用分组数，保持数据、字节掩码、输出握手与分组切换的周期行为。

## 功能与形式检查

```sh
python3 test/writeback_bus/run.py --bus-width 32 --reference aa2ef9a3 --out build/writeback32
python3 test/writeback_bus/run.py --bus-width 64 --reference aa2ef9a3 --out build/writeback64
python3 test/writeback_bus/run_selection_formal.py
python3 test/writeback_bus/run_watermark_formal.py
```

功能测试在两种总线宽度下各执行 81 项用例，检查 12,392 个字节，并逐周期比较所有输出。用例覆盖随机等待、转置、合并读取、尾部字节及存储分组复用。

`run_selection_formal.py` 从实际 RTL 提取输出选择逻辑，检查全部输入编码下的数据和字节掩码。参数组合为 `VLEN/BUS_WIDTH` 的 `4/32`、`8/32`、`8/64`、`16/32`、`16/64`、`16/128`、`32/64`、`32/256`。`run_watermark_formal.py` 检查空间计算，包含计数器编码的完整取值范围。

## 独立综合

```sh
python3 test/writeback_bus/measure.py --out build/writeback_measure
```

默认比较提交 `3f2e612` 和当前 RTL，参数为 `VLEN=16`、`BUS_WIDTH=64`、`BANKS=32`，启用转置。Yosys 0.71+40 对共用数据选择网络的测量如下：

| 项目 | 修改前 | 当前设计 |
| --- | ---: | ---: |
| 逻辑 LUT 单元 | 3,261 | 2,161 |
| 触发器 | 1,304 | 1,304 |
| RAM64M | 344 | 344 |
| CARRY4 | 110 | 108 |
| 最长寄存器间组合路径单元数 | 12 | 12 |

上述 LUT 数量为独立模块映射后的逻辑单元数。整机资源占用使用完整 SoC 布局后实际占用的 LUT 位置统计；器件时序使用布局布线后的延迟检查。
