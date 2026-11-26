# 共享存储布局选择

最大分配容量为两个 IA 物理块时，合法配置只包含一块和两块两种布局。布局选择使用一个状态位保存，并由该状态恢复完整块数。完整配置检查继续处理非法输入，容量、各个读写端口和访问周期保持原有定义。四块 IA 容量和较短配置端口使用完整布局寄存器。

地址碰撞检查保留实际支持布局的并行比较。两块最大容量配置只需要不移位和右移一位两种行地址比较。布局状态尚未建立时，完整配置寄存器继续提供原有四态传播。

## 验证

参考提交为 `324eba48`。`run_control.py` 比较全部物理存储读写使能、有效读写地址、字节掩码、写入数据、故障状态及所有同步返回选择状态，并检查布局状态与完整配置块数的归纳关系。

- 通用 IA 端口和配对 IA 端口各完成八组时序归纳证明，共十六组；首次采样复位，其后全部输入及复位自由。
- 参数覆盖每块 2048 或 8192 字节，总块数 6、7、8、9，共享写数据寄存级启用和关闭。
- 两种端口设置共完成 131,072 次四态比较，覆盖初始化前状态、配置切换、未知输入、冲突和非法请求。
- 所有物理存储命令和返回选择保持一致，因此使用相同初始内容的存储继续接收相同更新并返回相同位置的数据。

详细结果及源码散列值见 `layout_validation.json`。

## 完整模块映射

生产配置为七个 8192 字节物理块，启用共享写数据寄存级、非空写请求和配对 IA 端口。使用 physical-cost 映射，目标周期 6667 ps，估算连线延迟 300 ps，最大切分输入数 8。

| 指标 | 参考结构 | 当前结构 |
| --- | ---: | ---: |
| 逻辑 LUT | 1710 | 1638 |
| 触发器 | 12 | 10 |
| RAMB36 | 26 | 26 |
| DSP | 0 | 0 |
| 最长寄存器间组合级数 | 10 | 9 |

完整资源及路径保存在 `layout_measurement.json`。

## 复现

```bash
python test/shared_ia_pairing/run_control.py --reference 324eba48 --out build/shared_layout_generic
python test/shared_ia_pairing/run_control.py --reference 324eba48 --paired --out build/shared_layout_paired
python test/shared_ia_pairing/prepare_layout.py --out build/shared_layout_inputs
python scripts/fpga/open_fpga_synth.py --case-config build/shared_layout_inputs/cases.json --cases reference current --out build/shared_layout_pre --through pre_lut
python scripts/fpga/remap_fpga_luts.py --source build/shared_layout_pre/reference --out build/shared_layout_reference --delay-target-ps 6667
python scripts/fpga/remap_fpga_luts.py --source build/shared_layout_pre/current --out build/shared_layout_current --delay-target-ps 6667
```
