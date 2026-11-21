// SPDX-License-Identifier: Apache-2.0
#include "Vvector_banked_writeback.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <random>
#include <stdexcept>
#include <unordered_map>

#ifndef TEST_TILE_SIZE
#define TEST_TILE_SIZE 16
#endif
#ifndef TEST_BUS_WIDTH
#define TEST_BUS_WIDTH 64
#endif
#ifndef TEST_COALESCE_BYTES_ONLY
#define TEST_COALESCE_BYTES_ONLY 1
#endif
static constexpr unsigned kTile = TEST_TILE_SIZE;
static constexpr unsigned kBusBytes = TEST_BUS_WIDTH / 8;
static constexpr unsigned kCapacity = 4 * kTile;

static void require(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

struct Simulation {
    Vvector_banked_writeback dut;
    std::mt19937 rng{20261121};
    std::unordered_map<uint32_t, uint8_t> expected;
    std::unordered_map<uint32_t, unsigned> written;
    uint64_t cycles = 0, accepted_bytes = 0, written_bytes = 0;
    unsigned requests = 0, transactions = 0, responses = 0, errors = 0;
    unsigned grant_stalls = 0, data_stalls = 0, partial_cancels = 0;
    unsigned remaining = 0, response_delay = 0;
    uint32_t address = 0;
    bool random_wait = false, data_stalled = false, request_stalled = false;
    std::array<uint8_t, kBusBytes> previous_data{};
    uint32_t previous_mask = 0, previous_address = 0, previous_length = 0;

    uint32_t source_word(unsigned index) const {
#if TEST_TILE_SIZE == 1
        (void)index;
        return dut.result_words;
#elif TEST_TILE_SIZE == 2
        return uint32_t(dut.result_words >> (32 * index));
#else
        return dut.result_words[index];
#endif
    }
    void set_word(unsigned index, uint32_t value) {
#if TEST_TILE_SIZE == 1
        (void)index;
        dut.result_words = value;
#elif TEST_TILE_SIZE == 2
        const uint64_t mask = uint64_t(0xffffffffu) << (32 * index);
        dut.result_words = (dut.result_words & ~mask) | (uint64_t(value) << (32 * index));
#else
        dut.result_words[index] = value;
#endif
    }
    uint8_t bus_byte(unsigned lane) const {
#if TEST_BUS_WIDTH <= 64
        return uint8_t(uint64_t(dut.src_wdata) >> (8 * lane));
#else
        return uint8_t(dut.src_wdata[lane / 4] >> (8 * (lane % 4)));
#endif
    }
    void randomize_words() {
        for (unsigned i = 0; i < kTile; ++i) set_word(i, rng());
    }
    void tick() {
        dut.clk = 0;
        dut.wr_granted = dut.wr_req && !remaining && !response_delay &&
                         (!random_wait || rng() % 4 != 0);
        dut.src_wready = remaining && (!random_wait || rng() % 4 != 0);
        dut.wr_done = response_delay == 1;
        dut.wr_error = dut.wr_done && transactions % 17 == 0;
        dut.eval();
        if (dut.request_valid && dut.request_ready) {
            for (unsigned i = 0; i < dut.request_bytes; ++i) {
                const uint32_t destination = uint32_t(dut.request_address) + i;
                const uint8_t value = dut.request_byte_output ?
                    (i < kTile ? uint8_t(source_word(i)) : uint8_t(0)) :
                    uint8_t(source_word(i / 4) >> (8 * (i % 4)));
                require(expected.emplace(destination, value).second, "接收请求的地址发生重复");
            }
            accepted_bytes += dut.request_bytes;
            ++requests;
        }
        if (data_stalled) {
            require(dut.src_wvalid && dut.src_wmask == previous_mask, "暂停期间写使能改变");
            for (unsigned lane = 0; lane < kBusBytes; ++lane)
                require(bus_byte(lane) == previous_data[lane], "暂停期间写数据改变");
        }
        data_stalled = dut.src_wvalid && !dut.src_wready;
        if (data_stalled) ++data_stalls;
        previous_mask = dut.src_wmask;
        for (unsigned lane = 0; lane < kBusBytes; ++lane) previous_data[lane] = bus_byte(lane);
        if (request_stalled)
            require(dut.wr_req && dut.wr_base_addr == previous_address &&
                    dut.wr_burst_len_m1 == previous_length, "授权等待期间事务配置改变");
        request_stalled = dut.wr_req && !dut.wr_granted;
        if (request_stalled) ++grant_stalls;
        previous_address = dut.wr_base_addr;
        previous_length = dut.wr_burst_len_m1;
        if (!random_wait && remaining)
            require(dut.src_wvalid, "连续发送过程中出现空周期");
        if (dut.done) {
            require(dut.wr_done && !remaining, "写入完成早于全部数据");
            require(bool(dut.error) == bool(dut.wr_error), "错误响应没有传递");
            ++responses;
            if (dut.error) ++errors;
        }
        if (response_delay) --response_delay;
        if (dut.wr_start) {
            require(dut.wr_req && dut.wr_granted && !remaining, "事务授权状态错误");
            require(dut.wr_rows_to_write == 1 && dut.wr_row_stride == 0, "行配置错误");
            address = dut.wr_base_addr;
            remaining = dut.wr_burst_len_m1 + 1;
            require(address % kBusBytes == 0, "总线起始地址未按拍宽对齐");
            ++transactions;
        }
        if (dut.src_wvalid && dut.src_wready) {
            require(remaining && dut.src_wmask, "有效写数据缺少事务或字节使能");
            for (unsigned lane = 0; lane < kBusBytes; ++lane) {
                if (!(dut.src_wmask & (1u << lane))) continue;
                const uint32_t destination = address + lane;
                auto item = expected.find(destination);
                require(item != expected.end(), "写入地址尚未完成输入接收");
                require(item->second == bus_byte(lane), "输出字节与输入请求不同");
                require(++written[destination] == 1, "输出字节重复写入");
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
        for (unsigned i = 0; i < 4; ++i) tick();
        dut.rst_n = 1;
        tick();
    }
    void prepare(uint32_t destination, unsigned bytes, bool byte_output, bool coalesce, bool last) {
        dut.request_address = destination;
        dut.request_bytes = bytes;
        dut.request_byte_output = byte_output;
        dut.request_coalesce = coalesce;
        dut.request_last = last;
        randomize_words();
        dut.request_valid = 1;
        dut.eval();
    }
    void send(uint32_t destination, unsigned bytes, bool byte_output, bool coalesce, bool last) {
        prepare(destination, bytes, byte_output, coalesce, last);
        unsigned waited = 0;
        while (!dut.request_ready) {
            require(++waited < 10000, "输入请求接收超时");
            tick();
        }
        tick();
        dut.request_valid = 0;
        randomize_words();
        dut.eval();
    }
    void drain(bool force = false) {
        dut.flush = force;
        for (unsigned waited = 0; dut.busy || remaining || response_delay; ++waited) {
            require(waited < 100000, "写回缓冲排空超时");
            tick();
        }
        dut.flush = 0;
        require(transactions == responses, "存在未完成写响应");
        require(accepted_bytes == written_bytes, "已接收字节未全部写出");
    }
};

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    try {
        Simulation s;
        const unsigned chunk = std::min(kTile, kBusBytes);
        for (unsigned index = 0; index < 2 * kCapacity / chunk; ++index)
            s.send(0x1000 + chunk * index, chunk, true, true,
                   index + 1 == 2 * kCapacity / chunk);
        s.drain();
        require(s.transactions == 2, "连续请求未形成两个完整容量的突发");
        uint32_t next = 0x10000;
        for (unsigned alignment = 0; alignment < kBusBytes; ++alignment) {
            for (unsigned bytes = 1; bytes <= kCapacity; ++bytes) {
                s.send(next + alignment, bytes, false, false, true);
                next += kCapacity + kBusBytes;
            }
            for (unsigned bytes = 1; bytes <= kCapacity; ++bytes) {
                s.send(next + alignment, bytes, true, false, true);
                next += kCapacity + kBusBytes;
            }
        }
        s.drain();
        s.random_wait = true;
        for (unsigned index = 0; index < 300; ++index) {
            const bool byte_mode = index % 3 != 0;
            const unsigned bytes = 1 + s.rng() % (byte_mode ? kTile : kCapacity);
            s.send(next, bytes, byte_mode, index % 5 != 0, index % 7 == 6);
            next += bytes;
            if (index % 11 == 0) next += 3;
            if (index % 13 == 0) for (unsigned pause = 0; pause < 5; ++pause) s.tick();
        }
        s.drain(true);
        if (kCapacity > kBusBytes) {
            s.prepare(next, kCapacity, false, false, true);
            require(!s.dut.request_ready, "多拍请求提前完成接收");
            s.tick();
            s.dut.request_valid = 0;
            s.drain(true);
            ++s.partial_cancels;
            s.send(next, kCapacity, false, false, true);
            s.drain();
        }
        s.send(0xfffffffcu, std::min(kCapacity, 12u), false, false, true);
        s.drain();
        require(s.expected.size() == s.written.size(), "输出地址集合不完整");
        require(s.errors && s.grant_stalls && s.data_stalls, "错误及暂停覆盖不足");
        s.dut.final();
        std::printf("VECTOR_BANKED_WRITEBACK_PASS tile=%u bus_bits=%u coalesce_bytes_only=%u requests=%u bytes=%llu transactions=%u responses=%u errors=%u grant_stalls=%u data_stalls=%u partial_cancels=%u cycles=%llu\n",
                    kTile, TEST_BUS_WIDTH, TEST_COALESCE_BYTES_ONLY, s.requests, (unsigned long long)s.written_bytes,
                    s.transactions, s.responses, s.errors, s.grant_stalls, s.data_stalls,
                    s.partial_cancels, (unsigned long long)s.cycles);
        return 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "FAIL: %s\n", error.what());
        return 1;
    }
}
