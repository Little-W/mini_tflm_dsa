# 前端描述符选择与请求元数据计算

`conv_im2col_frontend` 在接收连续窗口描述符时，将坐标边界判断和请求纪元计算放在选择器之前，并限制配置移位和通道地址运算的有效位宽。配置、描述符、缓存请求、响应和输出写入保持原有接收周期。

参考提交为 `d9abf98cf2b32b0ef87446d41a100c4ceda9bc23`。本次修改的前端源码 SHA-256 为 `6c7776acd8b01d9a5b9a6e3fb30a851c82498b7e0be2ebb50db5c0e4a755f06e`。

## 组合结构

三种描述符坐标分别对应保存的行首、下一卷积核列和下一卷积核行。每种坐标独立计算填充条件，描述符选择已经完成的布尔结果。坐标仍使用 35 位有符号数，加法显式扩展一位并接收舍弃的最高位。

`tile_q0 < reduction_len` 分成四个并行的字节比较，由最高不同字节决定最终结果。描述符的行范围检查复用 `tile_rows_in_range`，覆盖低位求和进位以及位置上界。

当前请求和新描述符请求各自完成通道偏移、数据宽度移位和缓存行移位，`incoming_context` 最后选择请求纪元。短像素请求的纪元保持为零。

缓存行长度为二次幂时，短像素移位编码只检查缓存行范围内的位。16 字节缓存行的移位值为 0 至 4，高两位可以化为常量。其他缓存行长度继续使用原来的编码表达式。

通道索引宽度为 16 位，字节偏移至多为 17 位。通道地址的低 17 位求和与高 15 位加一并行执行，最后按低位进位选择高位，结果保持 32 位模加语义。

## 独立模块资源

两份源码均使用原生 XC7 综合，参数为 `SIZE=16`、`LANES=2`、`BUS_WIDTH=64`、`CACHE_SETS=128`、`CACHE_WAYS=2`、`LINE_BYTES=16`、`CACHE_POLICY=3`。缓存和预测器在资源测量中作为接口边界，因此表内只统计前端。完整功能证明使用实际缓存和预测器，生产缓存容量为 4,096 字节。

| 项目 | 参考版本 | 当前版本 | 变化 |
| --- | ---: | ---: | ---: |
| 逻辑 LUT | 6,472 | 6,435 | −37 |
| 触发器 | 3,230 | 3,228 | −2 |
| DSP48E1 | 30 | 30 | 0 |
| CARRY4 | 720 | 724 | +4 |
| 最长内部寄存器间组合单元数 | 21 | 20 | −1 |

资源统计采用综合映射后的逻辑单元数量。物理 LUT 位置和 150 MHz 时序由完整 SoC 的布局布线测量。

## 输入至消费寄存器的路径

路径工具沿实际单元连接统计起点到终点，分别处理 `LUT6_2` 的输出和 `CARRY4` 的逐位依赖。接口观察寄存器只存在于分析图中，资源统计使用完整原始网表。

| 起点 | 消费寄存器 | 参考组合单元数 | 当前组合单元数 |
| --- | --- | ---: | ---: |
| `tile_p0` | `state` | 13 | 12 |
| `tile_p0` | `request_index_q` | 14 | 12 |
| `tile_p0` | `request_epoch_q` | 14 | 8 |
| `tile_q0` | `state` | 14 | 14 |
| `tile_q0` | `request_index_q` | 14 | 13 |
| `tile_q0` | `request_epoch_q` | 14 | 9 |
| `tile_q0` | `addr` | 9 | 10 |
| `tile_valid` | `request_index_q` | 8 | 6 |
| `tile_valid` | `request_epoch_q` | 8 | 2 |
| `tile_rows` | `request_index_q` | 14 | 11 |
| `tile_rows` | `request_epoch_q` | 14 | 7 |
| `wr_ready` | `addr` | 8 | 7 |
| 缓存 `rsp_valid` | `addr` | 9 | 8 |

当前最长内部路径为 `kx_q[6]` 到 `state[1]`，经过核末列比较、下一核位置的 35 位加法和控制选择，共 20 个组合单元。完整 SoC 的 15 个组合单元目标需要继续缩短这部分及模块之间的控制路径。

## 完整功能检查

形式证明读取真实前端、缓存、预测器、AXI 读控制和存储封装。展开全部层次并映射存储后，比较公开输出及内部同名信号，使用 SAT 和时序归纳完成检查。输入未施加限制，配置、复位、描述符、响应和背压信号均参与证明。

| `SIZE` | `LANES` | `BUS_WIDTH` | `CACHE_SETS` | `CACHE_POLICY` | 等价位数 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 1 | 32 | 8 | 0 | 6,992 |
| 4 | 2 | 32 | 8 | 1 | 7,044 |
| 8 | 4 | 64 | 8 | 2 | 7,139 |
| 16 | 2 | 64 | 128 | 3 | 86,987 |
| 合计 | | | | | 108,162 |

独立算术证明对 `LINE_BYTES=1、2、8、12、16、32、64、128、256` 检查全部输入编码。每种配置比较描述符范围、32 位通道地址和 5 位短像素移位，共 38 位输出。此项检查仅针对提取的组合算术结构。

数值测试对 19 个公开输出逐周期比较，并检查数值期望结果。每组包含 37 个任务：

| `SIZE` | `BUS_WIDTH` | 窗口预取 | 比较周期数 |
| ---: | ---: | --- | ---: |
| 4 | 32 | 关闭 | 804,123 |
| 8 | 64 | 关闭 | 396,030 |
| 16 | 64 | 关闭 | 278,078 |
| 16 | 64 | 开启 | 269,013 |
| 合计 | | | 1,747,244 |

控制测试另外完成 23 项检查、16 个填充写入及 134 个逐周期输出比较，覆盖无效配置、无效描述符、运行期间等待配置以及恢复配置。所有检查通过。

## 重复运行

环境需要带 Slang 的 Pyosys 和支持项目 SystemVerilog 构造的 Verilator。以下命令从仓库根目录运行：

```sh
python3 test/conv_frontend/tools/run_state_equivalence.py \
  --reference-ref d9abf98 --out build/frontend_descriptor_check/formal
python3 test/conv_frontend/tools/descriptor_arithmetic_equivalence.py \
  --reference-ref d9abf98 --out build/frontend_descriptor_check/arithmetic
python3 test/conv_frontend/tools/compare_frontend.py \
  --reference-ref d9abf98 --verilator verilator-modern \
  --out build/frontend_descriptor_check/interface
python3 test/conv_frontend/tools/synthesis.py \
  --reference-ref d9abf98 --out build/frontend_descriptor_check/reference
python3 test/conv_frontend/tools/synthesis.py \
  --out build/frontend_descriptor_check/current
python3 test/conv_frontend/tools/measure_descriptor_paths.py \
  --mapped build/frontend_descriptor_check/reference/mapped.json \
  --pre-lut build/frontend_descriptor_check/reference/pre_lut.il \
  --out build/frontend_descriptor_check/reference/descriptor_paths.json
python3 test/conv_frontend/tools/measure_descriptor_paths.py \
  --mapped build/frontend_descriptor_check/current/mapped.json \
  --pre-lut build/frontend_descriptor_check/current/pre_lut.il \
  --out build/frontend_descriptor_check/current/descriptor_paths.json
```

汇总数据保存在 `docs/data/frontend_descriptor_selection_validation.json`，包含源码与工具摘要、各配置验证结果、资源数量、输入路径统计及最长路径的逐单元连接。
