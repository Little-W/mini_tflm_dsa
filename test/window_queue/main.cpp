// SPDX-License-Identifier: Apache-2.0
// 使用独立事务队列检查描述符、返回标签、停顿保持和错误后的排空。
#include "Vconv_window_queue.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <deque>
#include <random>
#include <stdexcept>
#include <string>

#ifndef TEST_DEPTH
#define TEST_DEPTH 4
#endif
#ifndef TEST_LANES
#define TEST_LANES 16
#endif

struct Request { uint32_t p, q, cols, tag; };

static void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

static uint16_t value(const Request& request, unsigned beat, unsigned lane) {
    return uint16_t(request.p * 17u + request.q * 5u + beat * 31u + lane);
}

static void run(bool random_wait) {
    Vconv_window_queue top;
    std::mt19937 rng(0x3217u + TEST_DEPTH + 13u * random_wait);
    std::deque<Request> expected;
    unsigned accepted=0, retired=0, launches=0, errors=0;
    unsigned beat=0, beats=1, latency=0, previous_launch=0, consecutive=0;
    bool active=false, failed=false;
    top.rst_n=0;
    top.enable=1;
    top.configure=0;
    top.req_valid=0;
    top.rsp_ready=0;
    top.frontend_ready=0;
    top.frontend_rsp_valid=0;
    top.frontend_error=0;
    for (unsigned tick=0;tick<4;tick++) {
        top.clk=0;top.eval();top.clk=1;top.eval();
    }
    top.rst_n=1;
    const unsigned count=random_wait ? 4000u : 256u;
    for (unsigned cycle=0;cycle<200000;cycle++) {
        top.clk=0;
        const bool configure=failed && expected.empty();
        const bool fault=random_wait && !failed && active && errors<8 && rng()%257u==0u;
        top.configure=configure;
        top.frontend_error=fault;
        top.req_valid=accepted<count && !failed && !fault && (!random_wait || rng()%4u!=0u);
        const Request offered{accepted*19u+1u,accepted*3u,1u+accepted%21u,accepted%4u};
        top.req_p0=offered.p;top.req_q0=offered.q;top.req_cols=offered.cols;top.req_tag=offered.tag;
        top.rsp_ready=(!random_wait || rng()%4u!=0u) && cycle>=16;
        top.frontend_rsp_valid=active && latency==0 && !failed;
        top.frontend_rsp_last=beat+1u==beats;
        top.frontend_rsp_col=beat%16u;
        top.frontend_rsp_mask=(1u<<TEST_LANES)-1u;
        for (unsigned lane=0;lane<TEST_LANES;lane++)
            top.frontend_rsp_data[lane]=active ? value(expected.front(),beat,lane) : 0;
        top.frontend_ready=cycle>=16 && (!active ||
            (top.frontend_rsp_valid && top.frontend_rsp_last && top.rsp_ready));
        top.eval();
        const bool accept=top.req_valid && top.req_ready;
        const bool response=top.rsp_valid && top.rsp_ready;
        const bool retire=response && top.rsp_last;
        const bool launch=top.frontend_valid && top.frontend_ready;
        if (top.frontend_valid) {
            const unsigned index=active ? 1u : 0u;
            require(expected.size()>index,"descriptor selected an absent request");
            const Request& request=expected[index];
            require(top.frontend_p0==request.p && top.frontend_q0==request.q &&
                    top.frontend_cols==request.cols,"descriptor order or payload differs");
            require(bool(top.frontend_cols_valid)==(request.cols<=16u),"column validation differs");
        }
        if (top.rsp_valid) {
            require(!expected.empty(),"response has no accepted request");
            require(top.rsp_tag==expected.front().tag,"response tag differs");
            require(bool(top.rsp_error)==(failed || fault),"response error differs");
            if (top.rsp_error) require(top.rsp_last && top.rsp_mask==0,"error response did not terminate");
            else {
                require(active && top.frontend_rsp_valid,"response precedes frontend data");
                require(top.rsp_col==beat%16u,"response column differs");
                require(top.rsp_mask==((1u<<TEST_LANES)-1u),"response mask differs");
                for (unsigned lane=0;lane<TEST_LANES;lane++)
                    require(top.rsp_data[lane]==value(expected.front(),beat,lane),"response data differs");
            }
        }
        top.clk=1;top.eval();
        if (latency) latency--;
        if (response && !retire) beat++;
        if (retire) { expected.pop_front();retired++;active=false; }
        if (accept) { expected.push_back(offered);accepted++; }
        if (launch) {
            require(!failed && !fault && !expected.empty(),"invalid frontend launch");
            active=true;beat=0;beats=random_wait ? 1u+rng()%5u : 1u;
            latency=random_wait ? rng()%4u : 0u;
            if (launches && cycle==previous_launch+1u) consecutive++;
            previous_launch=cycle;launches++;
        }
        if (fault) { failed=true;active=false;errors++; }
        if (configure) { failed=false;active=false; }
        if (accepted==count && expected.empty() && !active && !top.busy) {
            require(retired==accepted,"request count differs after drain");
            if (!random_wait)
                require(consecutive>=count-4u,"single-beat windows contain an avoidable issue gap");
            if (random_wait) require(errors==8,"error recovery cases incomplete");
            std::printf("WINDOW_QUEUE_PASS depth=%u lanes=%u random=%u accepted=%u retired=%u launches=%u consecutive=%u errors=%u cycles=%u\n",
                TEST_DEPTH,TEST_LANES,random_wait,accepted,retired,launches,consecutive,errors,cycle+1u);
            top.final();return;
        }
    }
    throw std::runtime_error("window queue did not complete within the cycle limit");
}

int main(int argc,char** argv) {
    Verilated::commandArgs(argc,argv);
    try { run(false);run(true);return 0; }
    catch (const std::exception& error) { std::fprintf(stderr,"FAIL: %s\n",error.what());return 1; }
}
