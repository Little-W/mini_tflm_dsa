// 使用固定 Coral VME RTL 执行共同 GEMM，并按每周期服务字节数检查外部存储。
#include "axi_byte_service.hpp"
#include "VVmeCoreMiniAxi.h"
#include "VVmeCoreMiniAxi___024root.h"
#include "hdl/verilog/sram_backdoor.h"
#include "verilated.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <elf.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace coral_fairness;
constexpr uint32_t kControl = 0x10000;

VerilatedContext *PrepareContext(VerilatedContext &context) {
  context.threads(1);
  return &context;
}

std::vector<uint8_t> ReadFile(const std::filesystem::path &path) {
  std::ifstream stream(path, std::ios::binary);
  Require(stream.good(), "Cannot open " + path.string());
  return {std::istreambuf_iterator<char>(stream),
          std::istreambuf_iterator<char>()};
}

void WriteFile(const std::filesystem::path &path,
               const std::vector<uint8_t> &bytes) {
  std::ofstream stream(path, std::ios::binary);
  stream.write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
  Require(stream.good(), "Cannot write " + path.string());
}

class Simulation : public AxiByteService {
public:
  VerilatedContext context;
  VVmeCoreMiniAxi core;
  uint64_t cycles = 0, launch_cycle = 0, launch_response_cycle = 0;
  uint64_t vme_pe_command_handshakes = 0;
  uint64_t first_vme_pe_command_cycle = 0, last_vme_pe_command_cycle = 0;

  explicit Simulation(uint32_t read_latency, uint32_t bytes_per_cycle)
      : AxiByteService(bytes_per_cycle, read_latency), core(PrepareContext(context)) {
    core.io_aclk = 0;
    core.io_aresetn = 0;
    core.io_te = 0;
    core.io_boot_addr = 0;
    core.io_irq = 0;
    core.io_timer_irq = 0;
    core.io_software_irq = 0;
    core.io_dm_req_valid = 0;
    core.io_dm_req_bits_address = 0;
    core.io_dm_req_bits_data = 0;
    core.io_dm_req_bits_op = 0;
    core.io_dm_rsp_ready = 1;
    core.io_axi_slave_write_addr_valid = 0;
    core.io_axi_slave_write_data_valid = 0;
    core.io_axi_slave_write_resp_ready = 1;
    core.io_axi_slave_read_addr_valid = 0;
    core.io_axi_slave_read_data_ready = 1;
    core.io_axi_master_read_data_valid = 0;
    core.io_axi_master_write_resp_valid = 0;
    core.io_axi_master_read_addr_ready = 0;
    core.io_axi_master_write_addr_ready = 0;
    core.io_axi_master_write_data_ready = 0;
    core.eval();
    for (int i = 0; i < 8; ++i)
      Tick();
    core.io_aresetn = 1;
    for (int i = 0; i < 8; ++i)
      Tick();
    sram_clear();
  }

  ~Simulation() { core.final(); }

  void Tick(bool *slave_aw = nullptr, bool *slave_w = nullptr,
            bool *slave_b = nullptr, uint32_t *slave_bresp = nullptr) {
    const uint64_t edge = cycles + 1;
    const auto output = Begin(edge);
    core.io_aclk = 0;
    core.io_axi_master_read_addr_ready = output.read_address_ready;
    core.io_axi_master_write_addr_ready = output.write_address_ready;
    core.io_axi_master_write_data_ready = output.write_ready;
    core.io_axi_master_read_data_valid = output.read_valid;
    core.io_axi_master_read_data_bits_resp = 0;
    if (output.read_valid) {
      for (int word = 0; word < 4; ++word) {
        uint32_t value;
        std::memcpy(&value, output.read_data.data() + word * 4, sizeof(value));
        core.io_axi_master_read_data_bits_data[word] = value;
      }
      core.io_axi_master_read_data_bits_id = output.read_id;
      core.io_axi_master_read_data_bits_last = output.read_last;
    }
    core.io_axi_master_write_resp_valid = output.response_valid;
    core.io_axi_master_write_resp_bits_resp = 0;
    if (output.response_valid) core.io_axi_master_write_resp_bits_id = output.response_id;
    core.eval();
    auto write_data = [&]() {
      WriteData value;
      value.valid = core.io_axi_master_write_data_valid;
      value.strobe = core.io_axi_master_write_data_bits_strb;
      value.last = core.io_axi_master_write_data_bits_last;
      for (int word = 0; word < 4; ++word) {
        const uint32_t data = core.io_axi_master_write_data_bits_data[word];
        std::memcpy(value.data.data() + word * 4, &data, sizeof(data));
      }
      return value;
    };
    core.io_axi_master_write_data_ready = PrepareWrite(write_data());
    core.eval();
    Inputs input;
    input.read = {bool(core.io_axi_master_read_addr_valid),
        core.io_axi_master_read_addr_bits_addr, core.io_axi_master_read_addr_bits_id,
        uint32_t(core.io_axi_master_read_addr_bits_len) + 1,
        core.io_axi_master_read_addr_bits_size, core.io_axi_master_read_addr_bits_burst};
    input.write = {bool(core.io_axi_master_write_addr_valid),
        core.io_axi_master_write_addr_bits_addr, core.io_axi_master_write_addr_bits_id,
        uint32_t(core.io_axi_master_write_addr_bits_len) + 1,
        core.io_axi_master_write_addr_bits_size, core.io_axi_master_write_addr_bits_burst};
    input.data = write_data();
    input.read_ready = core.io_axi_master_read_data_ready;
    input.response_ready = core.io_axi_master_write_resp_ready;
    const uint32_t pe_valid = core.rootp
        ->VmeCoreMiniAxi__DOT__core__DOT__rvvCore__DOT__rvvCoreWrapper__DOT__core__DOT__backend__DOT__vme__DOT__zvtPeArray__DOT__peCmdVld;
    const uint32_t pe_ready = core.rootp
        ->VmeCoreMiniAxi__DOT__core__DOT__rvvCore__DOT__rvvCoreWrapper__DOT__core__DOT__backend__DOT__vme__DOT__zvtPeArray__DOT__peCmdRdy;
    const bool pe_command = launch_cycle != 0 && !core.io_halted &&
                            ((pe_valid & pe_ready & 15u) == 15u);
    if (slave_aw) *slave_aw = core.io_axi_slave_write_addr_valid && core.io_axi_slave_write_addr_ready;
    if (slave_w) *slave_w = core.io_axi_slave_write_data_valid && core.io_axi_slave_write_data_ready;
    if (slave_b) *slave_b = core.io_axi_slave_write_resp_valid && core.io_axi_slave_write_resp_ready;
    if (slave_bresp) *slave_bresp = core.io_axi_slave_write_resp_bits_resp;

    context.timeInc(1);
    core.io_aclk = 1;
    core.eval();
    cycles = edge;
    if (pe_command) {
      ++vme_pe_command_handshakes;
      if (!first_vme_pe_command_cycle) first_vme_pe_command_cycle = edge;
      last_vme_pe_command_cycle = edge;
    }
    Commit(input);
    context.timeInc(1);
    core.io_aclk = 0;
    core.eval();
    Require(!context.gotFinish(), "RTL terminated before benchmark completion");
  }

  void WriteWord(uint32_t address, uint32_t value, bool launch = false) {
    core.io_axi_slave_write_addr_bits_addr = address;
    core.io_axi_slave_write_addr_bits_id = 0;
    core.io_axi_slave_write_addr_bits_len = 0;
    core.io_axi_slave_write_addr_bits_size = 2;
    core.io_axi_slave_write_addr_bits_burst = 1;
    core.io_axi_slave_write_addr_bits_prot = 0;
    core.io_axi_slave_write_addr_bits_lock = 0;
    core.io_axi_slave_write_addr_bits_cache = 0;
    core.io_axi_slave_write_addr_bits_qos = 0;
    core.io_axi_slave_write_addr_bits_region = 0;
    for (int word = 0; word < 4; ++word)
      core.io_axi_slave_write_data_bits_data[word] = 0;
    core.io_axi_slave_write_data_bits_data[(address & 15) / 4] = value;
    core.io_axi_slave_write_data_bits_strb = 15u << (address & 15);
    core.io_axi_slave_write_data_bits_last = 1;
    core.io_axi_slave_write_addr_valid = 1;
    core.io_axi_slave_write_data_valid = 1;
    bool aw_done = false, w_done = false, b_done = false;
    for (int i = 0; i < 1000 && !b_done; ++i) {
      bool aw = false, w = false, b = false;
      uint32_t response = 0;
      Tick(&aw, &w, &b, &response);
      if (aw)
        aw_done = true;
      if (w) {
        w_done = true;
        if (launch)
          launch_cycle = cycles;
      }
      if (b) {
        Require(response == 0, "AXI CSR write response " +
                                   std::to_string(response) + " at address " +
                                   std::to_string(address));
        b_done = true;
        if (launch)
          launch_response_cycle = cycles;
      }
      core.io_axi_slave_write_addr_valid = !aw_done;
      core.io_axi_slave_write_data_valid = !w_done;
    }
    Require(aw_done && w_done && b_done, "AXI CSR write timed out");
  }

  bool Drained() const {
    return DrainedService() &&
           !core.io_axi_master_read_addr_valid &&
           !core.io_axi_master_write_addr_valid &&
           !core.io_axi_master_write_data_valid;
  }
};

std::map<uint64_t, std::vector<uint8_t>>
ReadSramDump(const std::filesystem::path &path) {
  std::ifstream stream(path, std::ios::binary);
  std::map<uint64_t, std::vector<uint8_t>> memories;
  uint64_t address;
  uint32_t bytes;
  while (stream.read(reinterpret_cast<char *>(&address), sizeof(address))) {
    Require(bool(stream.read(reinterpret_cast<char *>(&bytes), sizeof(bytes))),
            "Truncated SRAM dump");
    std::vector<uint8_t> data(bytes);
    Require(bool(stream.read(reinterpret_cast<char *>(data.data()), bytes)),
            "Truncated SRAM data");
    memories.emplace(address, std::move(data));
  }
  return memories;
}

std::vector<uint8_t>
ReadSram(const std::map<uint64_t, std::vector<uint8_t>> &memories,
         uint32_t address, uint32_t bytes) {
  std::vector<uint8_t> result(bytes);
  for (uint32_t i = 0; i < bytes; ++i) {
    bool found = false;
    for (const auto &[base, data] : memories) {
      if (address + i >= base && address + i < base + data.size()) {
        result[i] = data[address + i - base];
        found = true;
        break;
      }
    }
    Require(found, "SRAM output address was not registered");
  }
  return result;
}
} // namespace

int main(int argc, char **argv) {
  try {
    Require(argc >= 3 && argc <= 5,
            "Usage: coral_axi_benchmark ELF CASE_DIR [READ_LATENCY] [SERVICE_BYTES]");
    const std::filesystem::path elf_path(argv[1]);
    const std::filesystem::path directory(argv[2]);
    const uint32_t latency = argc >= 4 ? std::stoul(argv[3]) : 8;
    const uint32_t service_bytes = argc == 5 ? std::stoul(argv[4]) : 8;
    const auto elf = ReadFile(elf_path);
    Require(elf.size() >= sizeof(Elf32_Ehdr), "ELF header is truncated");
    const auto *header = reinterpret_cast<const Elf32_Ehdr *>(elf.data());
    Require(header->e_ident[EI_CLASS] == ELFCLASS32 &&
                header->e_machine == EM_RISCV,
            "Expected a 32-bit RISC-V ELF");
    uint32_t m, n, k, mp, npad, kp, data_base, output_address, data_bytes;
    std::ifstream setup(directory / "setup.txt");
    Require(bool(setup >> m >> n >> k >> mp >> npad >> kp >> data_base >>
                 output_address >> data_bytes),
            "Invalid case setup");
    auto image = ReadFile(directory / "memory.bin");
    auto control = ReadFile(directory / "control.bin");
    auto expected = ReadFile(directory / "expected_padded.bin");
    Require(image.size() == data_bytes && control.size() == 64 &&
                expected.size() == mp * npad,
            "Invalid input file size");
    Simulation simulation(latency, service_bytes);
    sram_load_elf(elf_path.c_str());
    Require(sram_backdoor_load_c(kControl, control.data(), control.size()),
            "Cannot load control");
    if (data_base >= kRamBase) {
      Require(uint64_t(data_base - kRamBase) + image.size() <=
                  simulation.memory.size(),
              "Input image exceeds RAM");
      std::copy(image.begin(), image.end(),
                simulation.memory.begin() + (data_base - kRamBase));
      simulation.output_begin = output_address;
      simulation.output_end = output_address + mp * npad;
    } else {
      Require(data_base >= 0x10100 && data_base + image.size() <= 0x17800,
              "Input image exceeds standard DTCM");
      Require(sram_backdoor_load_c(data_base, image.data(), image.size()),
              "Cannot load DTCM inputs");
    }
    const auto initial_memory = simulation.memory;
    simulation.WriteWord(0x30004, header->e_entry);
    simulation.WriteWord(0x30000, 1);
    simulation.WriteWord(0x30000, 0, true);
    uint64_t halt_cycle = 0;
    for (uint64_t i = 0; i < 100000000; ++i) {
      if (simulation.core.io_halted || simulation.core.io_fault) {
        if (halt_cycle == 0)
          halt_cycle = simulation.cycles;
        if (simulation.Drained())
          break;
      }
      simulation.Tick();
    }
    const uint64_t drained_cycle = simulation.cycles;
    const auto dump_path = directory / "sram_dump.bin";
    Require(sram_backdoor_dump_memory(dump_path.c_str()) == 0,
            "Cannot dump SRAM");
    const auto srams = ReadSramDump(dump_path);
    auto completed = ReadSram(srams, kControl, 64);
    std::array<uint32_t, 16> words{};
    std::memcpy(words.data(), completed.data(), completed.size());
    WriteFile(directory / "control_after.bin", completed);
    if (simulation.core.io_fault || words[8] == 3) {
      std::cerr << "Core fault: mcause=" << words[12] << " mepc=" << words[13]
                << " mtval=" << words[14] << " status=" << words[8] << '\n';
    }
    Require(halt_cycle != 0 && simulation.Drained(),
            "Benchmark did not finish");
    Require(!simulation.core.io_fault && words[8] == 2,
            "Benchmark execution failed");
    Require(words[11] == (mp / 16) * (npad / 16) * (kp / 4),
            "Matrix instruction count mismatch");
    Require(simulation.vme_pe_command_handshakes > 0,
            "No VME PE command was accepted");
    std::vector<uint8_t> padded;
    if (data_base >= kRamBase) {
      const uint32_t offset = output_address - kRamBase;
      padded.assign(simulation.memory.begin() + offset,
                    simulation.memory.begin() + offset + mp * npad);
      for (size_t i = 0; i < simulation.memory.size(); ++i) {
        if (i >= offset && i < offset + mp * npad)
          continue;
        Require(simulation.memory[i] == initial_memory[i],
                "RAM changed outside output tensor");
      }
    } else {
      padded = ReadSram(srams, output_address, mp * npad);
      Require(simulation.read_requests == 0 && simulation.write_requests == 0,
              "TCM execution unexpectedly used external RAM");
    }
    WriteFile(directory / "actual_padded.bin", padded);
    uint64_t mismatches = 0;
    for (size_t i = 0; i < padded.size(); ++i) {
      if (padded[i] != expected[i]) {
        if (mismatches < 12)
          std::cerr << "Mismatch " << i << ": actual=" << int(int8_t(padded[i]))
                    << " expected=" << int(int8_t(expected[i])) << '\n';
        ++mismatches;
      }
    }
    std::vector<uint8_t> actual;
    for (uint32_t row = 0; row < m; ++row)
      actual.insert(actual.end(), padded.begin() + row * npad,
                    padded.begin() + row * npad + n);
    WriteFile(directory / "actual.bin", actual);
    for (int i = 0; i < 32; ++i) {
      simulation.Tick();
      Require(simulation.Drained(), "Traffic continued after completion");
    }
    simulation.CheckComplete();
    const uint64_t min_latency =
        simulation.read_requests ? simulation.min_first_read_latency : 0;
    std::cout
        << "{\"passed\":" << (mismatches == 0 ? "true" : "false")
        << ",\"mismatches\":" << mismatches << ",\"m\":" << m << ",\"n\":" << n
        << ",\"k\":" << k
        << ",\"bus_width_bits\":128,\"physical_memory_bytes\":" << kRamBytes
        << ",\"launch_accept_cycle\":" << simulation.launch_cycle
        << ",\"launch_response_cycle\":" << simulation.launch_response_cycle
        << ",\"halt_cycle\":" << halt_cycle
        << ",\"drained_cycle\":" << drained_cycle
        << ",\"drained_cycles\":" << drained_cycle - simulation.launch_cycle
        << ",\"kernel_start_mcycle\":" << words[9]
        << ",\"kernel_end_mcycle\":" << words[10]
        << ",\"kernel_cycles\":" << uint32_t(words[10] - words[9])
        << ",\"expected_matrix_instructions\":" << words[11]
        << ",\"vme_pe_command_handshakes\":"
        << simulation.vme_pe_command_handshakes
        << ",\"first_vme_pe_command_cycle\":"
        << simulation.first_vme_pe_command_cycle
        << ",\"last_vme_pe_command_cycle\":"
        << simulation.last_vme_pe_command_cycle
        << ",\"first_ar_cycle\":" << simulation.first_ar_cycle
        << ",\"last_r_cycle\":" << simulation.last_r_cycle
        << ",\"last_aw_cycle\":" << simulation.last_aw_cycle
        << ",\"last_w_cycle\":" << simulation.last_w_cycle
        << ",\"last_b_cycle\":" << simulation.last_b_cycle
        << ",\"read_beats\":" << simulation.read_beats
        << ",\"write_beats\":" << simulation.write_beats
        << ",\"read_requests\":" << simulation.read_requests
        << ",\"write_requests\":" << simulation.write_requests
        << ",\"read_requested_bytes\":" << simulation.read_requested_bytes
        << ",\"write_requested_bytes\":" << simulation.write_requested_bytes
        << ",\"written_bytes\":" << simulation.bytes_written
        << ",\"max_read_outstanding\":" << simulation.max_read_outstanding
        << ",\"max_write_outstanding\":" << simulation.max_write_outstanding
        << ",\"max_read_burst_beats\":" << simulation.max_read_burst
        << ",\"max_write_burst_beats\":" << simulation.max_write_burst
        << ",\"first_read_latency_min\":" << min_latency
        << ",\"first_read_latency_max\":" << simulation.max_first_read_latency
        << ",\"output_elements\":" << m * n
        << ",\"padded_output_elements\":" << mp * npad
        << ",\"physical_axi_bits\":128,\"effective_service_bits\":" << service_bytes * 8
        << ",\"read_service_bytes\":" << simulation.read_service.bytes
        << ",\"write_service_bytes\":" << simulation.write_service.bytes
        << ",\"read_service_cycles\":" << simulation.read_service.cycles
        << ",\"write_service_cycles\":" << simulation.write_service.cycles
        << ",\"read_service_max_bytes_per_cycle\":" << simulation.read_service.max_bytes_per_cycle
        << ",\"write_service_max_bytes_per_cycle\":" << simulation.write_service.max_bytes_per_cycle
        << ",\"read_full_beat_min_interval\":" << simulation.read_service.FullInterval()
        << ",\"write_full_beat_min_interval\":" << simulation.write_service.FullInterval()
        << ",\"first_read_service_latency_min\":"
        << (simulation.read_requests ? simulation.min_first_read_service_latency : 0)
        << ",\"first_full_read_latency_min\":"
        << (simulation.read_service.full_beats ? simulation.min_first_full_read_latency : 0)
        << ",\"first_read_service_cycle\":" << simulation.read_service.first_cycle
        << ",\"last_read_service_cycle\":" << simulation.read_service.last_cycle
        << ",\"last_write_service_cycle\":" << simulation.write_service.last_cycle
        << ",\"read_backpressure_cycles\":" << simulation.read_backpressure_cycles
        << ",\"write_partial_cycles\":" << simulation.write_partial_cycles
        << ",\"simultaneous_service_cycles\":" << simulation.simultaneous_service_cycles
        << ",\"read_full_beats\":" << simulation.read_service.full_beats
        << ",\"write_full_beats\":" << simulation.write_service.full_beats
        << ",\"memory_drained\":true,\"partial_services_pending\":false}\n";
    return mismatches == 0 ? 0 : 1;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
