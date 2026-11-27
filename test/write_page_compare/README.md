# AXI 写入页内长度检查

`axi_write_page_guard` 将请求长度与当前页剩余字数分组比较。低三位、中间三位和高两位各自产生大小关系，最高地址组独立判断是否仍有至少 256 个字的余量。未按字节宽度排列的起始地址参与最低组边界条件。请求选择、分段写入、响应累计和队列状态保持原有周期行为。

综合实现使用普通组合比较。事件仿真在地址或长度含未知值时使用完整定宽表达式，使所有公开输出保持严格四态语义。

## 已执行的检查

- 23 组参数完成整个模块的状态及公开输出等价检查，覆盖 78,843 个比较位，输入未增加限制。
- 4 组地址及数据位宽配置完成 136,410 次严格四态输出比较。43、90、126、206 位输入分别逐位覆盖 0、1、X、Z，运行期实际端口宽度与声明宽度同时检查。
- 每组四态仿真包含页内请求与跨页请求，完成 3 个物理写地址、4 个数据拍、3 个物理响应和 2 个客户端响应，并实际经历背压。
- 32、64 位数据接口与 1、4 个在途请求组合完成 16 次协议测试，每次提供 256 个命令，覆盖随机背压和错误响应。

两侧使用相同的输入和输出寄存器进行独立映射：

| 数据位宽 | 参考 LUT | 当前 LUT | 触发器 | DSP | 参考最长路径 | 当前最长路径 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 32 | 175 | 173 | 242 | 0 | 9 | 9 |
| 64 | 174 | 168 | 314 | 0 | 9 | 8 |

路径长度包括寄存器数据和控制端口。该结果来自 Xilinx 7 系列结构映射，完整 SoC 和器件布局布线时序单独测量。源码散列和检查结果见 [validation.json](validation.json)。

## 重复运行

```sh
python test/write_page_address/run_formal.py \
  --reference-ref c9614d3f52d8cdb7baafeebffa26325d05d5a40d \
  --out build/write_page_compare/formal
python test/write_page_compare/run_four_state.py --out build/write_page_compare/four_state
python test/write_page_address/run_protocol.py --verilator verilator \
  --out build/write_page_compare/protocol
python scripts/fpga/open_fpga_synth.py \
  --case-config test/write_page_compare/cases.json --cases page32 page64 \
  --out build/write_page_compare/measure --max-register-path-cells 10
```
