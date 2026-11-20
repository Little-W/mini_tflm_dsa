# 输出FIFO的银行计数存储

对于不少于8个且数量为二的整数次幂的银行，`vec_s8_to_fifo_full` 使用单写、双异步读的 `regfile` 保存行数。计数在银行完成写入时保存，`bank_ready` 管理复位和释放后的有效性。普通输出和合并输出分别读取所需银行的计数，读取周期保持一致。其他银行数量使用独立寄存器保存计数。

数据FIFO的存储容量、读写端口、输出数据及掩码保持一致。普通输出、转置输出、合并输出和同周期写入／释放均保留原有行为。

## 综合结果

联合综合包含完整 `vec_s8_to_fifo` 和 `oa_writer`，参数为16列、32个银行、64位总线及29位写回计数。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT | 2,841 | 2,645 |
| RAM LUT | 52 | 60 |
| 名义LUT合计 | 2,893 | 2,705 |
| 触发器 | 1,066 | 911 |
| RAMB18E1 | 8 | 8 |
| 最长寄存器间组合路径 | 17级 | 15级 |

参考提交为 `cc0d4f69`，双方使用同一公共RTL、输出写回模块、工具和综合配置。

## 功能验证

形式验证覆盖8组配置，包含3、8、16、32、64个银行、32位／64位总线、循环／普通存储布局，以及FPGA／通用实现。8,156位公开输出、控制状态、各银行有效计数和数据存储端口全部通过归纳等价检查，外部输入与数据存储读数据不附加取值约束。

四组实际FPGA逐周期仿真合计完成324个场景和49,568个输出字节比较。数据、掩码、有效信号、行切换、请求与满状态全部一致。源文件和日志摘要见 `measurement.json`。

```sh
python test/fifo_count_storage/run_formal.py --out build/fifo_count_storage/formal
python test/fifo_count_storage/prepare_measurement.py --out build/fifo_count_storage/inputs
python scripts/fpga/open_fpga_synth.py \
  --case-config build/fifo_count_storage/inputs/cases.json \
  --cases reference current --out build/fifo_count_storage/synthesis
for banks in 16 32; do
  for bus in 32 64; do
    python test/writeback_cyclic/run.py --reference-rev cc0d4f69 \
      --banks "$banks" --bus-width "$bus" --fpga \
      --out "build/fifo_count_storage/numeric${banks}_${bus}"
  done
done
```
