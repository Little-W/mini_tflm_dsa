# Vector engine verification

`run.py` builds the production vector engine, DMA arbiter, window descriptor
queue, image frontend, shared cache, and AXI engines. Independent integer
references check DW, Pool, vector operations, Add, Softmax, and nearest-even
requantization. The memory scoreboard checks every byte, including bytes
outside the output tensor.

Run functional tests with both supported execution widths used by the design
documentation:

```sh
python3 test/vector_engine/run.py --pes 1 8 --jobs 2 --out build/vector_engine
```

Run the default eight-PE performance suite:

```sh
python3 test/vector_engine/run.py --pes 8 --perf --jobs 2 --out build/vector_performance
```

The functional suite applies random AXI delays and checks allocation bounds,
4 KiB boundaries, stable payloads under backpressure, error completion,
subsequent task execution, destination tags, and input-slot ownership. Both
PE configurations must accept multiple outstanding window requests. The
eight-PE configuration also checks simultaneous request and response activity.

## Strided-window study

```sh
python3 test/vector_engine/run.py --pes 8 --perf --window-study --jobs 2 \
  --out build/vector_window_study
```

This suite uses six aligned DW shapes. Its 32-bit memory service makes the
first read response available three cycles after an address handshake and returns successive
beats of a burst every two cycles, and leaves at least three cycles between the
last response of one burst and the first response of the next. Every reported
cache miss is classified when the demand request is accepted. Output checking
and input/output bounds are the same as in the functional suite.

## Error and resource checks

```sh
python3 test/vector_engine/run_window_error.py --jobs 2 --out build/vector_window_error
python3 test/vector_engine/inspect_resources.py --out build/vector_resources
```

The directed error test schedules a terminal window error while an output
write receives its grant. It checks the complete write and response drain,
idle completion, and the numerical output of the following task, with fixed
and random AXI waits and all four output byte offsets.

The resource check inspects elaborated multiplication operators and declared
arrays. `--reference /path/to/repository` additionally compares the vector data
array dimensions with another checkout. Test summaries record the source and
executable hashes used by each run.
