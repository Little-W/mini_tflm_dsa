// SPDX-License-Identifier: Apache-2.0
#include "Vdma_abort_top.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <deque>
#include <stdexcept>

#ifndef TEST_BUS_WIDTH
#define TEST_BUS_WIDTH 32
#endif
#ifndef TEST_PREPARE_ABORT
#define TEST_PREPARE_ABORT 0
#endif
constexpr uint32_t ByteMask = (1u << (TEST_BUS_WIDTH/8))-1u;

static void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}

struct Simulation {
  VerilatedContext context;
  Vdma_abort_top dut{&context};
  bool read_pending=false, response_pending=false, read_release=false;
  bool write_release=false, response_release=true, fault_latched=false;
  bool external_abort=false, stalled=false;
  bool observed_grant=false;
  unsigned write_left=0, accepted=0, written=0, completed=0, errors=0, addresses=0;
  unsigned raw_completed=0, error_completions=0;
  unsigned read_addresses=0, read_completions=0;
  struct WriteBeat {uint64_t data; uint32_t mask; bool last;};
  std::deque<WriteBeat> buffered_beats;
  bool source_handshake=false;
  uint64_t held_data=0;
  uint32_t held_mask=0, held_last=0;
  void step() {
    dut.clk=0;
    dut.i_abort=external_abort || fault_latched;
    dut.arready=1; dut.awready=write_left==0 && !response_pending;
    dut.rvalid=read_release && read_pending;
    dut.wready=write_release && write_left!=0;
    dut.bvalid=response_release && response_pending;
    dut.source_data=(TEST_BUS_WIDTH==64 ? UINT64_C(0xc0d1e2f391827364) : UINT64_C(0x91827364)) + accepted;
    dut.eval();
    source_handshake=dut.source_valid && dut.source_ready;
    observed_grant=dut.write_granted;
    if (stalled) require(dut.wvalid && dut.wdata==held_data && dut.wstrb==held_mask &&
                         dut.wlast==held_last, "W response changed while stalled");
    stalled=dut.wvalid && !dut.wready;
    held_data=dut.wdata; held_mask=dut.wstrb; held_last=dut.wlast;
    if (dut.rst_n) {
      if (dut.bus_error) {fault_latched=true; ++errors;}
      if (dut.write_done) ++completed;
      if (dut.write_done_raw) ++raw_completed;
      if (dut.write_error_raw) ++error_completions;
      if (source_handshake) ++accepted;
      if (dut.buffer_valid && dut.buffer_ready)
        buffered_beats.push_back({dut.buffer_data,dut.buffer_mask,bool(dut.buffer_last)});
      if (dut.rvalid && dut.rready) {read_pending=false;++read_completions;}
      if (dut.bvalid && dut.bready) response_pending=false;
      if (dut.wvalid && dut.wready) {
        require(write_left>0, "W beat has no accepted AW");
        require(bool(dut.wlast)==(write_left==1), "W last differs from AW length");
        if (!fault_latched && !external_abort)
          require(dut.wstrb==ByteMask, "live transfer lost byte enables");
        require(!buffered_beats.empty(), "W beat has no buffered predecessor");
        const WriteBeat expected=buffered_beats.front();buffered_beats.pop_front();
        require(dut.wdata==expected.data && dut.wstrb==expected.mask &&
                bool(dut.wlast)==expected.last, "W beat differs from buffered order");
        ++written;
        if (--write_left==0) response_pending=true;
      }
      if (dut.arvalid && dut.arready) {require(dut.arlen==0,"unexpected read length");read_pending=true;++read_addresses;}
      if (dut.awvalid && dut.awready) {require(dut.awlen==3,"unexpected write length");write_left=4;++addresses;}
    }
    dut.clk=1;dut.eval();context.timeInc(1);
  }
  void reset() {
    dut.rst_n=0; dut.read_req=0; dut.read_start=0; dut.write_req=0; dut.write_start=0;
    dut.source_valid=0;dut.rresp=0;dut.bresp=0;
    for (unsigned cycle=0;cycle<3;++cycle)step();
    dut.rst_n=1;step();
  }
  void read() {
    dut.read_req=1;
    for (unsigned cycle=0;cycle<200 && !dut.read_granted;++cycle)step();
    require(dut.read_granted,"read grant timeout");dut.read_start=1;step();
    dut.read_req=0;dut.read_start=0;step();
  }
  void write() {
    dut.write_req=1;
    for (unsigned cycle=0;cycle<200 && !dut.write_granted;++cycle)step();
    require(dut.write_granted,"write grant timeout");dut.write_start=1;step();
    dut.write_req=0;dut.write_start=0;dut.source_valid=1;
    for (unsigned cycle=0;cycle<200 && !dut.wvalid;++cycle)step();
    require(dut.wvalid,"write data timeout");
  }
  void drain() {
    write_release=true;response_release=true;read_release=true;
    unsigned quiet_cycles=0;
    for (unsigned cycle=0;cycle<500;++cycle) {
      step();
      quiet_cycles=(dut.idle && !dut.bus_error && !read_pending && !write_left &&
                    !response_pending) ? quiet_cycles+1 : 0;
      if (quiet_cycles==3) {
        require(buffered_beats.empty(), "DMA retained a buffered write after draining");
        return;
      }
    }
    throw std::runtime_error("DMA drain timeout");
  }
};

int main(int argc, char** argv) {
  Verilated::commandArgs(argc,argv);
  try {
    unsigned cases=0;
    for (unsigned owner=0;owner<2;++owner) {
      for (unsigned mode=0;mode<8;++mode) {
        Simulation s;s.dut.owner_dw=owner;s.reset();s.read();
        if (mode==5) {
          s.dut.write_req=1;
          for (unsigned cycle=0;cycle<200 && !s.dut.write_granted;++cycle)s.step();
          require(s.dut.write_granted,"pending write grant timeout");
          while (!s.read_pending)s.step();
          s.dut.rresp=2;s.read_release=true;s.dut.write_start=1;s.step();
          require(!s.observed_grant && s.addresses==0,"read error accepted a new write command");
          s.dut.write_req=0;s.dut.write_start=0;
        } else s.write();
        const unsigned accepted_before_fault=s.accepted;
        if (mode==1) {s.dut.rresp=2;s.read_release=true;s.write_release=true;s.step();
          require(s.source_handshake && s.accepted==accepted_before_fault+1 && s.written==1,
                  "same-cycle R error and W transfer lost source handshake");}
        else if (mode==2) {s.dut.rresp=2;s.read_release=true;s.step();}
        else if (mode==3) {s.external_abort=true;s.read_release=true;s.step();}
        else if (mode==4 || mode==6 || mode==7) {
          s.write_release=true;s.response_release=false;
          while (s.written<4)s.step();
          s.dut.rresp=mode==7 ? 0 : 2;
          s.dut.bresp=mode==7 ? 2 : 0;
          s.read_release=true;s.response_release=mode!=4;s.step();
        }
        const unsigned accepted_at_fault=s.accepted;
        s.drain();
        require(s.addresses==(mode==5?0u:1u) && s.written==(mode==5?0u:4u),
                "accepted write transaction did not drain");
        require(s.completed==(mode==0?1u:0u),"incorrect successful completion after error or abort");
        require(s.raw_completed==(mode==0?1u:0u) && s.error_completions==0,
                "aborted owner published a completion");
        if (mode==1 || mode==2)
          require(s.accepted==accepted_at_fault,"source data accepted after read error");
        if (mode==3)
          require(s.accepted==accepted_before_fault,"source data accepted after external abort");
        if (mode==0 || mode==4 || mode==6 || mode==7) require(s.accepted==4,"normal source beat count differs");
        s.dut.source_valid=0;s.external_abort=false;s.fault_latched=false;
        s.dut.rresp=0;s.dut.bresp=0;s.read_release=false;
        for(unsigned cycle=0;cycle<4;++cycle)s.step();
        unsigned prior_done=s.completed;
        s.write_release=false;s.write();s.drain();
        require(s.completed==prior_done+1,"write recovery failed without reset");
        std::printf("DMA_ABORT_CASE owner=%u mode=%u initial_source_beats=%u recovery=1\n",
                    owner,mode,s.accepted-4);++cases;
      }
      if (TEST_PREPARE_ABORT) {
        // 已接收的读取命令在准备期间收到中止后继续完成总线排空。
        for (unsigned preparation_cycle=0;preparation_cycle<2;++preparation_cycle) {
          Simulation s;s.dut.owner_dw=owner;s.reset();s.read();
          for(unsigned cycle=0;cycle<preparation_cycle;++cycle)s.step();
          require(!s.read_pending && s.read_addresses==0,"read preparation coverage is missing");
          s.external_abort=true;s.read_release=true;s.drain();
          require(s.read_addresses==1 && s.read_completions==1,
                  "accepted read did not drain after preparation abort");
          require(s.addresses==0 && s.accepted==0,"preparation abort issued a write");
          s.external_abort=false;s.read_release=false;
          for(unsigned cycle=0;cycle<4;++cycle)s.step();
          s.write_release=false;s.write();s.drain();
          require(s.completed==1 && s.accepted==4,"preparation abort recovery failed");
          std::printf("DMA_ABORT_PREPARE owner=%u preparation_cycle=%u recovery=1\n",owner,preparation_cycle);
          ++cases;
        }
        for (unsigned preparation_cycle=0;preparation_cycle<2;++preparation_cycle) {
          Simulation s;s.dut.owner_dw=owner;s.reset();s.read();
          for(unsigned cycle=0;cycle<preparation_cycle;++cycle)s.step();
          require(!s.read_pending && s.read_addresses==0,"read reset preparation coverage is missing");
          s.reset();
          for(unsigned cycle=0;cycle<4;++cycle)s.step();
          require(s.dut.idle && s.read_addresses==0,"reset retained a prepared read");
          s.read();s.drain();
          require(s.read_addresses==1 && s.read_completions==1,"read recovery after preparation reset failed");
          s.write_release=false;s.write();s.drain();
          require(s.completed==1 && s.accepted==4,"write recovery after preparation reset failed");
          std::printf("DMA_RESET_PREPARE owner=%u preparation_cycle=%u recovery=1\n",owner,preparation_cycle);
          ++cases;
        }
      }
    }
    std::printf("DMA_ABORT_BOUNDARY_PASS cases=%u\n",cases);return 0;
  } catch(const std::exception& error) {
    std::fprintf(stderr,"DMA_ABORT_BOUNDARY_FAIL %s\n",error.what());return 1;
  }
}
