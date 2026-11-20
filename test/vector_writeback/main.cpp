// SPDX-License-Identifier: Apache-2.0
#include "Vvector_writeback.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <random>
#include <stdexcept>
#include <tuple>
#include <vector>

#ifndef TEST_BUS_WIDTH
#define TEST_BUS_WIDTH 64
#endif
static constexpr unsigned kBusBytes = TEST_BUS_WIDTH / 8;
static void require(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}

struct Simulation {
    Vvector_writeback dut;
    std::mt19937 rng{20261121};
    std::vector<int> expected = std::vector<int>(1 << 16, -1);
    std::vector<unsigned> observed = std::vector<unsigned>(1 << 16, 0);
    uint64_t cycles = 0, accepted_bytes = 0, written_bytes = 0;
    unsigned transactions = 0, responses = 0, error_responses = 0;
    unsigned remaining = 0, address = 0, response_delay = 0;
    bool stalled = false;
    std::tuple<uint64_t, unsigned> previous;
    bool random_wait = true;

    void tick() {
        dut.clk = 0;
        dut.wr_granted = dut.wr_req && !remaining && !response_delay &&
                         (!random_wait || rng() % 4 != 0);
        dut.src_wready = remaining && (!random_wait || rng() % 4 != 0);
        dut.wr_done = response_delay == 1;
        dut.wr_error = dut.wr_done && transactions % 17 == 0;
        dut.eval();
        auto current = std::make_tuple(uint64_t(dut.src_wdata), unsigned(dut.src_wmask));
        if (stalled) require(dut.src_wvalid && current == previous, "写数据在停顿期间改变");
        stalled = dut.src_wvalid && !dut.src_wready;
        previous = current;
        if (dut.done) {
            require(dut.wr_done && !remaining, "写入完成早于数据结束");
            require(bool(dut.error) == bool(dut.wr_error), "写入错误状态丢失");
            ++responses;
            if (dut.error) ++error_responses;
        }
        if (response_delay) --response_delay;
        if (dut.wr_start) {
            require(dut.wr_req && dut.wr_granted && !remaining, "写入请求接收错误");
            require(dut.wr_rows_to_write == 1 && dut.wr_row_stride == 0, "写入行配置错误");
            address = dut.wr_base_addr;
            remaining = dut.wr_burst_len_m1 + 1;
            require(address % kBusBytes == 0, "总线起始地址未按字节数对齐");
            ++transactions;
        }
        if (dut.src_wvalid && dut.src_wready) {
            require(remaining && dut.src_wmask, "写数据缺少事务或字节使能");
            for (unsigned lane = 0; lane < kBusBytes; ++lane) {
                if (!(dut.src_wmask & (1u << lane))) continue;
                const unsigned destination = address + lane;
                require(destination < expected.size() && expected[destination] >= 0, "写入未授权地址");
                const unsigned value = (uint64_t(dut.src_wdata) >> (8 * lane)) & 255;
                require(value == unsigned(expected[destination]), "写入数据与接收结果不同");
                require(observed[destination] == 0, "输出字节重复写入");
                observed[destination] = 1;
                ++written_bytes;
            }
            address += kBusBytes;
            if (--remaining == 0) response_delay = random_wait ? 1 + rng() % 9 : 1;
        }
        dut.clk = 1;
        dut.eval();
        Verilated::timeInc(1);
        ++cycles;
        dut.clk = 0;
        dut.eval();
    }

    Simulation() {
        dut.rst_n = 0;
        dut.request_valid = 0;
        dut.flush = 0;
        for (unsigned i = 0; i < 5; ++i) tick();
        dut.rst_n = 1;
        tick();
    }

    void send(unsigned destination, unsigned bytes, bool byte_output, bool coalesce, bool last) {
        dut.request_address = destination;
        dut.request_bytes = bytes;
        dut.request_byte_output = byte_output;
        dut.request_coalesce = coalesce;
        dut.request_last = last;
        for (unsigned i = 0; i < 16; ++i) dut.result_words[i] = rng();
        for (unsigned i = 0; i < bytes; ++i) {
            require(expected.at(destination + i) < 0, "测试输出范围重叠");
            expected[destination + i] = byte_output ? dut.result_words[i] & 255 :
                (dut.result_words[i / 4] >> (8 * (i % 4))) & 255;
        }
        dut.request_valid = 1;
        dut.eval();
        unsigned waited = 0;
        while (!dut.request_ready) {
            require(++waited < 1000, "结果接收没有完成");
            tick();
        }
        tick();
        dut.request_valid = 0;
        accepted_bytes += bytes;
        // 接收后立即改变生产方数据，写出必须使用已保存的内容。
        for (unsigned i = 0; i < 16; ++i) dut.result_words[i] = rng();
        dut.eval();
    }

    void drain(bool force_flush = false) {
        dut.flush = force_flush;
        unsigned waited = 0;
        while (dut.busy || remaining || response_delay) {
            require(++waited < 10000, "写入队列没有完成");
            tick();
        }
        dut.flush = 0;
        require(transactions == responses, "完成时仍有写入响应未返回");
        require(accepted_bytes == written_bytes, "完成时存在丢失输出字节");
    }
};

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    try {
        Simulation s;
        s.random_wait = false;
        for (unsigned index = 0; index < 16; ++index)
            s.send(0x1000 + 8 * index, 8, true, true, index == 15);
        s.drain();
        require(s.transactions == 2 && s.written_bytes == 128, "连续结果未形成两个64字节突发");
        s.random_wait = true;
        unsigned address = 0x2003;
        for (unsigned index = 0; index < 240; ++index) {
            const bool byte_output = index % 3 != 0;
            const unsigned bytes = 1 + s.rng() % (byte_output ? 16 : 64);
            const bool coalesce = index % 5 != 0;
            const bool last = index % 7 == 6;
            s.send(address, bytes, byte_output, coalesce, last);
            address += bytes;
            if (index % 11 == 0) address += 3;
            if (index % 13 == 0) for (unsigned wait = 0; wait < 5; ++wait) s.tick();
        }
        s.drain(true);
        for (unsigned index = 0; index < s.expected.size(); ++index)
            require(s.observed[index] == unsigned(s.expected[index] >= 0), "输出地址集合不一致");
        s.dut.final();
        std::printf("VECTOR_WRITEBACK_PASS bus_bits=%u requests=256 bytes=%llu transactions=%u responses=%u errors=%u cycles=%llu\n",
                    TEST_BUS_WIDTH, (unsigned long long)s.written_bytes, s.transactions,
                    s.responses, s.error_responses, (unsigned long long)s.cycles);
        return 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "FAIL: %s\n", error.what());
        return 1;
    }
}
