#include "Vps_replay_top.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <deque>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef TEST_DEPTH
#define TEST_DEPTH 17
#define TEST_FRAMES 3
#define TEST_MAX_LEN 7
#endif

class Test {
    VerilatedContext context;
    Vps_replay_top top{&context};
    std::deque<std::vector<uint64_t>> frames;
    std::deque<uint64_t> replay;
    std::vector<uint64_t> collecting;
    bool last_end = false, last_trigger = false;
    uint32_t random_state = 0x51327a19;
    uint64_t serial = 1, cycles = 0, rows = 0, replayed = 0;
    uint64_t empty_push_pop = 0, queued_push_pop = 0, push_while_replaying = 0;
    uint64_t forwarded = 0, write_wraps = 0;
    uint32_t last_write_address = 0;
    bool had_write = false;

    void require(bool ok, const char* message) {
        if (!ok) throw std::runtime_error(std::string(message) + " at cycle " + std::to_string(cycles));
    }
    uint32_t random() {
        random_state ^= random_state << 13;
        random_state ^= random_state >> 17;
        random_state ^= random_state << 5;
        return random_state;
    }
    uint64_t value() { return (serial++ * UINT64_C(0x9e3779b97f4a7c15)) ^ UINT64_C(0xd10ca6d782fe3419); }
public:
    Test(int argc, char** argv) {
        context.commandArgs(argc, argv);
        top.rst_n = 0; top.clk = 0; top.input_valid = 0;
        top.frame_end = 0; top.replay_trigger = 0; top.replay_enable = 1;
        for (int i = 0; i < 3; ++i) { top.clk = 0; top.eval(); top.clk = 1; top.eval(); }
        top.rst_n = 1;
    }
    size_t occupied() const {
        size_t total = replay.size() + collecting.size();
        for (const auto& frame : frames) total += frame.size();
        return total;
    }
    void tick(bool write = false, bool finish = false, bool trigger = false, bool enable = true) {
        const bool active = !replay.empty();
        const uint64_t expected = active ? replay.front() : 0;
        const bool was_empty = frames.empty();
        const uint64_t input = write ? value() : 0;
        if (write) { collecting.push_back(input); ++rows; }
        const bool push = finish && !last_end && !collecting.empty();
        if (push) {
            require(collecting.size() <= TEST_MAX_LEN, "frame length exceeds configured limit");
            frames.push_back(collecting);
            collecting.clear();
            push_while_replaying += active;
        }
        const bool pop = trigger && !last_trigger && enable && !active && !frames.empty();
        if (active) { replay.pop_front(); ++replayed; }
        if (pop) {
            replay.assign(frames.front().begin(), frames.front().end());
            frames.pop_front();
            if (push) { empty_push_pop += was_empty; queued_push_pop += !was_empty; }
        }
        require(frames.size() <= TEST_FRAMES && occupied() <= TEST_DEPTH, "test exceeds admitted storage");
        last_end = finish; last_trigger = trigger;
        top.clk = 0; top.input_valid = write; top.data_in = input;
        top.frame_end = finish; top.replay_trigger = trigger; top.replay_enable = enable;
        top.eval(); top.clk = 1; context.timeInc(1); top.eval(); ++cycles;
        if (top.data_out != expected) {
            std::fprintf(stderr, "actual=%016llx expected=%016llx\n", (unsigned long long)top.data_out, (unsigned long long)expected);
            require(false, "replayed data differs");
        }
        require(!top.capacity_fault, "unexpected capacity fault");
        require(top.frame_count == frames.size(), "queued frame count differs");
        require(top.replay_count == replay.size(), "remaining replay count differs");
        require(bool(top.replay_ready) == (!frames.empty() && replay.empty()), "replay readiness differs");
        forwarded += top.forward_hit;
        if (top.write_enable) {
            require(top.write_address < TEST_DEPTH, "write address outside exact depth");
            write_wraps += had_write && top.write_address < last_write_address;
            last_write_address = top.write_address; had_write = true;
        }
    }
    void frame(unsigned length, bool immediate = false) {
        for (unsigned i = 0; i < length; ++i) tick(true, i + 1 == length, immediate && i + 1 == length);
        tick();
    }
    void drain() {
        while (!frames.empty() || !replay.empty()) tick(false, false, !last_trigger);
        tick();
    }
    void run() {
        frame(1, true);
        drain();
        frame(3, true);
        drain();
        frame(2);
        frame(2, true);
        drain();
        frame(3);
        tick(false, false, true);
        tick(true, false, false);
        tick(true, true, false);
        drain();

        unsigned target = 0;
        for (unsigned i = 0; i < 5000; ++i) {
            if (target == 0) target = 1 + random() % TEST_MAX_LEN;
            const bool write = frames.size() < TEST_FRAMES && occupied() < TEST_DEPTH && !last_end && random() % 3 != 0;
            const bool finish = write && collecting.size() + 1 == target;
            const bool trigger = !last_trigger && random() % 3 != 0;
            tick(write, finish, trigger);
            if (finish) target = 0;
        }
        if (!collecting.empty()) {
            while (frames.size() == TEST_FRAMES || !replay.empty()) tick(false, false, !last_trigger);
            tick(false, true, !last_trigger);
            tick();
        }
        drain();
        require(rows == replayed, "row accounting differs");
        require(empty_push_pop > 0 && queued_push_pop > 0 && push_while_replaying > 0, "frame boundary coverage missing");
        require(forwarded > 0 && write_wraps > 10, "forwarding or ring wrap coverage missing");
        std::printf("PS_REPLAY_PASS depth=%u frames=%u cycles=%llu rows=%llu empty_push_pop=%llu queued_push_pop=%llu push_while_replaying=%llu forwarded=%llu write_wraps=%llu\n",
            TEST_DEPTH, TEST_FRAMES, (unsigned long long)cycles, (unsigned long long)rows,
            (unsigned long long)empty_push_pop, (unsigned long long)queued_push_pop,
            (unsigned long long)push_while_replaying, (unsigned long long)forwarded,
            (unsigned long long)write_wraps);
        top.final();
    }
};

int main(int argc, char** argv) {
    try { Test test(argc, argv); test.run(); return 0; }
    catch (const std::exception& error) { std::fprintf(stderr, "PS_REPLAY_FAIL %s\n", error.what()); return 1; }
}
