#include "Vdma_registered_tb.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
constexpr unsigned bytes_per_beat = TEST_BUS_WIDTH / 8;
constexpr unsigned input_base = 0x10ffd;
constexpr unsigned linear_base = 0x20ffd;
constexpr unsigned slot_mask = TEST_CACHE_BLOCKS - 1;

void require(bool value, const std::string& message) {
    if (!value) throw std::runtime_error(message);
}

int byte_value(uint32_t address) {
    const unsigned value = (address * 37U + (address >> 4U) * 13U + 71U) & 255U;
    return value >= 128U ? int(value) - 256 : int(value);
}

struct Command {
    bool image = true;
    uint32_t p = 5, q = 3, group = 0, rows = 2, cols = 16;
    unsigned slot = 0, tag = 0;
    bool error = false, immediate_error = false;
    uint64_t accepted_cycle = 0;
    unsigned starts = 0, values = 0;
    bool ready_when_accepted = false;
    std::array<bool, 16 * 16> seen{};
};

struct Burst { uint32_t address; unsigned beats, size, index; uint64_t ready_cycle; };

class Test {
public:
    Vdma_registered_tb dut;
    std::deque<Burst> bus;
    std::deque<Command> commands;
    Command offered;
    Command queued_image;
    bool offer_on_linear_finish = false;
    bool has_offer = false, inject_error = false, injected = false;
    bool hold_ar = false, hold_r = false;
    bool configured_prefetch = false;
    uint64_t cycles = 0, accepted = 0, completed = 0, frontend_starts = 0;
    uint64_t checked_values = 0, rejected = 0, reset_cancelled = 0;
    uint64_t abort_pending = 0, ar_waits = 0, r_waits = 0, immediate_errors = 0;
    uint64_t completion_accept_overlap = 0, window_responses = 0;
    uint64_t ar_requests = 0, error_completions = 0, immediate_ready_starts = 0;
    uint64_t maximum_start_delay = 0;
    uint64_t linear_finish_accept_overlap = 0;
    uint64_t image_accept_during_prefetch = 0, image_complete_during_prefetch = 0;
    uint64_t configuration_error_pending = 0, configuration_error_recoveries = 0;
    unsigned response_delay = 0;
    unsigned scenario = 0;

    Test() {
        dut.clk = 0; dut.rst_n = 0; dut.i_abort = 0;
        dut.rd_start = 0; dut.wr_start = 0; dut.src_wvalid = 0;
        dut.conv_cfg_valid = 0; dut.conv_enable = 1; dut.dma_range_enable = 0;
        dut.win_req_valid = 0; dut.win_rsp_ready = 1;
        dut.m_axi_awready = 1; dut.m_axi_wready = 1; dut.m_axi_bvalid = 0; dut.m_axi_bresp = 0;
        for (unsigned i = 0; i < 4; ++i) { dut.conv_range_base[i] = 0; dut.conv_range_end[i] = 0; }
        for (unsigned i = 0; i < 16; ++i) dut.config_words[i] = 0;
        reset();
    }

    int expected(const Command& command, unsigned row, unsigned col) const {
        if (!command.image) return byte_value(linear_base + row * 19U + col) - 11;
        const uint32_t p = command.p + row, q = command.q + col;
        if (q >= 45U) return 0;
        const int iy = int(p / 7U) - 1 + int((q / 5U) / 3U);
        const int ix = int(p % 7U) - 1 + int((q / 5U) % 3U);
        if (iy < 0 || iy >= 5 || ix < 0 || ix >= 7) return 0;
        return byte_value(input_base + unsigned(iy * 7 + ix) * 5U + q % 5U) - 7;
    }

    void evaluate() { dut.clk = 0; dut.eval(); }

    void step() {
        dut.clk = 0;
        dut.m_axi_arready = !hold_ar && (cycles % 7U != 2U);
        dut.m_axi_rvalid = !bus.empty() && !hold_r && (cycles % 5U != 1U) &&
                          cycles >= bus.front().ready_cycle;
        dut.m_axi_rdata = 0; dut.m_axi_rlast = 0; dut.m_axi_rresp = 0;
        if (!bus.empty()) {
            const auto& b = bus.front();
            const uint32_t address = b.address + (b.index << b.size);
            const uint32_t word_address = address & ~(bytes_per_beat - 1U);
            uint64_t word = 0;
            for (unsigned lane = 0; lane < bytes_per_beat; ++lane)
                word |= uint64_t(uint8_t(byte_value(word_address + lane))) << (8U * lane);
            dut.m_axi_rdata = word;
            dut.m_axi_rlast = b.index + 1U == b.beats;
            dut.m_axi_rresp = inject_error && !injected ? 2 : 0;
        }
        dut.eval();
        if (offer_on_linear_finish && dut.observe_linear_finish) {
            present(queued_image);
            offer_on_linear_finish = false;
        }
        const bool ar_fire = dut.m_axi_arvalid && dut.m_axi_arready;
        const bool r_fire = dut.m_axi_rvalid && dut.m_axi_rready;
        const Burst incoming{dut.m_axi_araddr, unsigned(dut.m_axi_arlen) + 1U,
                             dut.m_axi_arsize, 0, cycles + response_delay};
        if (dut.rst_n) {
            if (dut.m_axi_arvalid && !dut.m_axi_arready) ++ar_waits;
            if (!bus.empty() && !dut.m_axi_rvalid) ++r_waits;
            require(!dut.observe_pending || dut.observe_active, "pending without active transaction");
            if (dut.observe_pending && dut.i_abort) ++abort_pending;
            if (dut.observe_frontend_fire && !dut.win_busy) {
                require(!commands.empty(), "frontend accepted an unknown descriptor");
                auto& c = commands.back();
                require(c.image && !c.immediate_error && c.starts == 0, "duplicate frontend acceptance");
                require(cycles > c.accepted_cycle, "frontend consumed an uncaptured descriptor");
                require(dut.observe_p0 == c.p && dut.observe_q0 == c.q &&
                        dut.observe_group == c.group && dut.observe_rows == c.rows &&
                        dut.observe_cols == ((c.cols > 0 && c.cols <= 16) ? c.cols : 16U) &&
                        dut.observe_slot == (c.slot & slot_mask), "captured descriptor changed");
                if (c.ready_when_accepted) {
                    require(cycles == c.accepted_cycle + 1U, "registered launch interval changed");
                    ++immediate_ready_starts;
                }
                maximum_start_delay = std::max(maximum_start_delay, cycles - c.accepted_cycle);
                ++c.starts; ++frontend_starts;
            }
            for (unsigned lane = 0; lane < bytes_per_beat; ++lane) if (dut.wr_valid[lane]) {
                require(!commands.empty(), "data without a descriptor");
                auto& c = commands.front();
                const unsigned row = dut.wr_row, col = dut.wr_col_base + lane;
                const unsigned cols = c.image ? ((c.cols > 0 && c.cols <= 16) ? c.cols : 16U) : 16U;
                require(row < c.rows && col < cols, "matrix index outside descriptor");
                require(row < 16 && col < 16 && !c.seen[row * 16U + col], "duplicate matrix element");
                require(dut.wr_slot == (c.slot & slot_mask), "matrix slot changed");
                require(dut.rd_response_tag == c.tag, "matrix response tag changed");
                require(int16_t(dut.wr_data[lane]) == expected(c, row, col),
                        "matrix value mismatch scenario=" + std::to_string(scenario) +
                        " cycle=" + std::to_string(cycles) + " p=" + std::to_string(c.p) +
                        " q=" + std::to_string(c.q) + " row=" + std::to_string(row) +
                        " col=" + std::to_string(col) + " got=" +
                        std::to_string(int16_t(dut.wr_data[lane])) + " expected=" +
                        std::to_string(expected(c, row, col)));
                c.seen[row * 16U + col] = true; ++c.values; ++checked_values;
            }
            if (dut.rd_done) {
                require(!commands.empty(), "completion without a descriptor");
                const auto c = commands.front();
                require(dut.rd_response_tag == c.tag, "completion tag changed");
                require(bool(dut.rd_error) == c.error, "completion error status mismatch");
                if (c.image) require(c.starts == (c.immediate_error ? 0U : 1U), "frontend acceptance count mismatch");
                if (!c.error) {
                    const unsigned cols = c.image ? ((c.cols > 0 && c.cols <= 16) ? c.cols : 16U) : 16U;
                    require(c.values == c.rows * cols, "incomplete matrix output");
                }
                if (c.error) ++error_completions;
                if (c.image && configured_prefetch && dut.observe_frontend_busy)
                    ++image_complete_during_prefetch;
                if (c.immediate_error) { require(c.values == 0, "immediate error produced data"); ++immediate_errors; }
                ++completed; commands.pop_front();
                if (dut.observe_accept || dut.observe_linear_accept) ++completion_accept_overlap;
            }
            if (dut.observe_accept || dut.observe_linear_accept) {
                require(has_offer && !dut.i_abort, "unexpected command acceptance");
                offered.accepted_cycle = cycles; offered.ready_when_accepted = dut.observe_frontend_ready;
                commands.push_back(offered); ++accepted;
                require(!offered.image || !dut.observe_frontend_fire, "image accepted without register separation");
                has_offer = false;
                if (dut.observe_accept && dut.observe_linear_finish) ++linear_finish_accept_overlap;
                if (dut.observe_accept && configured_prefetch && dut.observe_frontend_busy)
                    ++image_accept_during_prefetch;
                require(!dut.observe_linear_accept || !dut.observe_frontend_busy,
                        "linear command accepted before image reads drained");
            }
            if (dut.win_rsp_valid && dut.win_rsp_ready) ++window_responses;
        }
        dut.clk = 1; dut.eval(); ++cycles;
        if (r_fire) {
            if (dut.m_axi_rresp) injected = true;
            if (++bus.front().index == bus.front().beats) bus.pop_front();
        }
        if (ar_fire) { bus.push_back(incoming); ++ar_requests; }
        dut.clk = 0; dut.eval();
    }

    void reset() {
        reset_cancelled += commands.size(); commands.clear(); bus.clear(); has_offer = false;
        dut.rst_n = 0; dut.rd_start = 0; dut.i_abort = 0; dut.win_req_valid = 0;
        dut.conv_cfg_valid = 0; hold_ar = false; hold_r = false;
        configured_prefetch = false;
        for (unsigned i = 0; i < 4; ++i) step();
        dut.rst_n = 1; step();
    }

    void wait_idle() {
        for (unsigned i = 0; i < 50000; ++i) {
            evaluate();
            if (commands.empty() && bus.empty() && !dut.rd_busy && !dut.rd_done) return;
            step();
        }
        throw std::runtime_error("DMA did not finish");
    }

    void configure(bool windowed = false, bool prefetch = false) {
        wait_idle(); dut.i_abort = 0; dut.conv_enable = 1; inject_error = false; injected = false;
        configured_prefetch = prefetch;
        const uint32_t words[16] = {input_base, 5, 7, 5, 3, 3, 5, 7, 1, 1, 1, 1,
                                    uint32_t(-7), unsigned(windowed), unsigned(prefetch), 0};
        for (unsigned i = 0; i < 16; ++i) dut.config_words[i] = words[i];
        dut.conv_range_base[0] = linear_base; dut.conv_range_end[0] = linear_base + 512U;
        evaluate();
        for (unsigned i = 0; i < 50000 && !dut.conv_cfg_ready; ++i) step();
        require(dut.conv_cfg_ready, "configuration input remained busy");
        dut.conv_cfg_valid = 1; step(); dut.conv_cfg_valid = 0;
        for (unsigned i = 0; i < 2000; ++i) { evaluate(); if (dut.observe_frontend_ready) return; step(); }
        throw std::runtime_error("frontend configuration did not finish scenario=" + std::to_string(scenario) + " state=" + std::to_string(dut.observe_configuration) + " error=" + std::to_string(dut.conv_error));
    }

    void present(Command c) {
        offered = c; has_offer = true;
        dut.rd_im2col = c.image; dut.rd_p0 = c.p; dut.rd_q0 = c.q; dut.rd_group = c.group;
        dut.rd_rows_to_read = c.rows; dut.rd_valid_cols = c.cols;
        dut.rd_slot_id = c.slot & slot_mask; dut.rd_tag = c.tag;
        dut.rd_linear_read_mode = 0; dut.rd_base_addr = linear_base; dut.rd_row_stride = 19;
        dut.rd_burst_len_m1 = 16U / bytes_per_beat - 1U;
        dut.rd_use_16bits = 0; dut.rd_lhs_zp = uint32_t(-11); dut.rd_start = 1;
        evaluate();
    }

    void start(Command c) {
        present(c);
        for (unsigned i = 0; i < 50000 && has_offer; ++i) step();
        require(!has_offer, "descriptor was not accepted");
        dut.rd_start = 0;
        dut.rd_p0 = 0xffffffffU; dut.rd_q0 = 0xffffffffU; dut.rd_group = 0xffffffffU;
        dut.rd_rows_to_read = 0xffffffffU; dut.rd_valid_cols = 0xffffffffU; dut.rd_slot_id = 0;
        dut.rd_tag = 7; evaluate();
    }

    void configuration_error(bool abort_after_accept) {
        wait_idle();
        dut.i_abort = 0; dut.conv_enable = 1; inject_error = false; injected = false;
        configured_prefetch = false;
        const uint32_t words[16] = {abort_after_accept ? 0xffffff80U : 0xfffffff0U,
            5, 7, 5, 3, 3, 5, 7, 1, 1, 1, 1, uint32_t(-7), 0, 0, 0};
        for (unsigned i = 0; i < 16; ++i) dut.config_words[i] = words[i];
        evaluate();
        for (unsigned i = 0; i < 50000 && !dut.conv_cfg_ready; ++i) step();
        require(dut.conv_cfg_ready, "configuration error case could not configure");
        const auto accepted_before = accepted, completed_before = completed;
        const auto errors_before = error_completions, starts_before = frontend_starts;
        const auto requests_before = ar_requests, config_cycle = cycles;
        dut.conv_cfg_valid = 1; step(); dut.conv_cfg_valid = 0; evaluate();
        require(dut.observe_frontend_busy && !dut.observe_frontend_ready && !dut.conv_error,
                "configuration preparation interval was not exercised");

        // 配置准备期间立即接收描述符，范围溢出随后通过一次错误完成释放它。
        Command c; c.rows = 1; c.tag = abort_after_accept ? 6U : 4U;
        c.error = true; c.immediate_error = true;
        start(c);
        require(accepted == accepted_before + 1U && !commands.empty() &&
                commands.back().accepted_cycle == config_cycle + 1U,
                "descriptor was not accepted immediately after configuration");
        require(dut.observe_pending && dut.observe_active && !dut.conv_error,
                "configuration error did not cover an already pending descriptor");
        ++configuration_error_pending;
        if (abort_after_accept) dut.i_abort = 1;
        wait_idle();
        require(completed == completed_before + 1U && error_completions == errors_before + 1U,
                "configuration failure completion count mismatch");
        require(dut.conv_error && !dut.observe_pending && !dut.observe_active &&
                !dut.observe_frontend_busy && !dut.conv_busy && !dut.rd_busy &&
                !dut.rd_done && !dut.m_axi_arvalid && bus.empty() && dut.conv_cfg_ready,
                "configuration failure did not release all accepted state");
        require(ar_requests == requests_before && frontend_starts == starts_before,
                "invalid configuration started an input transaction");
        for (unsigned i = 0; i < 20; ++i) step();
        require(completed == completed_before + 1U,
                "configuration failure generated a second completion");
        ++scenario;

        // 错误状态排空后重新配置，并逐元素检查合法任务的数据和标签。
        configure();
        Command recovery; recovery.rows = 3; recovery.p = 6; recovery.tag = 2;
        const auto values_before = checked_values;
        start(recovery); wait_idle();
        require(!dut.conv_error && checked_values == values_before + recovery.rows * recovery.cols,
                "valid image task did not recover after configuration failure");
        ++configuration_error_recoveries; ++scenario;
    }

    void run() {
        configuration_error(false);
        configuration_error(true);
        configure();
        for (unsigned mode = 0; mode < 6; ++mode) {
            Command c; c.slot = mode + 1U; c.tag = mode; c.rows = 1U + mode; c.q = mode * 7U;
            start(c);
            if (mode == 0) dut.i_abort = 1;
            if (mode == 1) { hold_ar = true; for (unsigned i = 0; i < 12; ++i) step(); dut.i_abort = 1; hold_ar = false; }
            if (mode == 2) { hold_r = true; for (unsigned i = 0; i < 20; ++i) step(); dut.i_abort = 1; hold_r = false; }
            if (mode == 3) {
                for (unsigned i = 0; i < 50000 &&
                     (bus.empty() || bus.front().index + 1U != bus.front().beats); ++i) step();
                require(!bus.empty() && bus.front().index + 1U == bus.front().beats,
                        "last response was not observed");
                dut.i_abort = 1;
            }
            wait_idle(); dut.i_abort = 0; ++scenario;
        }
        // 接收前的中止不产生待启动描述符或事务完成。
        const auto accepted_before = accepted, requests_before = ar_requests;
        Command rejected_command; rejected_command.tag = 3;
        dut.i_abort = 1; present(rejected_command);
        for (unsigned i = 0; i < 6; ++i) step();
        require(accepted == accepted_before && ar_requests == requests_before && commands.empty(), "aborted offer was accepted");
        dut.rd_start = 0; has_offer = false; dut.i_abort = 0; ++rejected; ++scenario;

        // 前端启动之前复位，然后重新配置并接收独立任务。
        Command cancelled; cancelled.tag = 1; start(cancelled);
        require(dut.observe_pending && commands.back().starts == 0, "pending reset coverage absent");
        reset(); configure(); ++scenario;
        Command recovered; recovered.tag = 2; recovered.rows = 16; start(recovered); wait_idle(); ++scenario;

        // 旧完成与新描述符在同一边沿发生，两个标签分别检查。
        Command first; first.tag = 1; start(first);
        for (unsigned i = 0; i < 50000 && !dut.rd_done; ++i) step();
        require(dut.rd_done, "missing old completion");
        Command second; second.tag = 5; second.slot = 37; second.p = 6; start(second); wait_idle(); ++scenario;

        for (unsigned cols : {0U, 1U, 16U, 17U, 0xffffffffU}) {
            Command c; c.cols = cols; c.rows = 1; c.tag = scenario % 7U; start(c); wait_idle(); ++scenario;
        }
        for (unsigned rows : {0U, 17U, 0xffffffffU}) {
            configure(); Command c; c.rows = rows; c.tag = 2; c.error = c.immediate_error = true;
            start(c); wait_idle(); ++scenario;
        }
        for (unsigned invalid_p : {35U, 0xffffffffU}) {
            configure(); Command c; c.p = invalid_p; c.rows = 1; c.tag = 6; c.error = true;
            start(c); wait_idle(); ++scenario;
        }
        configure();
        Command invalid_reduction; invalid_reduction.q = 0xffffffffU;
        invalid_reduction.rows = 1; invalid_reduction.error = true; invalid_reduction.tag = 3;
        start(invalid_reduction); wait_idle(); ++scenario;
        configure(); inject_error = true;
        Command failed; failed.error = true; failed.tag = 4; start(failed); wait_idle();
        require(injected, "read response error was not exercised"); ++scenario;
        configure(); start(Command{}); wait_idle(); ++scenario;

        // 普通线性读取与 im2col 交替使用相同数据返回端口。
        for (unsigned i = 0; i < 6; ++i) {
            Command c; c.image = (i & 1U) != 0; c.rows = 2; c.tag = i; c.slot = i + 11U;
            start(c); wait_idle(); ++scenario;
        }
        // 线性 DMA 最后一个数据拍与新 im2col 描述符在同一边沿接收。
        Command last_linear; last_linear.image = false; last_linear.rows = 1; last_linear.tag = 2;
        start(last_linear);
        queued_image = Command{}; queued_image.p = 6; queued_image.tag = 7; queued_image.slot = 23;
        offer_on_linear_finish = true;
        for (unsigned i = 0; i < 50000 && (offer_on_linear_finish || has_offer); ++i) step();
        require(!offer_on_linear_finish && !has_offer, "linear completion launch was not accepted");
        dut.rd_start = 0; wait_idle(); ++scenario;
        uint32_t random_state = 0x12345678U;
        for (unsigned i = 0; i < 128; ++i) {
            random_state = random_state * 1664525U + 1013904223U;
            Command c; c.rows = 1U + random_state % 16U;
            c.p = (random_state >> 5U) % (36U - c.rows);
            c.q = (random_state >> 12U) % 45U;
            c.cols = 1U + ((random_state >> 18U) % 16U);
            c.slot = (random_state >> 22U) & slot_mask; c.tag = i % 8U;
            c.group = random_state; start(c); wait_idle(); ++scenario;
        }
        // 连续图像分块共享配置，缓存预取与后续分块同时执行。
        // 首拍延迟使后台读取跨越描述符完成，线性命令仍等待这些读取结束。
        configure(false, true);
        response_delay = 32;
        for (unsigned i = 0; i < 32; ++i) {
            Command c;
            c.p = 7U + (i % 14U); c.q = (i * 5U) % 40U;
            c.rows = 2; c.cols = 5; c.tag = i % 8U; c.slot = i & slot_mask;
            start(c); ++scenario;
        }
        Command after_prefetch; after_prefetch.image = false;
        after_prefetch.rows = 2; after_prefetch.tag = 3;
        start(after_prefetch); wait_idle(); ++scenario;
        response_delay = 0;
        require(image_accept_during_prefetch > 0 && image_complete_during_prefetch > 0,
                "image prefetch overlap was not exercised");
        require(abort_pending > 0 && completion_accept_overlap > 0 && linear_finish_accept_overlap > 0 && ar_waits > 0 && r_waits > 0,
                "required control coverage absent");
        require(accepted == completed + reset_cancelled, "accepted transaction count mismatch");
        dut.final();
        std::cout << "{\"passed\":true,\"scenarios\":" << scenario
                  << ",\"cycles\":" << cycles << ",\"accepted\":" << accepted
                  << ",\"completed\":" << completed << ",\"frontend_starts\":" << frontend_starts
                  << ",\"checked_values\":" << checked_values << ",\"rejected\":" << rejected
                  << ",\"reset_cancelled\":" << reset_cancelled << ",\"abort_pending_cycles\":" << abort_pending
                  << ",\"completion_accept_overlap\":" << completion_accept_overlap
                  << ",\"ar_waits\":" << ar_waits << ",\"r_waits\":" << r_waits
                  << ",\"immediate_errors\":" << immediate_errors
                  << ",\"error_completions\":" << error_completions
                  << ",\"immediate_ready_starts\":" << immediate_ready_starts
                  << ",\"linear_finish_accept_overlap\":" << linear_finish_accept_overlap
                  << ",\"image_accept_during_prefetch\":" << image_accept_during_prefetch
                  << ",\"image_complete_during_prefetch\":" << image_complete_during_prefetch
                  << ",\"configuration_error_pending\":" << configuration_error_pending
                  << ",\"configuration_error_recoveries\":" << configuration_error_recoveries
                  << ",\"maximum_start_delay\":" << maximum_start_delay << "}\n";
    }
};
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    try { Test test; test.run(); }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    return 0;
}
