# WS 参数写入验证

`vec_requant` 按 DMA 字的通道索引选择参数 bank。同一 bank 的通道共用写数据选择，每个通道保留原始乘数、原始移位量、预处理乘数和预处理移位量，共 103 位。参数布局允许并行读取全部通道，也允许按串行批次读取指定通道。

```bash
python test/requant_parameter_write/run_formal.py --out build/requant_parameter_write
python -m unittest discover -s test/requant_parameter_write -p 'test_*.py'
```

形式检查比较实际 bank 存储与直接通道数组模型的全部内容。32、64、96、128 位总线和 1、2、3、16 个通道的组合覆盖二的幂次与一般参数配置。写数据、地址、DMA 字计数、写入阶段及响应资格均可自由变化；同地址重复写入按有效 DMA 字顺序处理。

容量分类单元测试检查 WS 参数 bank 和 IS 参数表的层次归属。完整 NPU 容量检查由 `scripts/capacity` 读取当前设计执行。
