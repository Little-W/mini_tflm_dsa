# 四通道选择加法

运行统一选择加法和四路 12 位模加的完整输入空间与四态验证：

```sh
python test/select_add_simd/run.py --out build/select_add_lanes
```

算术参考与覆盖范围分别位于 `test/select_add` 和 `test/ia_packed_add`。
