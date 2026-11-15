#!/usr/bin/env python3
"""Cross-check the C host planner and the actual RTL input generator.

The C helper is compiled once, then compared with the Python planner over the
four preserved capacity-study geometries. Generator tests verify the schedule
register words, reconstruct full INT32 golden values from input bytes, and
preserve legacy output byte for byte. No RTL simulation is run here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from capacity import model  # noqa: E402

COMPILER = shutil.which("cc") or shutil.which("gcc")
GEOMETRIES = [(4,3,37),(8,5,113),(12,8,305),(24,13,653)]
SHAPES = [(128,1024,128),(256,1024,256),(512,1024,512),
          (1024,1024,1024),(2048,1024,2048),(128,4096,4096),
          (4096,4096,128),(128,16384,128)]

C_RUNNER = r"""
#include <inttypes.h>
#include <stdio.h>
#include "gempact_tiling.h"
int main(void) {
    unsigned m,n,r,w,p,req_r,req_w,mode,raw;
    while (scanf("%u %u %u %u %u %u %u %u %u",
                 &m,&n,&r,&w,&p,&req_r,&req_w,&mode,&raw)==9) {
        gempact_tiling_t t={0}; uint64_t payload=0;
        int ok=gempact_plan_panel(m,n,r,w,p,req_r,req_w,mode,raw,&t,&payload);
        printf("%d %u %u %u %u %u %u %" PRIu64 "\n",ok,t.ia_reuse,t.w_reuse,
               t.row_groups,t.row_tail_tiles,t.col_groups,t.col_tail_tiles,payload);
    }
    return 0;
}
"""

DRIVER_RUNNER = r"""
#include <stdio.h>
#include "dsa_accel.h"
int main(void) {
    unsigned m,k,n,mode;
    while (scanf("%u %u %u %u",&m,&k,&n,&mode)==4) {
        uint32_t r=0,w=0;
        dsa_matmul_select_reuse(m,k,n,64,(dsa_dataflow_mode_t)mode,&r,&w);
        printf("%u %u\n",r,w);
    }
    return 0;
}
"""


@unittest.skipUnless(COMPILER,"A C99 compiler is required for the C/Python cross-check")
class HostPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory(prefix="gempact-host-planner-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory=Path(cls.temporary.name)
        source=directory/"planner.c";source.write_text(C_RUNNER)
        cls.executable=directory/"planner"
        subprocess.run([COMPILER,"-std=c99","-O2","-Wall","-Wextra","-Werror",
                        "-I",str(ROOT/"drivers"),str(source),"-o",str(cls.executable)],
                       check=True,text=True,capture_output=True)

    def run_c(self,cases):
        text="".join(" ".join(map(str,c))+"\n" for c in cases)
        run=subprocess.run([str(self.executable)],input=text,text=True,capture_output=True,
                           check=True,timeout=20)
        results=[list(map(int,line.split())) for line in run.stdout.splitlines()]
        self.assertEqual(len(results),len(cases))
        return results

    def test_fixed_dataflow_agrees_across_study_shapes_and_policies(self):
        cases=[];expected=[]
        for r,w,pages in GEOMETRIES:
            for m,k,n in SHAPES:
                for mode in (0,1):
                    for raw in (0,1):
                        cases.append((m,n,r,w,pages*256,0,0,mode,raw))
                        expected.append(model.plan_for_hardware(m,k,n,r,w,pages,
                            "raw32" if raw else "nominal3",mode=mode))
        # Include non-square tails and explicit request limits. A request may
        # exceed a physical limit, but must never enlarge the selected group.
        for r,w,pages in GEOMETRIES:
            for req_r,req_w in ((1,0),(0,2),(3,5),(32,32)):
                mode=(req_r+req_w)%2
                cases.append((80,112,r,w,pages*256,req_r,req_w,mode,0))
                expected.append(model.plan_for_hardware(80,64,112,r,w,pages,
                    mode=mode,requested_r=req_r,requested_w=req_w))
        for case,actual,p in zip(cases,self.run_c(cases),expected):
            with self.subTest(case=case):
                self.assertEqual(actual,[1,p["R"],p["W"],p["row_groups"],
                    p["row_tail_tiles"],p["column_groups"],p["column_tail_tiles"],
                    p["required_pool_pages"]*256])

    def test_requested_group_shrinks_to_fit_the_pool(self):
        case=(512,512,4,3,37*256,4,3,0,0)
        actual=self.run_c([case])[0]
        self.assertEqual(actual[0:3],[1,3,3])
        p=model.plan_for_hardware(512,1024,512,4,3,37,
                                 mode=0,requested_r=4,requested_w=3)
        self.assertEqual((p["R"],p["W"]),(3,3))

    def test_c_rejects_unrepresentable_hardware_and_shapes(self):
        cases=[(0,16,1,1,1024,0,0,0,0),(17,16,1,1,1024,0,0,0,0),
               (1<<20,16,1,1,1024,0,0,0,0),(16,16,0,1,1024,0,0,0,0),
               (16,16,33,1,1024,0,0,0,0),(16,16,1,1,1023,0,0,0,0),
               (16,16,1,1,1025,0,0,0,0),(16,16,1,1,4096*256,0,0,0,0)]
        for case,result in zip(cases,self.run_c(cases)):
            with self.subTest(case=case):
                self.assertEqual(result[0],0)

    def test_root_and_nmsis_driver_compile_and_use_configured_pcr_planner(self):
        directory=Path(self.temporary.name)
        source=directory/"driver_runner.c";source.write_text(DRIVER_RUNNER)
        variants=[("root",ROOT/"drivers/dsa_accel.c",ROOT/"drivers"),
                  ("nmsis",ROOT/"drivers/tflm/NMSIS/NN/Source/ExtraAccFunctions/dsa_accel.c",
                   ROOT/"drivers/tflm/NMSIS/NN/Include")]
        cases=[(80,64,112,0),(80,64,112,1),(512,1024,512,0),
               (128,4096,4096,0),(128,4096,4096,1)]
        for variant,driver,includes in variants:
            for raw in (0,1):
                with self.subTest(driver=variant,raw=raw):
                    executable=directory/f"driver_{variant}_{raw}"
                    run=subprocess.run([COMPILER,"-std=c99","-O2","-I",str(includes),
                        "-I",str(ROOT/"drivers"),"-DDSA_PCR_ENGINE=1","-DDSA_TILE_SIZE=16",
                        "-DDSA_IA_CACHE_BLOCKS=64","-DDSA_PS_FRAME_COUNT=25",
                        "-DDSA_PANEL_MAX_R=8","-DDSA_PANEL_MAX_W=5","-DDSA_PS_POOL_BYTES=28928",
                        f"-DDSA_PS_FORCE_RAW={raw}",str(source),str(driver),"-o",str(executable)],
                        text=True,capture_output=True,timeout=30)
                    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                    run=subprocess.run([str(executable)],
                        input="".join(" ".join(map(str,case))+"\n" for case in cases),
                        text=True,capture_output=True,check=True,timeout=10)
                    actual=[tuple(map(int,line.split())) for line in run.stdout.splitlines()]
                    expected=[]
                    for m,k,n,mode in cases:
                        p=model.plan_for_hardware(m,k,n,8,5,113,
                                                 "raw32" if raw else "nominal3",mode=mode)
                        expected.append((p["R"],p["W"]))
                    self.assertEqual(actual,expected)


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix="gempact-generator-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)

    def generate(self,*args,name="case",success=True):
        out=self.directory/name
        run=subprocess.run([sys.executable,str(ROOT/"veri/top_regression/gen_mem.py"),
                            "--out_dir",str(out),*map(str,args)],
                           cwd=self.directory,text=True,capture_output=True,timeout=30)
        if success:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        else:self.assertNotEqual(run.returncode,0,run.stdout+run.stderr)
        return out

    @staticmethod
    def words(path):
        return [int(s,16) for s in path.read_text().split()]

    def test_pcr_generator_encodes_groups_and_complete_accumulators(self):
        # The public generator names are K=rows, N=reduction, M=columns.
        # 80x112 output exceeds both physical panel dimensions and has tails.
        for mode,raw in ((0,False),(1,True)):
            with self.subTest(mode=mode,raw=raw):
                args=["--pcr-engine","--size",16,"--ia_cache_blocks",64,
                      "--ps_frame_count",25,"--panel-max-r",4,"--panel-max-w",3,
                      "--ps_pool_bytes",9472,"--K",80,"--N",64,"--M",112,
                      "--mem_words",16384,"--dataflow_mode",mode]
                if raw:args.append("--ps-force-raw")
                out=self.generate(*args,name=f"mode{mode}")
                cfg=self.words(out/"config.mem")
                p=model.plan_for_hardware(80,64,112,4,3,37,
                                         "raw32" if raw else "nominal3",mode=mode)
                self.assertEqual(cfg[3:9],[80,64,112,p["R"],p["W"],mode])
                self.assertEqual(cfg[30],p["row_groups"]|(p["column_groups"]<<16))
                self.assertEqual(cfg[31],p["row_tail_tiles"]|(p["column_tail_tiles"]<<16))
                self.assertEqual(cfg[12:14],[0,0])
                self.assertEqual(cfg[16],0)  # the PCR profile does not load bias
                case=json.loads((out/"config.json").read_text())
                self.assertEqual(case["pcr_tiling"]["R"],p["R"])
                image=b"".join(v.to_bytes(4,"little") for v in self.words(out/"init.mem"))
                signed=lambda x:x-256 if x>127 else x
                lhs=[[signed(image[cfg[14]+i*cfg[18]+k]) for k in range(64)] for i in range(80)]
                rhs=[[signed(image[cfg[15]+j*cfg[19]+k]) for k in range(64)] for j in range(112)]
                expected=[sum(a*b for a,b in zip(row,col))&0xffffffff
                          for row in lhs for col in rhs]
                self.assertEqual(self.words(out/"acc.mem"),expected)

    def test_legacy_generator_outputs_remain_byte_identical(self):
        # Frozen from e8a73373009064026fd0be1cbf3af6870d592ebb, using exactly
        # --seed 1 --mem_words 4096 and no PCR flags. No runtime Git needed.
        expected={
            "init.mem":"eda6cb2f65d64badc75ca11ad6359fc1490bc2fdd6d0e50f741cdbe88db23fda",
            "golden.mem":"78a181362c6211d71d39338cb79dcbf52bc8e219d6f97ba24a9b906ae8ba52d0",
            "config.mem":"d19656f73e36352bd6a8fc3311ec9427cfcd46ab4add592db8f35757f6425dcc",
            "test_params.svh":"b4f7124fe48f96c50ff8feb22106d716506a72ee37fcc6cd13110b68dc565bd9",
        }
        out=self.generate("--seed",1,"--mem_words",4096)
        for filename,digest in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256((out/filename).read_bytes()).hexdigest(),digest)
        self.assertFalse((out/"acc.mem").exists())

    def test_pcr_generator_rejects_unsupported_profiles(self):
        base=["--pcr-engine","--size",16,"--ps_pool_bytes",9472]
        for i,extra in enumerate((["--K",17],["--lhs_dtype",2],["--lhs_zp",1],
                                  ["--per_channel"],["--ps_pool_bytes",1025])):
            with self.subTest(extra=extra):
                out=self.generate(*base,*extra,name=f"bad{i}",success=False)
                self.assertFalse((out/"config.mem").exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
