# 控制状态与位宽验证

该测试比较 `oa_writer` 和 `ps_frame_store` 的全部公开输出及共同状态。测试使用模块完整 RTL，不限制输入数值，并检查逐周期等价关系。

## 配置

| 模块 | 配置 |
| --- | --- |
| `oa_writer` | `VLEN/BUS_WIDTH/COUNT_WIDTH` 为 `4/32/8`、`16/32/29`、`16/64/29`、`32/128/32` |
| `ps_frame_store` | 内部存储 47 行/16 帧；外部固定通道 512 行/16 帧/7×8192 字节；外部轮换通道 16 行/4 帧/7×2048 字节 |

写回模块只保留有读取用途的状态。部分和存储对银行数、行数和地址步长进行显式位宽转换，并按有效输入控制存储写入。

## 执行

```bash
python3 test/rtl_state_cleanup/run.py \
  --source-root . --reference ef0dc75342997721bdc4110b2841445df962018e \
  --out build/rtl_state_cleanup
```

可以用 `--cases` 选择表中对应的测试名称，用 `--reference-root` 指定独立的参考源码目录。`validation.json` 保存各配置的源码 SHA256、证明点数量和结果。

帧地址准备的流水线、算术和中止行为由 `test/frame_address` 的独立数值测试与符号部分积证明检查。
