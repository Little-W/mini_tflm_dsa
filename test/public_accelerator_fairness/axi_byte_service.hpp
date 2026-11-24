#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace coral_fairness {

constexpr uint32_t kRamBase = 0x80000000;
constexpr uint32_t kRamBytes = 2 * 1024 * 1024;

inline void Require(bool condition, const std::string &message) {
  if (!condition) throw std::runtime_error(message);
}

struct Address {
  bool valid = false;
  uint32_t address = 0, id = 0, beats = 1, size = 4, burst = 1;
};

struct WriteData {
  bool valid = false;
  std::array<uint8_t, 16> data{};
  uint16_t strobe = 0;
  bool last = false;
};

struct Inputs {
  Address read, write;
  WriteData data;
  bool read_ready = false, response_ready = false;
};

struct Outputs {
  bool read_address_ready = false, write_address_ready = false;
  bool write_ready = false, read_valid = false, response_valid = false;
  std::array<uint8_t, 16> read_data{};
  uint32_t read_id = 0, response_id = 0;
  bool read_last = false;
};

struct Transaction {
  uint32_t address, id, beats, size, transferred = 0;
  uint64_t accepted, due;
};

struct Response {
  uint32_t id;
  uint64_t due;
};

struct ChannelService {
  uint64_t bytes = 0, cycles = 0, first_cycle = 0, last_cycle = 0;
  uint32_t max_bytes_per_cycle = 0;
  uint64_t full_beats = 0, last_full_beat_cycle = 0;
  uint64_t min_full_beat_interval = std::numeric_limits<uint64_t>::max();

  void Grant(uint64_t cycle, uint32_t count, uint32_t limit) {
    Require(count > 0 && count <= limit, "Invalid byte service grant");
    Require(last_cycle != cycle, "Two service grants in one direction and cycle");
    bytes += count;
    ++cycles;
    if (!first_cycle) first_cycle = cycle;
    last_cycle = cycle;
    max_bytes_per_cycle = std::max(max_bytes_per_cycle, count);
  }

  void Accept(uint64_t cycle, uint32_t beat_bytes) {
    if (beat_bytes != 16) return;
    if (full_beats)
      min_full_beat_interval = std::min(min_full_beat_interval,
                                      cycle - last_full_beat_cycle);
    last_full_beat_cycle = cycle;
    ++full_beats;
  }

  uint64_t FullInterval() const {
    return full_beats > 1 ? min_full_beat_interval : 0;
  }
};

// 读写方向独立服务。每个周期最多处理指定字节数，完整数据拍再进行 AXI 握手。
class AxiByteService {
public:
  std::vector<uint8_t> memory = std::vector<uint8_t>(kRamBytes, 0);
  std::deque<Transaction> reads, writes;
  std::deque<Response> responses;
  ChannelService read_service, write_service;
  uint32_t service_bytes, latency;
  uint32_t output_begin = kRamBase, output_end = kRamBase + kRamBytes;
  uint64_t first_ar_cycle = 0, last_r_cycle = 0, last_aw_cycle = 0;
  uint64_t last_w_cycle = 0, last_b_cycle = 0;
  uint64_t read_beats = 0, write_beats = 0, read_requests = 0, write_requests = 0;
  uint64_t read_requested_bytes = 0, write_requested_bytes = 0, bytes_written = 0;
  uint32_t max_read_outstanding = 0, max_write_outstanding = 0;
  uint32_t max_read_burst = 0, max_write_burst = 0;
  uint64_t min_first_read_latency = std::numeric_limits<uint64_t>::max();
  uint64_t max_first_read_latency = 0;
  uint64_t min_first_full_read_latency = std::numeric_limits<uint64_t>::max();
  uint64_t min_first_read_service_latency = std::numeric_limits<uint64_t>::max();
  uint64_t read_backpressure_cycles = 0, write_partial_cycles = 0;
  uint64_t simultaneous_service_cycles = 0;
  std::array<uint64_t, 5> read_beats_by_size{}, write_beats_by_size{};

  AxiByteService(uint32_t bytes, uint32_t read_latency)
      : service_bytes(bytes), latency(read_latency) {
    Require(bytes == 8 || bytes == 16, "Service width must be 8 or 16 bytes");
    Require(read_latency >= 1, "First read latency must be positive");
  }

  void CheckAddress(const Address &address) const {
    Require(address.size <= 4, "AXI transfer exceeds 128 bits");
    Require(address.beats >= 1 && address.beats <= 256, "Invalid AXI burst length");
    Require(address.burst == 1, "Expected AXI INCR transfer");
    Require((address.address & ((1u << address.size) - 1)) == 0,
            "AXI transfer is unaligned");
    const uint64_t end = uint64_t(address.address) +
                         (uint64_t(address.beats) << address.size);
    Require(address.address >= kRamBase && end <= uint64_t(kRamBase) + kRamBytes,
            "External RAM access is out of bounds");
    Require((address.address >> 12) == ((end - 1) >> 12), "AXI burst crosses 4 KiB");
  }

  // 每周期先准备读响应及地址接收条件，再采样写通道并准备写接收条件。
  Outputs Begin(uint64_t cycle) {
    Require(cycle > edge_, "Memory service cycles must increase");
    edge_ = cycle;
    write_grant_ = 0;
    prepared_write_ = false;
    Outputs result;
    result.read_address_ready = reads.size() < 4;
    result.write_address_ready = writes.size() + responses.size() < 4;
    if (!writes.empty())
      result.write_ready = (1u << writes.front().size) - write_progress_ <= service_bytes;
    if (!reads.empty() && reads.front().due <= cycle) {
      const auto &request = reads.front();
      const uint32_t count = 1u << request.size;
      const uint32_t address = request.address + (request.transferred << request.size);
      if (read_progress_ < count) {
        if (read_progress_ == 0) {
          read_data_.fill(0);
          if (request.transferred == 0)
            min_first_read_service_latency = std::min(min_first_read_service_latency,
                                                      cycle - request.accepted);
        }
        const uint32_t grant = std::min(service_bytes, count - read_progress_);
        for (uint32_t byte = 0; byte < grant; ++byte)
          read_data_[(address & 15) + read_progress_ + byte] =
              memory[address - kRamBase + read_progress_ + byte];
        read_progress_ += grant;
        read_service.Grant(cycle, grant, service_bytes);
      }
      result.read_valid = read_progress_ == count;
      result.read_data = read_data_;
      result.read_id = request.id;
      result.read_last = request.transferred + 1 == request.beats;
    }
    result.response_valid = !responses.empty() && responses.front().due <= cycle;
    if (result.response_valid) result.response_id = responses.front().id;
    outputs_ = result;
    return result;
  }

  bool PrepareWrite(const WriteData &data) {
    Require(!prepared_write_, "Write service prepared twice in one cycle");
    prepared_write_ = true;
    if (write_progress_ != 0) CheckHeldWrite(data);
    if (writes.empty() || !data.valid) return outputs_.write_ready;
    const auto &request = writes.front();
    Require(edge_ > request.accepted, "AXI W precedes registered AW");
    const uint32_t count = 1u << request.size;
    const uint32_t address = request.address + (request.transferred << request.size);
    const uint32_t lane_mask = ((1u << count) - 1) << (address & 15);
    Require((uint32_t(data.strobe) & ~lane_mask) == 0, "WSTRB exceeds the transfer lanes");
    Require(data.last == (request.transferred + 1 == request.beats), "Incorrect AXI WLAST");
    if (write_progress_ == 0) held_write_ = data;
    write_offset_ = write_progress_;
    write_grant_ = std::min(service_bytes, count - write_progress_);
    outputs_.write_ready = write_progress_ + write_grant_ == count;
    return outputs_.write_ready;
  }

  // 写数据在各次字节服务边沿保存；完整拍接收后才推进事务并生成写响应。
  void Commit(const Inputs &input) {
    Require(prepared_write_, "Write service was not prepared");
    if (write_grant_) CheckHeldWrite(input.data);
    const bool read_accept = outputs_.read_valid && input.read_ready;
    const bool write_accept = outputs_.write_ready && input.data.valid;
    const bool response_accept = outputs_.response_valid && input.response_ready;
    const bool ar = outputs_.read_address_ready && input.read.valid;
    const bool aw = outputs_.write_address_ready && input.write.valid;
    if (ar) CheckAddress(input.read);
    if (aw) CheckAddress(input.write);
    if (outputs_.read_valid && !input.read_ready) ++read_backpressure_cycles;
    if (response_accept) {
      responses.pop_front();
      last_b_cycle = edge_;
    }
    if (read_accept) {
      auto &request = reads.front();
      Require(edge_ >= request.accepted + latency +
                          ((1u << request.size) + service_bytes - 1) / service_bytes - 1,
              "Read completed before its byte services");
      if (request.transferred == 0) {
        min_first_read_latency = std::min(min_first_read_latency, edge_ - request.accepted);
        max_first_read_latency = std::max(max_first_read_latency, edge_ - request.accepted);
        if (request.size == 4)
          min_first_full_read_latency = std::min(min_first_full_read_latency,
                                                 edge_ - request.accepted);
      }
      read_service.Accept(edge_, 1u << request.size);
      ++read_beats_by_size[request.size];
      ++request.transferred;
      ++read_beats;
      last_r_cycle = edge_;
      read_progress_ = 0;
      if (request.transferred == request.beats) reads.pop_front();
    }
    if (write_grant_) {
      auto &request = writes.front();
      const uint32_t address = request.address + (request.transferred << request.size);
      for (uint32_t byte = write_offset_; byte < write_offset_ + write_grant_; ++byte) {
        const uint32_t lane = (address & 15) + byte;
        if (!(held_write_.strobe & (1u << lane))) continue;
        Require(address + byte >= output_begin && address + byte < output_end,
                "External store is outside the output tensor");
        memory[address - kRamBase + byte] = held_write_.data[lane];
        ++bytes_written;
      }
      write_service.Grant(edge_, write_grant_, service_bytes);
      if (read_service.last_cycle == edge_) ++simultaneous_service_cycles;
      write_progress_ += write_grant_;
      if (!write_accept) ++write_partial_cycles;
    }
    if (write_accept) {
      Require(write_grant_ != 0 && !writes.empty(), "AXI W without byte service");
      auto &request = writes.front();
      Require(write_progress_ == (1u << request.size), "Partial AXI write accepted");
      write_service.Accept(edge_, 1u << request.size);
      ++write_beats_by_size[request.size];
      ++request.transferred;
      ++write_beats;
      last_w_cycle = edge_;
      write_progress_ = 0;
      if (request.transferred == request.beats) {
        responses.push_back({request.id, edge_ + 1});
        writes.pop_front();
      }
    }
    if (ar) {
      const auto &a = input.read;
      reads.push_back({a.address, a.id, a.beats, a.size, 0, edge_, edge_ + latency});
      ++read_requests;
      read_requested_bytes += uint64_t(a.beats) << a.size;
      if (!first_ar_cycle) first_ar_cycle = edge_;
      max_read_burst = std::max(max_read_burst, a.beats);
    }
    if (aw) {
      const auto &a = input.write;
      writes.push_back({a.address, a.id, a.beats, a.size, 0, edge_, 0});
      ++write_requests;
      write_requested_bytes += uint64_t(a.beats) << a.size;
      last_aw_cycle = edge_;
      max_write_burst = std::max(max_write_burst, a.beats);
    }
    max_read_outstanding = std::max(max_read_outstanding, uint32_t(reads.size()));
    max_write_outstanding = std::max(max_write_outstanding,
                                     uint32_t(writes.size() + responses.size()));
    Require(max_read_outstanding <= 4 && max_write_outstanding <= 4,
            "AXI outstanding transaction limit exceeded");
  }

  bool DrainedService() const {
    return reads.empty() && writes.empty() && responses.empty() &&
           read_progress_ == 0 && write_progress_ == 0;
  }

  void CheckComplete() const {
    Require(DrainedService(), "Memory service contains an incomplete transaction");
    Require(read_service.bytes == read_requested_bytes, "Read service byte count mismatch");
    Require(write_service.bytes == write_requested_bytes, "Write service byte count mismatch");
    Require(read_service.max_bytes_per_cycle <= service_bytes &&
                write_service.max_bytes_per_cycle <= service_bytes,
            "External memory bandwidth exceeded");
    if (service_bytes == 8) {
      Require(read_service.full_beats < 2 || read_service.FullInterval() >= 2,
              "Full read beats exceeded the service bandwidth");
      Require(write_service.full_beats < 2 || write_service.FullInterval() >= 2,
              "Full write beats exceeded the service bandwidth");
    }
  }

private:
  uint64_t edge_ = 0;
  uint32_t read_progress_ = 0, write_progress_ = 0;
  uint32_t write_offset_ = 0, write_grant_ = 0;
  bool prepared_write_ = false;
  WriteData held_write_;
  std::array<uint8_t, 16> read_data_{};
  Outputs outputs_;

  void CheckHeldWrite(const WriteData &data) const {
    Require(data.valid && data.data == held_write_.data &&
                data.strobe == held_write_.strobe && data.last == held_write_.last,
            "AXI write payload changed during a partial byte service");
  }
};

}  // namespace coral_fairness
