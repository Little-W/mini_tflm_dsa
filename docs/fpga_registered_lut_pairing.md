# 带寄存器的 LUT 双输出共享

`scripts/fpga/pair_registered_luts.py` 在完成打包的网表中识别独立的
LUT 与触发器组，将两组兼容单元放入同一个物理 LUT 位置。
两个逻辑输出分别使用 O6 和 O5，触发器分别使用 FF 和 5FF。
逻辑函数、信号连接、触发器初值及复位值保持一致。

## 选择条件

- 两个 LUT 各自只有一个输出，且该输出仅连接本组触发器的 D 输入。
- 每对 LUT 的输入并集至多包含五个信号，至少共享一个非常量输入。
- 两个触发器的时钟、使能、复位、时钟极性、复位极性和同步模式相同。
- 保留已有的 LUT 与触发器组关系，排除固定位置、存储 LUT、锁存器、
  进位组和其他相对位置组。
- 所有新组内部保持 LUT 至触发器的相对距离，组本身可以在器件上移动。

5FF 的输出使用本位置的 OUTMUX，因此 O5 只连接本地 5FF 的 D 输入。
候选筛选同时检查其他单元和顶层端口，防止 O5 与 5FF 输出竞争该资源。

工具在修改相对位置属性前后计算逻辑单元摘要。摘要包含全部原语、连接、
参数及非位置属性，要求修改前后完全相同。物理 LUT 占用由随后的合法布局
统计，候选配对数量单独记录。

## 实际器件检查

使用 `xc7a200tfbg484-3` 数据库和已保存 SHA-256 的 nextpnr 二进制，
四种设计均完成布局、布线和 FASM 输出检查。

| 设计 | 配对数量 | 修改前物理 LUT | 修改后物理 LUT | 触发器数量 |
| --- | ---: | ---: | ---: | ---: |
| 同步复位、相同控制 | 1 | 2 | 1 | 2 |
| 异步复位、相同控制 | 1 | 2 | 1 | 2 |
| 同步置位、相同控制 | 1 | 2 | 1 | 2 |
| 不同使能 | 0 | 2 | 2 | 2 |

验证从实际布线文件读取引脚及 SITEPIP 选择，检查 LUT INIT、FFMUX、
FF5MUX、OUTMUX、初值、复位值、时钟极性和共享控制配置。八份实际布线
结果共检查 512 个触发器状态转移组合和 272 个 LUT 输入组合，均通过。
另有七项工具检查覆盖输入数量、控制不兼容、外部使用者、固定资源、
相对位置以及重复组。

在固定 RTL `1c081bc` 的完整 SoC 打包文件中，普通 LUT 共享已包含
3,524 对。该工具另外识别 11,216 个可用 LUT 与触发器组，产生 2,183 对
候选。其逻辑单元摘要保持相同，完整 SoC 的物理占用等待合法布局结果。

## 运行命令

```sh
python3 scripts/fpga/pair_registered_luts.py \
  --packed build/soc/ordinary_paired.json \
  --out build/soc/registered_paired.json \
  --report build/soc/registered_pairing.json

python3 scripts/fpga/tests/test_pair_registered_luts.py

python3 scripts/fpga/tests/run_registered_lut_pair_implementation.py \
  --nextpnr /path/to/nextpnr-xilinx \
  --source /path/to/nextpnr-xilinx/xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --tilegrid /path/to/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/registered_lut_validation
```

工具版本、网表摘要和逐项测量保存在
[寄存 LUT 共享验证数据](data/nextpnr_registered_lut_pair_validation.json)。

## 寄存输出与组合输出共享

`scripts/fpga/pair_mixed_luts.py` 将剩余的独立 LUT 与触发器组和普通
组合 LUT 配对。寄存结果使用 O6 和 FF，组合结果使用 O5 和 OUTMUX。
原有触发器相对位置、全部逻辑和初值保持一致，输入并集仍至多五个。

实际器件检查中，共享输入设计由两个物理 LUT 位置减少至一个，保留
原有触发器；六个独立输入的设计保持两个位置。修改前后均完成布局和
布线，检查 128 个触发器状态转移组合和 112 个 LUT 输入组合，并核对
实际 FASM 的 O5 输出选择。五项工具检查覆盖依赖关系、专用使用者和
已有相对位置。

在上述完整 SoC 候选文件中，完成普通 LUT 和寄存 LUT 配对之后，另有
95 对满足该规则。完整 SoC 面积继续使用最终合法布局的位置统计。

```sh
python3 scripts/fpga/pair_mixed_luts.py \
  --packed build/soc/registered_paired.json \
  --out build/soc/mixed_paired.json \
  --report build/soc/mixed_pairing.json

python3 scripts/fpga/tests/test_pair_mixed_luts.py
```

逐项配置和实际器件结果见
[组合与寄存 LUT 共享验证数据](data/nextpnr_mixed_lut_pair_validation.json)。
