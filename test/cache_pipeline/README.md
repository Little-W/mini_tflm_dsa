# Shared-cache request pipeline

`conv_windowed_cache` accepts ordered word requests through its existing
`req_valid`/`req_ready` interface. With `cfg_windowed=1`, `DEMAND_DEPTH` limits the
total number of accepted requests whose responses have not been consumed. The
default is four. Request metadata and completed responses have separate queues;
the shared credit count covers both queues and the active cache lookup.

An empty request queue directly feeds the cache lookup. An empty response queue
directly exposes the synchronous RAM result. A resident word therefore has one
cycle of latency, and a ready consumer can receive one word per cycle. When the
consumer pauses, completed data and the error bit are stored together. Responses
always follow request acceptance order.

The request queue stores 163 bits per entry and the response queue stores 33 bits
per entry. Four entries in each queue require 784 bits, or 98 bytes, of register
content, in addition to pointers and counters. The data RAM retains its original
capacity and one synchronous read port. Geometry mode (`cfg_windowed=0`) admits
one request at a time so that the geometry hint belongs to its active request.

`cfg_ready` requires all accepted requests, queued responses, fills, and queued
prefetches to finish. Holding `cfg_valid` prevents new requests while existing
work drains. A reset clears the queues and cancels accepted requests. Each
accepted request otherwise produces exactly one response, including requests
that fail range checks or encounter an AXI read error.

## Counters

- `stat_hits` and `stat_misses` inspect residency when the external request is
  accepted. An accepted cold request remains a miss even if a preceding fill
  makes it resident before its queued lookup starts.
- Internal `stat_lookup_hits` and `stat_lookup_misses` inspect residency when a
  request enters the lookup stage.
- Internal `stat_peak_outstanding` records the maximum number of accepted,
  unconsumed requests in the current configuration.

Requests outside the configured allocation produce errors and do not contribute
to the hit or miss counts. The counters reset when a new configuration is
accepted.

## Verification

Run the actual RTL tests with Verilator:

```sh
python3 test/cache_pipeline/run.py --verilator /path/to/verilator --jobs 2
```

The default profiles use depth four with one and two cache ways, plus depth one
with two ways. Each profile checks twelve scenarios: cold request queuing,
continuous resident reads, response backpressure, conflicting cache lines,
ordered range errors, demand-fill error recovery, acceptance during a pending
prefetch, prefetch-error recovery, configuration draining, reset with pending
work, clipped bypass reads, and geometry-hint ordering.

The throughput test cycles through sixteen consecutive resident word addresses
for sixty-four requests. It checks every accepted and returned cycle, every data
byte, and the absence of external reads. The backpressure tests check stable
response data and error bits. Independent request accounting checks the shared
credit count against queued requests, the active lookup, and queued responses.
The AXI memory model varies request and response timing and verifies allocation
bounds and the 4 KiB transaction boundary.

Results include each scenario, observed peak outstanding count, hit-stream
intervals, source hashes, and executable hashes in
`build/cache_pipeline/summary.json`.
