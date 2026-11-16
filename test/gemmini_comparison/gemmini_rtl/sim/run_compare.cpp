#include "VGemminiCompare.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Command { bool fence; unsigned funct; uint64_t rs1, rs2; };
struct ReadRequest {
  unsigned id, size, beats;
  uint64_t address;
};

static std::vector<uint8_t> load(const std::string& path) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) throw std::runtime_error("Cannot read " + path);
  return std::vector<uint8_t>(std::istreambuf_iterator<char>(stream), {});
}

int main(int argc, char** argv) {
  try {
    if (argc != 10) throw std::runtime_error(
      "Usage: simulator memory.bin memory_base commands.txt output_base output_bytes expected.bin timed_start result.json read_interval");
    VerilatedContext context;
    context.commandArgs(argc, argv);
    VGemminiCompare model(&context);
    const uint64_t memory_base = std::stoull(argv[2], nullptr, 0);
    const uint64_t output_base = std::stoull(argv[4], nullptr, 0);
    const size_t output_bytes = std::stoull(argv[5], nullptr, 0);
    const size_t timed_start = std::stoull(argv[7], nullptr, 0);
    const unsigned read_interval = std::stoul(argv[9], nullptr, 0);
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
    if (read_interval < 2) throw std::runtime_error("Read beat interval must be at least 2");
    uint64_t cycle = 0, first_cycle = 0;
    uint64_t read_bytes = 0, write_bytes = 0, get_requests = 0, put_requests = 0;
    uint64_t max_read_burst_bytes = 0, max_write_burst_bytes = 0;
    uint64_t load_cycles = 0, execute_cycles = 0, store_cycles = 0, busy_cycles = 0;
    uint64_t im2col_cycles = 0, im2col_requests = 0, im2col_responses = 0;
    uint64_t loop_conv_launches = 0, loop_dw_launches = 0;
    int64_t first_ar = -1, first_r = -1, last_r = -1;
    int64_t first_aw = -1, first_w = -1, last_w = -1, last_b = -1;
    int64_t first_launch = -1;
    std::deque<ReadRequest> reads;
    ReadRequest current_read{};
    bool read_active = false, rvalid = false;
    uint32_t rdata = 0;
    uint64_t next_read_fill = 0;
    bool write_active = false, bvalid = false;
    unsigned write_left = 0, write_id = 0, write_size = 0;
    uint64_t write_address = 0;
    auto read_word = [&](uint64_t address, unsigned size) {
      uint32_t value = 0xa5a5a5a5;
      for (unsigned lane=0;lane<4;lane++) {
        if (lane < (address & 3) || lane >= (address & 3) + (1u << size)) continue;
        const auto byte = (address & ~uint64_t(3)) + lane;
        if (byte < memory_base || byte-memory_base >= memory.size())
          throw std::runtime_error("Read outside comparison memory");
        value = (value & ~(0xffu << (lane*8))) | (uint32_t(memory[byte-memory_base]) << (lane*8));
      }
      return value;
    };
    auto tick = [&](bool collect) {
      model.clock = 0;
      model.mem_ar_ready = !model.reset && reads.size() < 16;
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
        unsigned(model.mem_ar_bits_len) + 1, model.mem_ar_bits_addr};
      const unsigned new_read_burst = model.mem_ar_bits_burst;
      const unsigned new_write_id = model.mem_aw_bits_id;
      const unsigned new_write_size = model.mem_aw_bits_size;
      const unsigned new_write_left = unsigned(model.mem_aw_bits_len) + 1;
      const uint64_t new_write_address = model.mem_aw_bits_addr;
      const unsigned new_write_burst = model.mem_aw_bits_burst;
      const uint32_t write_data = model.mem_w_bits_data;
      const unsigned write_mask = model.mem_w_bits_strb;
      const bool write_last = model.mem_w_bits_last;
      if (collect) {
        if (command_fire && (model.command_funct == 8 || model.command_funct == 15) && first_launch < 0)
          first_launch = cycle-first_cycle;
        busy_cycles += model.busy;
        load_cycles += model.load_busy;
        execute_cycles += model.execute_busy;
        store_cycles += model.store_busy;
        im2col_cycles += model.im2col_active;
        im2col_requests += model.im2col_request_valid && model.im2col_request_ready;
        im2col_responses += model.im2col_response_valid && model.im2col_response_ready;
        if (command_fire && model.command_funct == 15) {
          loop_conv_launches++;
          loop_dw_launches += (model.command_rs1 >> 6) & 1;
        }
      }
      model.clock = 1;
      model.eval();
      context.timeInc(1);
      if (!model.reset) {
        if (fill) { rvalid = true; rdata = read_word(current_read.address, current_read.size); }
        if (r_fire) {
          rvalid = false;
          if (--current_read.beats == 0) read_active = false;
          else current_read.address = (current_read.address & ~((1ull << current_read.size)-1)) + (1ull << current_read.size);
          next_read_fill = cycle + read_interval - 1;
          if (collect) { if (first_r < 0) first_r = cycle-first_cycle; last_r = cycle-first_cycle; }
        }
        if (pop) {
          current_read = reads.front(); reads.pop_front(); read_active = true;
          next_read_fill = cycle+1;
        }
        if (ar_fire) {
          if (new_read.size > 2 || new_read_burst != 1)
            throw std::runtime_error("Unsupported AXI read burst");
          const uint64_t bytes = uint64_t(new_read.beats) << new_read.size;
          if ((new_read.address & 4095) + bytes > 4096)
            throw std::runtime_error("AXI read crosses 4 KiB");
          reads.push_back(new_read);
          if (collect) {
            get_requests++; read_bytes += bytes;
            max_read_burst_bytes = std::max(max_read_burst_bytes, bytes);
            if (first_ar < 0) first_ar = cycle-first_cycle;
          }
        }
        if (aw_fire) {
          if (new_write_size > 2 || new_write_burst != 1)
            throw std::runtime_error("Unsupported AXI write burst");
          if ((new_write_address & 4095) + (uint64_t(new_write_left) << new_write_size) > 4096)
            throw std::runtime_error("AXI write crosses 4 KiB");
          write_active = true; write_id = new_write_id; write_size = new_write_size;
          write_address = new_write_address; write_left = new_write_left;
          if (collect) {
            put_requests++; if (first_aw < 0) first_aw = cycle-first_cycle;
            max_write_burst_bytes = std::max(max_write_burst_bytes, uint64_t(new_write_left) << new_write_size);
          }
        }
        if (w_fire) {
          if (write_last != (write_left == 1)) throw std::runtime_error("Incorrect AXI WLAST");
          for (unsigned lane=0;lane<4;lane++) if (write_mask & (1u << lane)) {
            const uint64_t address = (write_address & ~uint64_t(3)) + lane;
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
          if (collect) last_b = cycle-first_cycle;
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
    if (!memory_drained) throw std::runtime_error("Comparison completed before all AXI responses drained");
    std::string observed_path = argv[8];
    if (observed_path.size() >= 5 && observed_path.substr(observed_path.size()-5) == ".json")
      observed_path.resize(observed_path.size()-5);
    observed_path += ".output.bin";
    std::ofstream observed(observed_path, std::ios::binary);
    observed.write(reinterpret_cast<const char*>(memory.data()+output_base-memory_base), output_bytes);
    if (!observed) throw std::runtime_error("Cannot save observed output");
    std::ofstream result(argv[8]);
    result << "{\n  \"passed\": " << (mismatches == 0 && outside_output_mismatches == 0 ? "true" : "false")
      << ",\n  \"cycles\": " << elapsed << ",\n  \"read_bytes\": " << read_bytes
      << ",\n  \"write_bytes\": " << write_bytes << ",\n  \"read_requests\": " << get_requests
      << ",\n  \"max_read_burst_bytes\": " << max_read_burst_bytes
      << ",\n  \"max_write_burst_bytes\": " << max_write_burst_bytes
      << ",\n  \"write_requests\": " << put_requests << ",\n  \"load_busy_cycles\": " << load_cycles
      << ",\n  \"execute_busy_cycles\": " << execute_cycles << ",\n  \"store_busy_cycles\": " << store_cycles
      << ",\n  \"busy_cycles\": " << busy_cycles << ",\n  \"output_mismatches\": " << mismatches
      << ",\n  \"outside_output_mismatches\": " << outside_output_mismatches
      << ",\n  \"independent_im2col_active_cycles\": " << im2col_cycles
      << ",\n  \"independent_im2col_requests\": " << im2col_requests
      << ",\n  \"independent_im2col_responses\": " << im2col_responses
      << ",\n  \"loop_conv_launches\": " << loop_conv_launches
      << ",\n  \"loop_depthwise_launches\": " << loop_dw_launches
      << ",\n  \"output_bytes\": " << output_bytes << ",\n  \"memory_drained\": true"
      << ",\n  \"first_ar_cycle\": " << first_ar << ",\n  \"first_r_cycle\": " << first_r
      << ",\n  \"last_r_cycle\": " << last_r << ",\n  \"first_aw_cycle\": " << first_aw
      << ",\n  \"first_w_cycle\": " << first_w << ",\n  \"last_w_cycle\": " << last_w
      << ",\n  \"last_b_cycle\": " << last_b
      << ",\n  \"first_launch_cycle\": " << first_launch
      << ",\n  \"launch_to_complete_cycles\": " << (first_launch >= 0 ? int64_t(elapsed)-first_launch : -1)
      << ",\n  \"read_beat_interval\": " << read_interval << "\n}\n";
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
