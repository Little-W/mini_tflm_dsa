#!/usr/bin/env python3
"""Check declared-array widths against elaborated SystemVerilog $bits values."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import tempfile

from inspect_resources import dtype_shape, extent, walk


SOURCE = """
module resource_types;
  typedef logic [4:0] code_t;
  typedef enum logic [2:0] {STATE_A, STATE_B} state_t;
  typedef logic [1:0][3:0] pair_t;
  typedef struct packed {
    logic [31:0] address, index, epoch, retire, progress;
    logic index_valid, geometry, event_first;
  } demand_t;
  typedef struct packed {code_t code; state_t state; pair_t pair;} extra_t;
  typedef struct packed {demand_t request; extra_t extra;} packet_t;
  typedef union packed {logic [178:0] data; packet_t packet;} overlay_t;
  typedef demand_t demand_array_t [2:0];

  demand_t requests [4];
  state_t states [2];
  packet_t packets [2][3];
  overlay_t overlays [2];
  pair_t pairs [5];
  demand_array_t aliases;
  logic [$bits(requests)-1:0] bits_requests;
  logic [$bits(states)-1:0] bits_states;
  logic [$bits(packets)-1:0] bits_packets;
  logic [$bits(overlays)-1:0] bits_overlays;
  logic [$bits(pairs)-1:0] bits_pairs;
  logic [$bits(aliases)-1:0] bits_aliases;
endmodule
"""

EXPECTED = {
    "requests": {"dimensions": [4], "element_bits": 163},
    "states": {"dimensions": [2], "element_bits": 3},
    "packets": {"dimensions": [2, 3], "element_bits": 179},
    "overlays": {"dimensions": [2], "element_bits": 179},
    "pairs": {"dimensions": [5], "element_bits": 8},
    "aliases": {"dimensions": [3], "element_bits": 163},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="vector_resource_types_") as directory:
        root = Path(directory)
        source, tree = root / "resource_types.sv", root / "design.tree.json"
        source.write_text(SOURCE)
        subprocess.run([args.verilator, "--json-only", "--flatten",
                        "--json-only-output", str(tree), "--top-module", "resource_types",
                        str(source)], check=True, cwd=root, capture_output=True, text=True)
        nodes = list(walk(json.loads(tree.read_text())))
        types = {node["addr"]: node for node in nodes if "addr" in node}
        variables = {node["name"].removeprefix("resource_types."): node
                     for node in nodes if node.get("type") == "VAR"}
        for name, expected in EXPECTED.items():
            actual = dtype_shape(variables[name]["dtypep"], types)
            assert actual == expected, (name, actual, expected)
            oracle = types[variables["bits_" + name]["dtypep"]]
            assert oracle["type"] == "BASICDTYPE"
            assert math.prod(actual["dimensions"]) * actual["element_bits"] == extent(oracle["range"])
        print(json.dumps({"passed": True, "arrays": EXPECTED}, indent=2))


if __name__ == "__main__":
    main()
