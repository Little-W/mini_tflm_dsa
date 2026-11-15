#!/usr/bin/env python3
"""Independent regression and integration checks for the capacity configuration.

The frozen numbers below come from the 2026-11-15 capacity study, whose selected
schedules were checked against complete RTL results.  The remaining checks
exercise budget invariants, failed-write behavior, and the actual Make entry
points.  No commercial simulator, NumPy, or third-party Python package is needed.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from capacity import config as capacity_config  # noqa: E402
from capacity import model  # noqa: E402

SOLVER = ROOT / "scripts/capacity/solve.py"
WORKLOADS = [
    {"M":128,"K":1024,"N":128}, {"M":256,"K":1024,"N":256},
    {"M":512,"K":1024,"N":512}, {"M":1024,"K":1024,"N":1024},
    {"M":2048,"K":1024,"N":2048}, {"M":128,"K":4096,"N":4096},
    {"M":4096,"K":4096,"N":128}, {"M":128,"K":16384,"N":128},
]
FROZEN = {
    32: ((4,3,37), 32734.25,
         [786432,3145728,11534336,46137344,180355072,95420416,95420416,12582912]),
    64: ((8,5,113), 65377.375,
         [393216,1572864,6291456,24117248,94371840,50331648,50331648,6291456]),
    128: ((12,8,305), 130892.625,
          [262144,1048576,3670016,14680064,56623104,28311552,28311552,4194304]),
    256: ((24,13,653), 261935.75,
          [262144,786432,2621440,9437184,37748736,22544384,22544384,4194304]),
}

# An intentionally unoptimized, legal starting configuration.  All CLI tests
# operate on temporary copies, never on the user's checked-in configuration.
CONFIG_TEXT = """# Keep this user comment when applying a new capacity.
PCR_ENGINE ?= 1
SIZE ?= 16
IA_CACHE_BLOCKS ?= 64
PS_FRAME_COUNT ?= 25
AXI_READ_OUTSTANDING ?= 4
PANEL_MAX_R ?= 10
PANEL_MAX_W ?= 10
PS_POOL_BYTES ?= 78080
PS_FORCE_RAW ?= 0
CAPACITY_BUDGET_BYTES ?= 131072
CAPACITY_BUDGET_SCOPE ?= logical-state
CAPACITY_REPRESENTATION ?= nominal3
"""


def json_from_stdout(text: str):
    """Make may echo the invoked command before the JSON document."""
    decoder = json.JSONDecoder()
    for offset, char in enumerate(text):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(text[offset:])
            except json.JSONDecodeError:
                continue
            return value
    raise AssertionError("No JSON object in stdout: " + text)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {b:model.solve(WORKLOADS, b*1024, "logical-state", "nominal3")
                       for b in FROZEN}

    def assert_legal(self, result, budget_bytes, scope, representation="nominal3"):
        a = result["allocation"]
        rmax, wmax, pages = a["panel_max_r"], a["panel_max_w"], a["ps_pool_pages"]
        self.assertTrue(1 <= rmax <= 32 and 1 <= wmax <= 32)
        self.assertTrue(4 <= pages <= 4095)
        self.assertEqual(a["ps_pool_bytes"], 256*pages)
        # Count the actual 16 lane RAMs, independently of the model's function.
        a_bytes = 16 * (128*rmax) * 1
        b_bytes = 16 * (32*wmax) * 4
        self.assertEqual(a["a_panel_bytes"], a_bytes)
        self.assertEqual(a["b_panel_bytes"], b_bytes)
        self.assertEqual(a["buffer_ram_bytes"], a_bytes+b_bytes+256*pages)
        self.assertLessEqual(a["budget_used_bytes"], budget_bytes)
        if scope == "logical-state":
            self.assertLessEqual(a["logical_state_bits"], budget_bytes*8)
        else:
            self.assertEqual(a["budget_used_bytes"], a["buffer_ram_bytes"])
            self.assertLessEqual(a["buffer_ram_bytes"], budget_bytes)
        for p in result["plans"]:
            r, w = p["R"], p["W"]
            self.assertTrue(1 <= r <= rmax and 1 <= w <= wmax)
            needed = 4*r*w if representation == "raw32" else max(r*w+3*r, 3*r*w+r)
            self.assertLessEqual(needed, pages)
            self.assertEqual(p["required_pool_pages"], needed)
            m, k, n = [p["padded_"+d] for d in ("M","K","N")]
            self.assertTrue(all(v % 16 == 0 for v in (m,k,n)))
            tr, tc = (n//16,m//16) if p["mode"] else (m//16,n//16)
            self.assertEqual((p["row_groups"]-1)*r+p["row_tail_tiles"], tr)
            self.assertEqual((p["column_groups"]-1)*w+p["column_tail_tiles"], tc)
            self.assertTrue(1 <= p["row_tail_tiles"] <= r)
            self.assertTrue(1 <= p["column_tail_tiles"] <= w)
            # Each logical operand is reloaded once for every opposite group.
            ia_rounds = math.ceil((n//16)/(r if p["mode"] else w))
            weight_rounds = math.ceil((m//16)/(w if p["mode"] else r))
            self.assertEqual(p["A_external_bytes"], m*k*ia_rounds)
            self.assertEqual(p["B_external_bytes"], k*n*weight_rounds)
            self.assertEqual(p["ideal_operand_read_bytes"], m*k*ia_rounds+k*n*weight_rounds)

    def test_frozen_rtl_study_solutions_and_reads(self):
        for b, (geometry, state, reads) in FROZEN.items():
            with self.subTest(budget_kib=b):
                result = self.results[b]
                a = result["allocation"]
                self.assertEqual((a["panel_max_r"],a["panel_max_w"],a["ps_pool_pages"]), geometry)
                self.assertEqual(a["logical_state_bytes"], state)
                self.assertEqual([p["ideal_operand_read_bytes"] for p in result["plans"]], reads)
                self.assert_legal(result,b*1024,"logical-state")

    def test_state_formula_matches_preserved_inventory(self):
        for (r,w,p), expected_bits in [((2,4,45),260998),((4,8,122),523258),
                                      ((10,10,305),1048101),((16,16,700),2096684)]:
            with self.subTest(r=r,w=w,p=p):
                self.assertEqual(model.state_bits(r,w,p),expected_bits)

    def test_page_boundaries_are_monotone_and_never_rounded_up(self):
        for pages in (4,31,32,63,64,127,128,255,256,511,512,1023,1024):
            with self.subTest(pages=pages):
                self.assertGreater(model.state_bits(8,8,pages+1),model.state_bits(8,8,pages))
                self.assertEqual(model.buffer_ram_bytes(8,8,pages+1)-model.buffer_ram_bytes(8,8,pages),256)
        for b,result in self.results.items():
            a=result["allocation"]
            self.assertGreater(model.state_bits(a["panel_max_r"],a["panel_max_w"],a["ps_pool_pages"]+1),b*1024*8)

    def test_ram_budget_counts_both_operand_panels(self):
        result=model.solve(WORKLOADS,32*1024,"buffer-ram","nominal3")
        self.assert_legal(result,32*1024,"buffer-ram")
        a=result["allocation"]
        self.assertLess(32*1024-a["buffer_ram_bytes"],256)
        self.assertGreater(a["logical_state_bytes"],a["buffer_ram_bytes"])

    def test_minimum_buffer_ram_budget_is_exact(self):
        # Sixteen 128-byte A lanes + sixteen 128-byte B lanes + four PS pages.
        minimum=16*128+16*128+4*256
        with self.assertRaises(ValueError):
            model.solve([{"M":16,"K":16,"N":16}],minimum-1,"buffer-ram")
        result=model.solve([{"M":16,"K":16,"N":16}],minimum,"buffer-ram")
        self.assert_legal(result,minimum,"buffer-ram")
        a=result["allocation"]
        self.assertEqual((a["panel_max_r"],a["panel_max_w"],a["ps_pool_pages"]),(1,1,4))

    def test_more_budget_cannot_increase_minimum_reads(self):
        # Use the measured multi-task objective rather than the size of R or W.
        products=[math.prod(p["ideal_operand_read_bytes"] for p in self.results[b]["plans"])
                  for b in sorted(self.results)]
        self.assertEqual(products,sorted(products,reverse=True))

    def test_padding_and_is_operand_identity(self):
        result=model.solve([{"M":17,"K":31,"N":513}],32*1024,"logical-state","nominal3")
        self.assert_legal(result,32*1024,"logical-state")
        p=result["plans"][0]
        self.assertEqual((p["padded_M"],p["padded_K"],p["padded_N"]),(32,32,528))
        self.assertTrue(p["requires_padding"])

    def test_raw32_is_separately_admitted(self):
        result=model.solve(WORKLOADS,64*1024,"logical-state","raw32")
        self.assert_legal(result,64*1024,"logical-state","raw32")

    def test_invalid_problem_inputs_are_rejected(self):
        cases=[([],32768,"logical-state","nominal3"),
               ([{"M":0,"K":16,"N":16}],32768,"logical-state","nominal3"),
               ([{"M":True,"K":16,"N":16}],32768,"logical-state","nominal3"),
               ([{"M":1<<20,"K":16,"N":16}],32768,"logical-state","nominal3"),
               (WORKLOADS,0,"logical-state","nominal3"),
               (WORKLOADS,1024,"logical-state","nominal3"),
               (WORKLOADS,1024,"buffer-ram","nominal3"),
               (WORKLOADS,32768,"unknown","nominal3"),
               (WORKLOADS,32768,"logical-state","unknown")]
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaises((ValueError,TypeError)):
                    model.solve(*args)


class _ConfigurationFixture(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix="gempact-capacity-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)
        self.config=self.directory/"npu.mk"
        self.config.write_text(CONFIG_TEXT)
        self.workloads=self.directory/"workloads.json"
        self.workloads.write_text(json.dumps(WORKLOADS))

    def invoke(self,*args,success=True):
        result=subprocess.run([sys.executable,str(SOLVER),"--config",str(self.config),*map(str,args)],
                              cwd=self.directory,text=True,capture_output=True,timeout=90)
        if success:
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        else:
            self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        return result

    def stamp(self):
        return self.config.read_bytes(),self.config.stat().st_mtime_ns


class FileAndCliTests(_ConfigurationFixture):
    def test_solve_is_read_only_without_apply(self):
        before=self.stamp()
        report=self.directory/"proposal.json"
        self.invoke("--max-state-kib",32,"--workloads",self.workloads,"--output",report)
        self.assertEqual(self.stamp(),before)
        result=json.loads(report.read_text())
        self.assertEqual(result["allocation"]["panel_max_r"],4)
        self.assertEqual(result["allocation"]["panel_max_w"],3)

    def test_apply_preserves_comments_and_repeat_does_not_touch(self):
        args=("--max-state-kib",32,"--workloads",self.workloads,"--apply")
        self.invoke(*args)
        values=capacity_config.read_config(self.config)
        self.assertEqual(values["PANEL_MAX_R"],4)
        self.assertEqual(values["PANEL_MAX_W"],3)
        self.assertEqual(values["PS_POOL_BYTES"],9472)
        self.assertEqual(values["CAPACITY_BUDGET_BYTES"],32768)
        self.assertIn("Keep this user comment",self.config.read_text())
        before=self.stamp()
        self.invoke(*args)
        self.assertEqual(self.stamp(),before)

    def test_invalid_inputs_never_modify_configuration(self):
        broken=self.directory/"broken.json";broken.write_text('{"M":')
        for args in [("--max-state-kib",1,"--apply"),
                     ("--max-ram-kib",1,"--apply"),
                     ("--budget-kib",-1,"--apply"),
                     ("--shape","0,16,16","--apply"),
                     ("--workloads",broken,"--apply"),
                     ("--max-ram-kib",32,"--max-state-kib",32,"--apply")]:
            with self.subTest(args=args):
                before=self.stamp()
                self.invoke(*args,success=False)
                self.assertEqual(self.stamp(),before)

    def test_effective_overrides_are_checked_without_rewriting(self):
        before=self.stamp()
        result=self.invoke("--show","--set","PANEL_MAX_R=12","--set","PANEL_MAX_W=8")
        data=json_from_stdout(result.stdout)
        self.assertEqual(data["configuration"]["PANEL_MAX_R"],12)
        self.assertEqual(data["configuration"]["PANEL_MAX_W"],8)
        self.invoke("--check","--set","PS_POOL_BYTES=262144",success=False)
        self.assertEqual(self.stamp(),before)

    def test_raw_representation_sets_hardware_mode(self):
        self.invoke("--max-state-kib",64,"--workloads",self.workloads,"--representation","raw32","--apply")
        values=capacity_config.read_config(self.config)
        self.assertEqual(values["PS_FORCE_RAW"],1)
        self.assertEqual(values["CAPACITY_REPRESENTATION"],"raw32")
        self.invoke("--check")
        self.invoke("--check","--set","PS_FORCE_RAW=0",success=False)

    def test_unsupported_array_size_is_rejected_for_capacity(self):
        self.invoke("--check","--set","SIZE=8",success=False)

    def test_c_header_uses_checked_configuration(self):
        header=self.directory/"npu_config.h"
        self.invoke("--emit-c-header",header)
        text=header.read_text()
        self.assertIn("NPU_CONFIG_PANEL_MAX_R",text)
        self.assertIn("NPU_CONFIG_PS_POOL_BYTES",text)
        self.assertIn("78080",text)


@unittest.skipUnless(shutil.which("make"),"GNU Make is required for build integration checks")
class MakeTests(_ConfigurationFixture):

    def make_environment(self):
        # These are independent Make invocations, even when the test suite was
        # launched through `make capacity-test`. Do not inherit its recursive
        # variable overrides or exported configuration instead of the fixture.
        excluded=set(capacity_config.DEFAULTS)|{"MAKEFLAGS","MFLAGS","MAKELEVEL",
                    "MAKEOVERRIDES","CONFIG","REPRESENTATION","SHAPE","SHAPES","WORKLOADS"}
        return {key:value for key,value in os.environ.items()
                if key not in excluded and not key.startswith(("NPU_","MMA_","CAPACITY_"))}

    def make(self,*args,subdirectory=None,success=True):
        target=ROOT/subdirectory if subdirectory else ROOT
        command=["make","--no-print-directory","-C",str(target),"NPU_CONFIG="+str(self.config),*map(str,args)]
        result=subprocess.run(command,cwd=self.directory,env=self.make_environment(),
                              text=True,capture_output=True,timeout=90)
        if success:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        else:self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        return result

    def test_custom_config_and_make_overrides_from_another_directory(self):
        result=self.make("capacity-show","PANEL_MAX_R=12","PANEL_MAX_W=8")
        data=json_from_stdout(result.stdout)
        self.assertEqual(data["configuration"]["PANEL_MAX_R"],12)
        self.assertEqual(data["configuration"]["PANEL_MAX_W"],8)
        self.assertEqual(data["configuration"]["PS_POOL_BYTES"],78080)
        self.make("capacity-check","PS_POOL_BYTES=262144",success=False)

    def test_parallel_solve_and_build_is_rejected_before_writing(self):
        before=self.stamp()
        self.make("-j2","capacity-solve","vcs-unit-build","UNIT=npu_top","MAX_STATE_KIB=32",success=False)
        self.assertEqual(self.stamp(),before)

    def test_unit_compiler_arguments_and_build_identity_follow_config(self):
        first=self.make("-n","vcs-unit-build","UNIT=npu_top").stdout
        second=self.make("-n","vcs-unit-build","UNIT=npu_top","PANEL_MAX_R=12","PANEL_MAX_W=8").stdout
        self.assertIn("GEMPACT_PANEL_MAX_R=10",first)
        self.assertIn("GEMPACT_PANEL_MAX_W=10",first)
        self.assertIn("GEMMORA_PS_POOL_BYTES=78080",first)
        self.assertIn("GEMPACT_PANEL_MAX_R=12",second)
        self.assertIn("GEMPACT_PANEL_MAX_W=8",second)
        # Existing unit Make directories include physical capacities, ensuring
        # a changed configuration cannot pick the old geometry's executable.
        self.assertIn("_r10_w10",first)
        self.assertIn("_r12_w8",second)

    def test_direct_uvm_submake_receives_same_config(self):
        text=self.make("-n","com",subdirectory="veri/sim").stdout
        self.assertIn("GEMPACT_PANEL_MAX_R=10",text)
        self.assertIn("GEMPACT_PANEL_MAX_W=10",text)
        self.assertIn("GEMMORA_PS_POOL_BYTES=78080",text)

    def test_verilator_backend_receives_explicit_hardware_dimensions(self):
        text=self.make("-n","pcr-backend").stdout
        args=shlex.split(text)
        for flag,value in (("--panel-rows","10"),("--panel-cols","10"),
                           ("--ps-pool-bytes","78080")):
            self.assertEqual(args[args.index(flag)+1],value)

    def test_submake_effective_size_and_config_alias(self):
        # Simulator/ASIC expose different historical names for SIZE. Their
        # validation must check the value actually instantiated by that entry.
        for subdirectory,override in (("veri/sim","MMA_SIZE=8"),
                                      ("asic/synthesis","NPU_SIZE=8")):
            with self.subTest(subdirectory=subdirectory):
                self.make("capacity-check",override,subdirectory=subdirectory,success=False)
        result=subprocess.run(["make","--no-print-directory","-C",str(ROOT),
                               "CONFIG="+str(self.config),"capacity-show"],
                              cwd=self.directory,env=self.make_environment(),
                              text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json_from_stdout(result.stdout)["configuration"]["PANEL_MAX_R"],10)

    def test_uvm_rebuilds_only_when_effective_build_configuration_changes(self):
        # A tiny compiler substitute records the actual compile arguments and
        # produces the requested output file. This checks Make's dependency
        # behavior without pretending that an RTL simulation has occurred.
        compiler=self.directory/"record-vcs"
        log=self.directory/"compile-arguments.jsonl"
        binary=self.directory/"simv"
        filelist=self.directory/"files.f";filelist.write_text("")
        compiler.write_text(f"#!{sys.executable}\n"+
            "import json, pathlib, sys\n"+
            f"with open({str(log)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"+
            "pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text('compiler test output\\n')\n")
        compiler.chmod(0o755)
        args=("com","SIMV="+str(binary),"VCS="+str(compiler),
              "FILELIST="+str(filelist),"OUT_DIR="+str(self.directory/"out"))
        self.make(*args,subdirectory="veri/sim")
        stamp=Path(str(binary)+".npu-config")
        original=(stamp.read_bytes(),stamp.stat().st_mtime_ns,binary.stat().st_mtime_ns)
        self.make(*args,subdirectory="veri/sim")
        self.assertEqual(len(log.read_text().splitlines()),1)
        self.assertEqual((stamp.read_bytes(),stamp.stat().st_mtime_ns,binary.stat().st_mtime_ns),original)
        self.make(*args,"PANEL_MAX_R=12","PANEL_MAX_W=8",subdirectory="veri/sim")
        calls=[json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(len(calls),2)
        self.assertIn("+define+GEMPACT_PANEL_MAX_R=12",calls[-1])
        self.assertIn("+define+GEMPACT_PANEL_MAX_W=8",calls[-1])
        self.assertIn(b"PANEL_MAX_R=12",stamp.read_bytes())
        self.make(*args,"PANEL_MAX_R=12","PANEL_MAX_W=8",subdirectory="veri/sim")
        self.assertEqual(len(log.read_text().splitlines()),2)
        # Restore the file's capacities with a raw PS representation. Even
        # with a caller-specified SIMV name, a new mode must trigger rebuild.
        self.make(*args,"PS_FORCE_RAW=1","CAPACITY_REPRESENTATION=raw32",subdirectory="veri/sim")
        calls=[json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(len(calls),3)
        self.assertTrue(any("GEMMORA_PS_FORCE_RAW" in arg for arg in calls[-1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
