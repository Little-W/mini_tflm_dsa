# Outstanding window DMA tests

This test instantiates the production `axi_block_dma_arbiter`, window descriptor
queue, image frontend, shared window cache, and AXI read engine. It uses a
32-bit AXI memory model and an independent NHWC window reference. Requests may
visit spatial positions in any order; responses retain request order and the
two-bit destination tag.

```sh
python3 test/window_dma/run.py --out build/window_dma --jobs 2
```

The test covers:

- Four accepted descriptors before their responses are consumed.
- A continuous resident-data stream with 128 descriptors, 512 response beats,
  2,048 useful elements, and one accepted response beat per cycle.
- Ordinary reads and window requests presented together, including an
  ordinary grant held for three cycles before its start signal.
- Arbitrary spatial and reduction coordinates, unaligned tensors, channel
  tails, padding, random AXI delays, and response backpressure.
- Read failures and invalid lengths `0`, `17`, `32`, and `33`; every accepted
  descriptor receives one terminal error response before reconfiguration.
- A configuration request held while four previous descriptors drain.
- Configuration requests held while the first read address is blocked and
  while the final response of one burst coincides with the next read address.
- Reset with four outstanding descriptors, followed by a new configuration
  and numerical checks on its responses.

Every useful returned lane is checked after signed input-offset correction.
The scoreboard also checks tags, response columns, masks, last markers, stable
responses under backpressure, AXI address bounds, and the 4 KiB burst boundary.
`summary.json` records the tested source hashes, executable hash, and completed
scenario summaries. Reset cancellations are counted separately from completed
descriptors.

The complementary `test/vector_engine` suite checks DW, Pool, vector, Add,
Softmax, quantization, output writes, and complete output memory contents.
