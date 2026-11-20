# LUT 相对位置组与逻辑引脚实现检查

## 工具版本

本次检查使用固定二进制 `nextpnr-xilinx.10357cc430a78c45`，目标器件为 `xc7a200tfbg484-3`。所有新案例和原有独立输出案例使用同一份二进制完成实际打包、布局、布线和 FASM 写出。

| 文件 | SHA256 |
|---|---|
| `nextpnr-xilinx.10357cc430a78c45` | `10357cc430a78c45842554a01c0c6d0ec62d9cba3e656815aae0523560a035b3` |
| `common/placer_heap.cc` | `2c13137cd058f1ad624d9e8c1dfeef612f079519082c85eff645f973847745af` |
| `xilinx/arch_place.cc` | `39f5c5d7db9257c22d57aab2917981e0504d5557acbb1cdae1fabe559c601fdd` |

HeAP 的连通性检查递归访问相对位置组的子单元。组内任意单元具有有效连接时，整个组参与完整放置。共享 LUT 重新排列物理输入时，原逻辑输入编号通过 `X_ORIG_PORT_A*` 保持，INIT 继续表达同一个逻辑函数。

机器可读结果保存在 `docs/data/nextpnr_lut_cluster_validation.json`，包含工具、源码、原语模型、输入网表、布线结果、FASM 和各检查程序的散列值。

## 六个新增实现案例

`run_lut_cluster_connectivity.py` 使用官方 Xilinx `LUT6_2` 和 `FDRE` 模型。六项均固定 `I5=1`，通过保留输出网络使未使用半部参与实际打包和位置约束。所有案例均完成布局、布线和 FASM 检查，每项的 27 个实现单元均具有唯一 BEL。

| 案例 | LUT 输出条件 | 相对位置组 | 结果 |
|---|---|---|---|
| `unused_o6_zero` | O6 为常量 0 且无使用者，O5 有效 | LUT6 → LUT5 | 通过 |
| `unused_o6_one` | O6 为常量 1 且无使用者，O5 有效 | LUT6 → LUT5 | 通过 |
| `unused_o6_logic` | O6 为非恒定函数且无使用者，依赖 I1、I2、I3、I4；O5 有效 | LUT6 → LUT5 | 通过 |
| `unused_o5_logic` | O5 无使用者，依赖 I2、I3、I4；O6 有效 | LUT6 → LUT5 | 通过 |
| `unused_o6_nested_ff` | O6 为常量 0 且无使用者，O5 驱动 5FF | LUT6 → LUT5 → 5FF | 通过 |
| `only_grandchild_connected` | O6 和 O5 均为无使用者的常量函数，仅孙单元 FF 有连接 | LUT6 → LUT5 → 主 FF | 通过 |

两个嵌套案例在实际打包结果上仅添加相对位置属性，检查程序逐项确认单元类型、INIT、端口方向和全部网络连接保持一致。5FF 的相对 Z 为 3，主 FF 的相对 Z 为 2；布局后检查两级 LUT 和 FF 的实际 BEL 是否满足指定关系。

六项检查共完成 768 次源函数与打包函数比较，以及 322 次物理 LUT INIT 输出比较。未使用输出与有效输出均参加函数检查。检查程序还核对五路输入寄存器、结果寄存器和 I/O 缓冲器之间的连接，并检查实际 FASM 的 LUT INIT 与触发器输入选择。

## 既有输出检查

同一固定二进制通过 `run_lut_output_implementation.py` 的四个完整实现案例：`lower_output_feedback`、`upper_output_feedback`、`fixed_zero_select`、`variable_cofactor`。这些案例保留独立输出及动态余因子检查。

`dependent_feedback` 含有真实组合反馈环，严格时序图检查按预期拒绝该设计。

## 完整 SoC 逻辑引脚检查

新增 `check_lut_logical_pin_mapping.py` 可直接比较打包网表与布局或布线网表。脚本顺序加载两个文件以减少内存占用，并支持 gzip 压缩输入。

对于每个普通逻辑 LUT，检查程序核对原类型、INIT、原逻辑输入集合、各输入的实际网络别名和所有输出网络。物理输入可以重新排列，输出允许从 O6 改名为 O5，同一单元驱动的逻辑网络保持一致。共享物理位置的两个逻辑 LUT 同时连接 A1 至 A6 时，对应输入必须连接同一网络。全部实现单元均检查 BEL 的存在性和唯一性。

该检查器已在上述十个完整实现网表中通过验证，合计覆盖 26 个普通逻辑 LUT、77 个逻辑输入连接及 26 个输出网络。检查失败时返回非零状态，并在 JSON 报告中给出具体单元和连接。

```bash
python3 scripts/fpga/tests/check_lut_logical_pin_mapping.py \
  --packed path/to/paired.json \
  --physical path/to/placed.json \
  --out build/lut_logical_pin_mapping.json
```

## 复现完整工具检查

在仓库根目录执行：

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 scripts/fpga/tests/run_lut_cluster_connectivity.py \
  --nextpnr /workspace/scratch/92f7be750f11/toolchain/nextpnr-xilinx/build/nextpnr-xilinx.10357cc430a78c45 \
  --chipdb /workspace/scratch/92f7be750f11/toolchain/chipdb/chipdb-xc7a200tfbg484-3.bin \
  --source /workspace/scratch/92f7be750f11/toolchain/nextpnr-xilinx/xilinx \
  --package-pins /workspace/scratch/92f7be750f11/toolchain/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --tilegrid /workspace/scratch/92f7be750f11/toolchain/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/lut_cluster_connectivity_validated \
  --with-output-regressions
```

`--cases` 可选择指定的独立案例；省略该参数时执行全部六项。`--with-output-regressions` 同时执行原有四个完整实现案例及组合反馈环检查。
