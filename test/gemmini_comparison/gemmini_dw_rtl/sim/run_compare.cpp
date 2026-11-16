#include "VGemminiCompare.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef GEMMINI_AXI_DATA_BITS
#error "Define GEMMINI_AXI_DATA_BITS from the generated hardware configuration"
#endif
static constexpr unsigned axi_data_bits = GEMMINI_AXI_DATA_BITS;
static constexpr unsigned axi_data_bytes = axi_data_bits / 8;
static constexpr unsigned axi_size_max = axi_data_bits == 64 ? 3 : 2;
static constexpr unsigned axi_max_beats = 256;
static_assert(axi_data_bits == 32 || axi_data_bits == 64);

struct Command { bool fence; unsigned funct; uint64_t rs1, rs2; };
struct ReadRequest {
  unsigned id, size, beats;
  uint64_t address;
  uint64_t accepted_cycle, ready_cycle, offered_cycle;
  bool first_beat;
};

static std::vector<uint8_t> load(const std::string& path) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) throw std::runtime_error("Cannot read " + path);
  return std::vector<uint8_t>(std::istreambuf_iterator<char>(stream), {});
}

int main(int argc, char** argv) {
  try {
    if (argc != 10 && argc != 12 && argc != 13) throw std::runtime_error(
      "Usage: simulator memory.bin memory_base commands.txt output_base output_bytes expected.bin timed_start result.json read_interval [first_read_latency inter_burst_gap_cycles [read_outstanding_limit]]");
    VerilatedContext context;
    context.commandArgs(argc, argv);
    VGemminiCompare model(&context);
    static_assert(sizeof(model.mem_r_bits_data) * 8 == axi_data_bits);
    static_assert(sizeof(model.mem_w_bits_data) * 8 == axi_data_bits);
    const uint64_t memory_base = std::stoull(argv[2], nullptr, 0);
    const uint64_t output_base = std::stoull(argv[4], nullptr, 0);
    const size_t output_bytes = std::stoull(argv[5], nullptr, 0);
    const size_t timed_start = std::stoull(argv[7], nullptr, 0);
    const unsigned read_interval = std::stoul(argv[9], nullptr, 0);
    const bool request_deadline = argc >= 12;
    const unsigned read_latency = request_deadline ? std::stoul(argv[10], nullptr, 0) : 3;
    const unsigned inter_burst_gap = request_deadline ? std::stoul(argv[11], nullptr, 0) : 3;
    const unsigned read_outstanding_limit = argc == 13 ? std::stoul(argv[12], nullptr, 0) : 4;
    const char* cycle_limit_env = std::getenv("GEMMINI_MAX_CYCLES");
    const uint64_t cycle_limit = cycle_limit_env ? std::stoull(cycle_limit_env) : 10000000;
    auto memory = load(argv[1]);
    memory.resize(memory.size() + 4096, 0);
    const auto initial_memory = memory;
    const auto expected = load(argv[6]);
    if (expected.size() != output_bytes) throw std::runtime_error("Reference length mismatch");
    std::ifstream command_file(argv[3]);
    if (!command_file) throw std::runtime_error("Cannot read commands");
    std::vector<Command> commands;
    for (std::string line; std::getline(command_file, line);) {
      if (line.empty()) continue;
      if (line == "FENCE") commands.push_back({true, 0, 0, 0});
      else {
        std::istringstream fields(line);
        std::string funct, a, b;
        if (!(fields >> funct >> a >> b)) throw std::runtime_error("Invalid command record");
        commands.push_back({false, unsigned(std::stoul(funct, nullptr, 0)),
          std::stoull(a, nullptr, 0), std::stoull(b, nullptr, 0)});
      }
    }
    if (read_interval < 1 || read_latency < 1 || inter_burst_gap < 1 || read_outstanding_limit < 1)
      throw std::runtime_error("Memory response intervals must be positive");
    uint64_t cycle = 0, first_cycle = 0;
    uint64_t read_bytes = 0, write_bytes = 0, get_requests = 0, put_requests = 0;
    uint64_t read_beats = 0, write_beats = 0;
    uint64_t max_read_burst_beats = 0, max_write_burst_beats = 0;
    std::array<uint64_t, 4> read_beats_by_size{}, write_beats_by_size{};
    std::array<uint64_t, 4> read_requests_by_size{}, write_requests_by_size{};
    uint64_t read_pending = 0, write_pending = 0;
    uint64_t max_read_pending = 0, max_write_pending = 0;
    uint64_t max_read_burst_bytes = 0, max_write_burst_bytes = 0;
    uint64_t read_latency_min = std::numeric_limits<uint64_t>::max(), read_latency_max = 0;
    uint64_t read_latency_sum = 0, read_first_responses = 0;
    uint64_t first_read_queue_delay_sum = 0, first_read_queue_delay_max = 0;
    uint64_t first_read_backpressure_sum = 0, first_read_backpressure_max = 0;
    uint64_t matured_switch_gap_min = std::numeric_limits<uint64_t>::max(), matured_switch_gap_max = 0;
    uint64_t matured_switches = 0, consecutive_burst_transitions = 0;
    int64_t previous_burst_last_cycle = -1;
    uint64_t load_cycles = 0, execute_cycles = 0, store_cycles = 0, busy_cycles = 0;
    uint64_t im2col_cycles = 0, im2col_requests = 0, im2col_responses = 0;
    uint64_t loop_conv_launches = 0, loop_dw_launches = 0;
    uint64_t dwconv_cycles = 0, loop_dwconv_cycles = 0;
    int64_t first_ar = -1, first_r = -1, last_r = -1;
    int64_t first_aw = -1, first_w = -1, last_w = -1, last_b = -1;
    int64_t first_launch = -1;
    std::deque<ReadRequest> reads;
    ReadRequest current_read{};
    bool read_active = false, rvalid = false;
    uint64_t rdata = 0;
    uint64_t next_read_fill = 0;
    uint64_t next_read_handshake = 0;
    bool write_active = false, bvalid = false;
    unsigned write_left = 0, write_id = 0, write_size = 0;
    uint64_t write_address = 0;
    auto read_word = [&](uint64_t address, unsigned size) {
      uint64_t value = 0xa5a5a5a5a5a5a5a5ULL;
      const uint64_t lane_offset = address & (axi_data_bytes - 1);
      for (unsigned lane=0;lane<axi_data_bytes;lane++) {
        if (lane < lane_offset || lane >= lane_offset + (1u << size)) continue;
        const auto byte = (address & ~uint64_t(axi_data_bytes - 1)) + lane;
        if (byte < memory_base || byte-memory_base >= memory.size())
          throw std::runtime_error("Read outside comparison memory");
        value = (value & ~(0xffULL << (lane*8))) | (uint64_t(memory[byte-memory_base]) << (lane*8));
      }
      return value;
    };
    auto validate_burst = [&](uint64_t address, unsigned size, unsigned beats, unsigned burst) {
      if (size > axi_size_max || burst != 1 || beats == 0 || beats > axi_max_beats)
        throw std::runtime_error("AXI burst parameters exceed the physical interface");
      const uint64_t bytes_per_beat = 1ULL << size;
      const uint64_t aligned_start = address & ~(bytes_per_beat - 1);
      if ((aligned_start & 4095) + beats * bytes_per_beat > 4096)
        throw std::runtime_error("AXI burst crosses 4 KiB");
    };
    auto tick = [&](bool collect) {
      model.clock = 0;
      model.mem_ar_ready = !model.reset && (request_deadline ?
        reads.size() + unsigned(read_active) < read_outstanding_limit : reads.size() < 16);
      model.mem_aw_ready = !model.reset && !write_active && !bvalid;
      model.mem_w_ready = !model.reset && write_active;
      model.mem_r_valid = !model.reset && rvalid;
      model.mem_r_bits_data = rdata;
      model.mem_r_bits_id = current_read.id;
      model.mem_r_bits_resp = 0;
      model.mem_r_bits_last = current_read.beats == 1;
      model.mem_b_valid = !model.reset && bvalid;
      model.mem_b_bits_resp = 0;
      model.mem_b_bits_id = write_id;
      model.eval();
      const bool command_fire = model.command_valid && model.command_ready;
      const bool ar_fire = model.mem_ar_valid && model.mem_ar_ready;
      const bool r_fire = model.mem_r_valid && model.mem_r_ready;
      const bool aw_fire = model.mem_aw_valid && model.mem_aw_ready;
      const bool w_fire = model.mem_w_valid && model.mem_w_ready;
      const bool b_fire = model.mem_b_valid && model.mem_b_ready;
      const bool pop = !read_active && !reads.empty();
      const bool fill = read_active && !rvalid && cycle >= next_read_fill;
      const ReadRequest new_read{model.mem_ar_bits_id, model.mem_ar_bits_size,
        unsigned(model.mem_ar_bits_len) + 1, model.mem_ar_bits_addr,
        cycle, cycle + read_latency, 0, true};
      const unsigned new_read_burst = model.mem_ar_bits_burst;
      const unsigned new_write_id = model.mem_aw_bits_id;
      const unsigned new_write_size = model.mem_aw_bits_size;
      const unsigned new_write_left = unsigned(model.mem_aw_bits_len) + 1;
      const uint64_t new_write_address = model.mem_aw_bits_addr;
      const unsigned new_write_burst = model.mem_aw_bits_burst;
      const uint64_t write_data = model.mem_w_bits_data;
      const unsigned write_mask = model.mem_w_bits_strb;
      const bool write_last = model.mem_w_bits_last;
      if (collect) {
        if (command_fire && (model.command_funct == 8 || model.command_funct == 15 || model.command_funct == 29) && first_launch < 0)
          first_launch = cycle-first_cycle;
        busy_cycles += model.busy;
        load_cycles += model.load_busy;
        execute_cycles += model.execute_busy;
        store_cycles += model.store_busy;
        dwconv_cycles += model.dwconv_active;
        loop_dwconv_cycles += model.loop_dwconv_busy;
        im2col_cycles += model.im2col_active;
        im2col_requests += model.im2col_request_valid && model.im2col_request_ready;
        im2col_responses += model.im2col_response_valid && model.im2col_response_ready;
        if (command_fire && model.command_funct == 15) {
          loop_conv_launches++;
        }
        if (command_fire && model.command_funct == 29) loop_dw_launches++;
      }
      model.clock = 1;
      model.eval();
      context.timeInc(1);
      if (!model.reset) {
        if (!request_deadline && fill) {
          rvalid = true;
          rdata = read_word(current_read.address, current_read.size);
          if (current_read.first_beat) current_read.offered_cycle = cycle + 1;
        }
        if (r_fire) {
          if (request_deadline && cycle < current_read.ready_cycle)
            throw std::runtime_error("Read response precedes the request deadline");
          if (collect) {
            read_beats++;
            read_beats_by_size.at(current_read.size)++;
            if (current_read.first_beat) {
              const uint64_t latency = cycle - current_read.accepted_cycle;
              read_latency_min = std::min(read_latency_min, latency);
              read_latency_max = std::max(read_latency_max, latency);
              read_latency_sum += latency;
              read_first_responses++;
              const uint64_t queue_delay = current_read.offered_cycle > current_read.ready_cycle ?
                current_read.offered_cycle - current_read.ready_cycle : 0;
              const uint64_t backpressure = cycle - current_read.offered_cycle;
              first_read_queue_delay_sum += queue_delay;
              first_read_queue_delay_max = std::max(first_read_queue_delay_max, queue_delay);
              first_read_backpressure_sum += backpressure;
              first_read_backpressure_max = std::max(first_read_backpressure_max, backpressure);
              if (previous_burst_last_cycle >= 0 &&
                  current_read.accepted_cycle <= uint64_t(previous_burst_last_cycle) &&
                  current_read.ready_cycle <= uint64_t(previous_burst_last_cycle) + inter_burst_gap) {
                const uint64_t gap = cycle - uint64_t(previous_burst_last_cycle);
                matured_switch_gap_min = std::min(matured_switch_gap_min, gap);
                matured_switch_gap_max = std::max(matured_switch_gap_max, gap);
                matured_switches++;
                consecutive_burst_transitions += gap == 1;
              }
            }
            if (current_read.beats == 1) {
              if (read_pending == 0) throw std::runtime_error("Read completion has no outstanding request");
              read_pending--;
              previous_burst_last_cycle = int64_t(cycle);
            }
          }
          current_read.first_beat = false;
          rvalid = false;
          if (--current_read.beats == 0) {
            read_active = false;
            next_read_handshake = cycle + inter_burst_gap;
          }
          else {
            current_read.address = (current_read.address & ~((1ull << current_read.size)-1)) + (1ull << current_read.size);
            next_read_handshake = cycle + read_interval;
            if (!request_deadline && read_interval == 1) {
              rdata = read_word(current_read.address, current_read.size);
              rvalid = true;
            }
          }
          next_read_fill = cycle + read_interval - 1;
          if (collect) { if (first_r < 0) first_r = cycle-first_cycle; last_r = cycle-first_cycle; }
        }
        if (!request_deadline && pop) {
          current_read = reads.front(); reads.pop_front(); read_active = true;
          next_read_fill = cycle+1;
        }
        if (ar_fire) {
          validate_burst(new_read.address, new_read.size, new_read.beats, new_read_burst);
          const uint64_t bytes = uint64_t(new_read.beats) << new_read.size;
          reads.push_back(new_read);
          if (collect) {
            get_requests++; read_bytes += bytes;
            read_requests_by_size.at(new_read.size)++;
            max_read_burst_beats = std::max(max_read_burst_beats, uint64_t(new_read.beats));
            max_read_pending = std::max(max_read_pending, ++read_pending);
            max_read_burst_bytes = std::max(max_read_burst_bytes, bytes);
            if (first_ar < 0) first_ar = cycle-first_cycle;
          }
        }
        if (request_deadline) {
          if (!read_active && !reads.empty()) {
            current_read = reads.front();
            reads.pop_front();
            read_active = true;
          }
          // The synchronous memory register is filled on the edge before the
          // earliest permitted handshake. Each request waits from its own AR.
          if (read_active && !rvalid && cycle + 1 >= current_read.ready_cycle &&
              cycle + 1 >= next_read_handshake) {
            rdata = read_word(current_read.address, current_read.size);
            rvalid = true;
            if (current_read.first_beat) current_read.offered_cycle = cycle + 1;
          }
        }
        if (aw_fire) {
          validate_burst(new_write_address, new_write_size, new_write_left, new_write_burst);
          write_active = true; write_id = new_write_id; write_size = new_write_size;
          write_address = new_write_address; write_left = new_write_left;
          if (collect) {
            put_requests++; if (first_aw < 0) first_aw = cycle-first_cycle;
            write_requests_by_size.at(new_write_size)++;
            max_write_burst_beats = std::max(max_write_burst_beats, uint64_t(new_write_left));
            max_write_pending = std::max(max_write_pending, ++write_pending);
            max_write_burst_bytes = std::max(max_write_burst_bytes, uint64_t(new_write_left) << new_write_size);
          }
        }
        if (w_fire) {
          if (write_last != (write_left == 1)) throw std::runtime_error("Incorrect AXI WLAST");
          if (write_mask >> axi_data_bytes) throw std::runtime_error("Write strobe exceeds the physical data width");
          if (collect) { write_beats++; write_beats_by_size.at(write_size)++; }
          for (unsigned lane=0;lane<axi_data_bytes;lane++) if (write_mask & (1u << lane)) {
            const uint64_t address = (write_address & ~uint64_t(axi_data_bytes - 1)) + lane;
            if (address < memory_base || address-memory_base >= memory.size())
              throw std::runtime_error("Write outside comparison memory");
            if (address < output_base || address-output_base >= output_bytes)
              throw std::runtime_error("Write outside the output tensor");
            memory[address-memory_base] = uint8_t(write_data >> (lane*8));
            if (collect) write_bytes++;
          }
          if (--write_left == 0) { bvalid = true; write_active = false; }
          else write_address = (write_address & ~((1ull << write_size)-1)) + (1ull << write_size);
          if (collect) { if (first_w < 0) first_w = cycle-first_cycle; last_w = cycle-first_cycle; }
        }
        if (b_fire) {
          bvalid = false;
          if (collect) {
            last_b = cycle-first_cycle;
            if (write_pending == 0) throw std::runtime_error("Write completion has no outstanding request");
            write_pending--;
          }
        }
      }
      cycle++;
      if (context.gotFinish()) throw std::runtime_error("RTL assertion terminated simulation");
      return command_fire;
    };
    model.command_valid = 0;
    model.command_funct = 0;
    model.command_rs1 = 0;
    model.command_rs2 = 0;
    model.reset = 1;
    for (int i=0;i<8;i++) tick(false);
    model.reset = 0;
    for (int i=0;i<4;i++) tick(false);
    size_t record = 0;
    while (record < commands.size()) {
      if (record == timed_start && first_cycle == 0) first_cycle = cycle;
      const bool timed = first_cycle != 0;
      const auto command = commands[record];
      if (command.fence) {
        model.command_valid = 0;
        tick(timed);
        if (!model.busy && reads.empty() && !read_active && !rvalid && !write_active && !bvalid) record++;
      } else {
        model.command_valid = 1;
        model.command_funct = command.funct;
        model.command_rs1 = command.rs1;
        model.command_rs2 = command.rs2;
        if (tick(timed)) record++;
      }
      if (cycle > cycle_limit) {
        std::ostringstream message;
        message << "Simulation cycle limit exceeded: record=" << record << "/" << commands.size()
          << " busy=" << unsigned(model.busy) << " load=" << unsigned(model.load_busy)
          << " execute=" << unsigned(model.execute_busy) << " store=" << unsigned(model.store_busy)
          << " reads=" << get_requests << " writes=" << put_requests;
        throw std::runtime_error(message.str());
      }
    }
    const uint64_t elapsed = cycle-first_cycle;
    size_t mismatches = 0;
    for (size_t i=0;i<output_bytes;i++) {
      const auto actual = memory.at(output_base-memory_base+i);
      if (actual != expected[i]) {
        if (mismatches < 8) std::cerr << "Output mismatch index=" << i << " actual=" << int(int8_t(actual))
          << " expected=" << int(int8_t(expected[i])) << '\n';
        mismatches++;
      }
    }
    size_t outside_output_mismatches = 0;
    for (size_t i=0;i<memory.size();i++) {
      const uint64_t address = memory_base+i;
      if (address >= output_base && address-output_base < output_bytes) continue;
      if (memory[i] != initial_memory[i]) outside_output_mismatches++;
    }
    const bool memory_drained = reads.empty() && !read_active && !rvalid && !write_active && !bvalid;
    if (!memory_drained || read_pending || write_pending)
      throw std::runtime_error("Comparison completed before all AXI responses drained");
    std::string observed_path = argv[8];
    if (observed_path.size() >= 5 && observed_path.substr(observed_path.size()-5) == ".json")
      observed_path.resize(observed_path.size()-5);
    observed_path += ".output.bin";
    std::ofstream observed(observed_path, std::ios::binary);
    observed.write(reinterpret_cast<const char*>(memory.data()+output_base-memory_base), output_bytes);
    if (!observed) throw std::runtime_error("Cannot save observed output");
    std::ofstream result(argv[8]);
    auto histogram = [](const std::array<uint64_t, 4>& values) {
      std::ostringstream text;
      text << '{';
      for (unsigned size = 0; size <= axi_size_max; size++) {
        if (size) text << ", ";
        text << '"' << (1u << size) << "\": " << values[size];
      }
      text << '}';
      return text.str();
    };
    result << "{\n  \"passed\": " << (mismatches == 0 && outside_output_mismatches == 0 ? "true" : "false")
      << ",\n  \"cycles\": " << elapsed << ",\n  \"read_bytes\": " << read_bytes
      << ",\n  \"write_bytes\": " << write_bytes << ",\n  \"read_requests\": " << get_requests
      << ",\n  \"max_read_burst_bytes\": " << max_read_burst_bytes
      << ",\n  \"max_write_burst_bytes\": " << max_write_burst_bytes
      << ",\n  \"axi_data_bits\": " << axi_data_bits
      << ",\n  \"axi_strobe_bits\": " << axi_data_bytes
      << ",\n  \"axi_max_beats\": " << axi_max_beats
      << ",\n  \"axi_boundary_bytes\": 4096"
      << ",\n  \"read_beats\": " << read_beats
      << ",\n  \"write_beats\": " << write_beats
      << ",\n  \"read_bus_lane_bytes\": " << read_beats * axi_data_bytes
      << ",\n  \"write_bus_lane_bytes\": " << write_beats * axi_data_bytes
      << ",\n  \"max_read_burst_beats\": " << max_read_burst_beats
      << ",\n  \"max_write_burst_beats\": " << max_write_burst_beats
      << ",\n  \"max_read_outstanding_observed\": " << max_read_pending
      << ",\n  \"max_write_outstanding_observed\": " << max_write_pending
      << ",\n  \"read_requests_by_beat_bytes\": " << histogram(read_requests_by_size)
      << ",\n  \"write_requests_by_beat_bytes\": " << histogram(write_requests_by_size)
      << ",\n  \"read_beats_by_beat_bytes\": " << histogram(read_beats_by_size)
      << ",\n  \"write_beats_by_beat_bytes\": " << histogram(write_beats_by_size)
      << ",\n  \"write_requests\": " << put_requests << ",\n  \"load_busy_cycles\": " << load_cycles
      << ",\n  \"execute_busy_cycles\": " << execute_cycles << ",\n  \"store_busy_cycles\": " << store_cycles
      << ",\n  \"busy_cycles\": " << busy_cycles << ",\n  \"output_mismatches\": " << mismatches
      << ",\n  \"outside_output_mismatches\": " << outside_output_mismatches
      << ",\n  \"independent_im2col_active_cycles\": " << im2col_cycles
      << ",\n  \"independent_im2col_requests\": " << im2col_requests
      << ",\n  \"independent_im2col_responses\": " << im2col_responses
      << ",\n  \"dwconv_active_cycles\": " << dwconv_cycles
      << ",\n  \"loop_dwconv_busy_cycles\": " << loop_dwconv_cycles
      << ",\n  \"loop_conv_launches\": " << loop_conv_launches
      << ",\n  \"loop_depthwise_launches\": " << loop_dw_launches
      << ",\n  \"output_bytes\": " << output_bytes << ",\n  \"memory_drained\": true"
      << ",\n  \"first_ar_cycle\": " << first_ar << ",\n  \"first_r_cycle\": " << first_r
      << ",\n  \"last_r_cycle\": " << last_r << ",\n  \"first_aw_cycle\": " << first_aw
      << ",\n  \"first_w_cycle\": " << first_w << ",\n  \"last_w_cycle\": " << last_w
      << ",\n  \"last_b_cycle\": " << last_b
      << ",\n  \"first_launch_cycle\": " << first_launch
      << ",\n  \"launch_to_complete_cycles\": " << (first_launch >= 0 ? int64_t(elapsed)-first_launch : -1)
      << ",\n  \"read_beat_interval\": " << read_interval
      << ",\n  \"memory_response_mode\": \"" << (request_deadline ? "request_deadline" : "queued_pop_fill") << '"'
      << ",\n  \"read_latency_cycles\": " << read_latency
      << ",\n  \"inter_burst_gap_cycles\": " << inter_burst_gap
      << ",\n  \"read_outstanding_limit\": " << (request_deadline ? read_outstanding_limit : 16)
      << ",\n  \"read_latency_min\": " << (read_first_responses ? int64_t(read_latency_min) : -1)
      << ",\n  \"read_latency_max\": " << (read_first_responses ? int64_t(read_latency_max) : -1)
      << ",\n  \"read_latency_sum\": " << read_latency_sum
      << ",\n  \"read_first_responses\": " << read_first_responses
      << ",\n  \"first_read_queue_delay_sum_cycles\": " << first_read_queue_delay_sum
      << ",\n  \"first_read_queue_delay_max_cycles\": " << first_read_queue_delay_max
      << ",\n  \"first_read_backpressure_sum_cycles\": " << first_read_backpressure_sum
      << ",\n  \"first_read_backpressure_max_cycles\": " << first_read_backpressure_max
      << ",\n  \"matured_request_switch_gap_min\": " << (matured_switches ? int64_t(matured_switch_gap_min) : -1)
      << ",\n  \"matured_request_switch_gap_max\": " << (matured_switches ? int64_t(matured_switch_gap_max) : -1)
      << ",\n  \"matured_request_switches\": " << matured_switches
      << ",\n  \"consecutive_burst_transitions\": " << consecutive_burst_transitions
      << "\n}\n";
    model.final();
    if (mismatches || outside_output_mismatches) return 1;
    std::cout << "GEMMINI_COMPARE_PASS cycles=" << elapsed << " read_bytes=" << read_bytes
      << " write_bytes=" << write_bytes << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 2;
  }
}
