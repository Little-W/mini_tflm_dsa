#include "axi_byte_service.hpp"

#include <iostream>
#include <utility>

using namespace coral_fairness;

namespace {
int cases = 0;

Outputs Step(AxiByteService &service, uint64_t cycle, const Inputs &input) {
  auto output = service.Begin(cycle);
  output.write_ready = service.PrepareWrite(input.data);
  service.Commit(input);
  return output;
}

WriteData Data(uint8_t seed, bool last, uint16_t strobe = 0xffff) {
  WriteData result;
  result.valid = true;
  result.strobe = strobe;
  result.last = last;
  for (unsigned i = 0; i < 16; ++i) result.data[i] = uint8_t(seed + i * 7);
  return result;
}

void Sizes(uint32_t width, uint32_t size) {
  AxiByteService service(width, 8);
  for (unsigned i = 0; i < 512; ++i) service.memory[i] = uint8_t(i * 13 + 3);
  const auto initial = service.memory;
  const uint32_t bytes = 1u << size;
  const uint32_t offset = 16 - bytes;
  const uint32_t read_address = kRamBase + offset;
  const uint32_t write_address = kRamBase + 0x100 + offset;
  const auto data = Data(91, true, uint16_t(((1u << bytes) - 1) << offset));
  Inputs input;
  input.read = {true, read_address, 2, 1, size, 1};
  input.write = {true, write_address, 4, 1, size, 1};
  Step(service, 1, input);
  uint64_t read_cycle = 0, write_cycle = 0;
  for (uint64_t cycle = 2; cycle <= 16; ++cycle) {
    input = {};
    input.read_ready = input.response_ready = true;
    if (!write_cycle) input.data = data;
    const auto output = Step(service, cycle, input);
    if (input.data.valid && output.write_ready) write_cycle = cycle;
    if (output.read_valid) {
      Require(!read_cycle, "Read response repeated");
      read_cycle = cycle;
      Require(output.read_id == 2 && output.read_last, "Read response metadata mismatch");
      for (unsigned i = 0; i < bytes; ++i)
        Require(output.read_data[offset + i] == initial[offset + i], "Read lane mismatch");
    }
  }
  const uint32_t steps = (bytes + width - 1) / width;
  Require(read_cycle == 8 + steps && write_cycle == 1 + steps,
          "Byte service produced an unexpected acceptance cycle");
  auto expected = initial;
  for (unsigned i = 0; i < bytes; ++i) expected[0x100 + offset + i] = data.data[offset + i];
  Require(service.memory == expected, "Transfer changed unexpected memory bytes");
  Require(service.read_service.cycles == steps && service.write_service.cycles == steps,
          "Transfer service count mismatch");
  service.CheckComplete();
  ++cases;
}

// 五个事务跨越四项名额限制，同时覆盖突发、写响应等待和读数据保持。
void QueuesAndBackpressure() {
  AxiByteService service(8, 8);
  for (unsigned i = 0; i < 0x600; ++i) service.memory[i] = uint8_t(i * 11 + 5);
  const auto initial = service.memory;
  auto expected = initial;
  unsigned read_offered = 0, write_offered = 0, read_accepted = 0, write_accepted = 0;
  unsigned write_responses = 0;
  bool stalled = false, saw_full_read_queue = false, saw_full_write_queue = false;
  Outputs held;
  for (uint64_t cycle = 1; cycle <= 160; ++cycle) {
    Inputs input;
    if (read_offered < 5)
      input.read = {true, kRamBase + read_offered * 0x40, read_offered + 10, 2, 4, 1};
    if (write_offered < 5)
      input.write = {true, kRamBase + 0x400 + write_offered * 0x40, write_offered + 20, 2, 4, 1};
    input.read_ready = cycle >= 16;
    input.response_ready = cycle >= 32;
    if (cycle >= 8 && write_accepted < 10)
      input.data = Data(uint8_t(73 + write_accepted), write_accepted % 2 == 1, 0xaa55);
    const auto output = Step(service, cycle, input);
    if (stalled)
      Require(output.read_valid && output.read_data == held.read_data &&
                  output.read_id == held.read_id && output.read_last == held.read_last,
              "Read payload changed while waiting for acceptance");
    stalled = output.read_valid && !input.read_ready;
    held = output;
    if (input.read.valid && output.read_address_ready) ++read_offered;
    if (input.write.valid && output.write_address_ready) ++write_offered;
    saw_full_read_queue |= input.read.valid && !output.read_address_ready;
    saw_full_write_queue |= input.write.valid && !output.write_address_ready;
    if (output.read_valid && input.read_ready) {
      Require(output.read_id == 10 + read_accepted / 2 &&
                  output.read_last == (read_accepted % 2 == 1), "Read ordering mismatch");
      const unsigned offset = (read_accepted / 2) * 0x40 + (read_accepted % 2) * 16;
      for (unsigned i = 0; i < 16; ++i)
        Require(output.read_data[i] == initial[offset + i], "Burst read data mismatch");
      ++read_accepted;
    }
    if (input.data.valid && output.write_ready) {
      const unsigned offset = 0x400 + (write_accepted / 2) * 0x40 + (write_accepted % 2) * 16;
      for (unsigned i = 0; i < 16; ++i)
        if (input.data.strobe & (1u << i)) expected[offset + i] = input.data.data[i];
      ++write_accepted;
    }
    if (output.response_valid && input.response_ready) {
      Require(output.response_id == 20 + write_responses, "Write response ordering mismatch");
      ++write_responses;
    }
  }
  Require(read_accepted == 10 && write_accepted == 10 && write_responses == 5,
          "Queued transactions were not completed");
  Require(saw_full_read_queue && saw_full_write_queue && service.max_read_outstanding == 4 &&
              service.max_write_outstanding == 4, "Queue capacity was not exercised");
  Require(service.simultaneous_service_cycles > 0 && service.read_backpressure_cycles > 0 &&
              service.write_partial_cycles == 10, "Service overlap or backpressure was not exercised");
  Require(service.memory == expected, "Masked write changed unexpected memory bytes");
  service.CheckComplete();
  ++cases;
}

void ReadSnapshotAndEarlyWriteData() {
  AxiByteService service(8, 8);
  for (unsigned i = 0; i < 16; ++i) service.memory[i] = uint8_t(i + 1);
  const auto original = service.memory;
  const auto replacement = Data(170, true);
  for (uint64_t cycle = 1; cycle <= 27; ++cycle) {
    Inputs input;
    if (cycle == 1 || cycle == 15) input.read = {true, kRamBase, 1, 1, 4, 1};
    if (cycle == 10) input.write = {true, kRamBase, 2, 1, 4, 1};
    if (cycle >= 9 && cycle <= 12) input.data = replacement;
    input.read_ready = cycle >= 14;
    input.response_ready = true;
    const auto output = Step(service, cycle, input);
    if (cycle == 9 || cycle == 10)
      Require(!output.write_ready, "Write data was accepted before its address or byte service");
    if (cycle >= 10 && cycle <= 14) {
      Require(output.read_valid, "Prepared read did not remain valid");
      for (unsigned i = 0; i < 16; ++i)
        Require(output.read_data[i] == original[i], "Held read data changed after a write");
    }
    if (cycle == 24)
      Require(output.read_valid && output.read_data == replacement.data,
              "Later read did not observe the completed write");
  }
  service.CheckComplete();
  ++cases;
}

void RejectUnstableWrite(unsigned field) {
  AxiByteService service(8, 8);
  Inputs input;
  input.write = {true, kRamBase, 1, 1, 4, 1};
  Step(service, 1, input);
  input = {};
  input.data = Data(17, true);
  Require(!Step(service, 2, input).write_ready, "Partial write was accepted");
  if (field == 0) input.data.valid = false;
  if (field == 1) input.data.data[15] ^= 1;
  if (field == 2) input.data.strobe ^= 1;
  if (field == 3) input.data.last = false;
  bool rejected = false;
  try { Step(service, 3, input); }
  catch (const std::runtime_error &error) {
    rejected = std::string(error.what()).find("changed during a partial byte service") != std::string::npos;
  }
  Require(rejected, "An unstable partial write was accepted");
  ++cases;
}
}  // namespace

int main() {
  try {
    for (auto width : {8u, 16u}) for (unsigned size = 0; size <= 4; ++size) Sizes(width, size);
    QueuesAndBackpressure();
    ReadSnapshotAndEarlyWriteData();
    for (unsigned field = 0; field < 4; ++field) RejectUnstableWrite(field);
    std::cout << "AXI_BYTE_SERVICE_PASS cases=" << cases << '\n';
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
