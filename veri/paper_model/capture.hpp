#pragma once
#include <array>
#include <cstdint>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

struct Capture {
    uint64_t cycles = 0;
    uint64_t time_ps = 0;
    uint64_t start_cycle = std::numeric_limits<uint64_t>::max();
    uint64_t ready_cycle = std::numeric_limits<uint64_t>::max();
    bool saw_busy = false;
    bool initialized = false;
    std::array<uint32_t, 32> scalars{};
    std::array<std::vector<uint32_t>, 4> lanes;
    std::ofstream csv;
    // Read-only compact dump of final INT32 accumulator vectors.
    std::ofstream acc_dump;
    std::string io_summary_path;
    uint64_t task_accept_cycle = std::numeric_limits<uint64_t>::max();
    uint64_t last_output_w_cycle = std::numeric_limits<uint64_t>::max();
    uint64_t last_output_b_cycle = std::numeric_limits<uint64_t>::max();
    uint64_t accepted_ar = 0, accepted_r = 0, accepted_aw = 0, accepted_w = 0, accepted_b = 0;
    uint64_t valid_output_bytes = 0;
    std::array<uint64_t,256> read_burst_hist{};
    std::array<uint64_t,256> write_burst_hist{};
    void initialize();
    void write_io_summary();
};

extern thread_local Capture* active_capture;
