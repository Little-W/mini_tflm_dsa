#include "capture.hpp"
#include "svdpi.h"
#include "verilated.h"
#include <string>

thread_local Capture* active_capture = nullptr;
static Capture native_capture;
static const char* names[] = {
    "rst_n", "calc_start", "sa_ready", "done_valid", "err_code",
    "core_busy", "weight_write", "acc_valid", "requant_valid",
    "write_queue_full", "final_tile_row", "axi_flags", "araddr", "arlen", "rdata",
    "awaddr", "awlen", "wdata", "wstrb", "engine_state",
    "frame_committed", "frame_launch", "input_final_k", "operand_panel_available",
    "write_data_valid", "write_data_ready", "A_panel_read_done", "B_panel_read_done",
    "C_write_done", "is_mode", "int16_output", "int16_input"
};

void Capture::initialize() {
    initialized = true;
    const char* io_arg = Verilated::threadContextp()->commandArgsPlusMatch("IO_SUMMARY=");
    if (io_arg && std::string(io_arg).rfind("+IO_SUMMARY=", 0) == 0)
        io_summary_path = std::string(io_arg).substr(12);
    const char* acc_arg = Verilated::threadContextp()->commandArgsPlusMatch("ACC_DUMP=");
    if (acc_arg && std::string(acc_arg).rfind("+ACC_DUMP=", 0) == 0) {
        acc_dump.open(std::string(acc_arg).substr(10), std::ios::binary);
        if (!acc_dump) VL_FATAL_MT(__FILE__, __LINE__, "", "Cannot open ACC_DUMP file");
    }
    const char* arg = Verilated::threadContextp()->commandArgsPlusMatch("PY_TRACE=");
    if (arg && std::string(arg).rfind("+PY_TRACE=", 0) == 0) {
        csv.open(std::string(arg).substr(10));
        if (!csv) VL_FATAL_MT(__FILE__, __LINE__, "", "Cannot open PY_TRACE file");
        csv << "cycle,time_ps";
        for (const auto* name : names) csv << ',' << name;
        const char* prefixes[] = {"ia", "weight", "acc", "requant"};
        for (size_t kind = 0; kind < lanes.size(); ++kind)
            for (size_t i = 0; i < lanes[kind].size(); ++i)
                csv << ',' << prefixes[kind] << i;
        csv << '\n';
    }
}

void Capture::write_io_summary() {
    if (io_summary_path.empty()) return;
    std::ofstream out(io_summary_path, std::ios::trunc);
    if (!out) VL_FATAL_MT(__FILE__, __LINE__, "", "Cannot open IO_SUMMARY file");
    const bool complete = task_accept_cycle != UINT64_MAX && last_output_b_cycle != UINT64_MAX;
    auto value = [&](uint64_t v) { if (v == UINT64_MAX) out << "null"; else out << v; };
    out << "{\"cycle_convention\":\"zero-based rising-edge indices; task acceptance observed in the registered CHECK state after that edge; stable AXI handshakes consumed on the following edge\",\"task_accept_cycle\":";
    value(task_accept_cycle);
    out << ",\"last_output_w_cycle\":"; value(last_output_w_cycle);
    out << ",\"last_output_b_cycle\":"; value(last_output_b_cycle);
    out << ",\"end_to_end_cycles\":";
    if (complete) out << last_output_b_cycle-task_accept_cycle+1; else out << "null";
    out << ",\"inclusive_endpoints\":true,\"accepted_ar\":" << accepted_ar
        << ",\"accepted_r\":" << accepted_r << ",\"accepted_aw\":" << accepted_aw
        << ",\"accepted_w\":" << accepted_w << ",\"accepted_b\":" << accepted_b
        << ",\"valid_output_bytes\":" << valid_output_bytes << ",\"read_burst_beats_hist\":{";
    bool comma = false;
    for (size_t i=0;i<read_burst_hist.size();++i) if (read_burst_hist[i]) {
        if (comma) out << ',';
        out << '\"' << i+1 << "\":" << read_burst_hist[i]; comma=true;
    }
    out << "},\"write_burst_beats_hist\":{"; comma=false;
    for (size_t i=0;i<write_burst_hist.size();++i) if (write_burst_hist[i]) {
        if (comma) out << ',';
        out << '\"' << i+1 << "\":" << write_burst_hist[i]; comma=true;
    }
    out << "}}\n";
}

extern "C" void py_task_accept() {
    Capture& cap = active_capture ? *active_capture : native_capture;
    // Called after the current rising edge but before py_capture increments
    // cycles. CHECK is the registered acceptance event of this edge.
    if (cap.task_accept_cycle == UINT64_MAX) cap.task_accept_cycle = cap.cycles;
}

extern "C" void py_capture(
    unsigned int lane_count,
    const unsigned int* scalar_values, const unsigned int* ia_values,
    const unsigned int* weight_values, const unsigned int* acc_values,
    const unsigned int* requant_values
) {
    Capture& cap = active_capture ? *active_capture : native_capture;
    for (size_t i = 0; i < cap.scalars.size(); ++i) cap.scalars[i] = scalar_values[i];
    cap.lanes[0] = std::vector<uint32_t>(ia_values,ia_values+lane_count);
    cap.lanes[1] = std::vector<uint32_t>(weight_values,weight_values+lane_count);
    cap.lanes[2] = std::vector<uint32_t>(acc_values,acc_values+lane_count);
    cap.lanes[3] = std::vector<uint32_t>(requant_values,requant_values+lane_count);
    if (!cap.initialized) cap.initialize();
    cap.time_ps = Verilated::threadContextp()->time();
    if (cap.scalars[1] && cap.start_cycle == UINT64_MAX) cap.start_cycle = cap.cycles;
    if (cap.start_cycle != UINT64_MAX && !cap.scalars[2]) cap.saw_busy = true;
    if (cap.saw_busy && cap.scalars[2] && cap.ready_cycle == UINT64_MAX)
        cap.ready_cycle = cap.cycles;
    if (cap.task_accept_cycle != UINT64_MAX) {
        const uint32_t flags = cap.scalars[11];
        if ((flags & 3u) == 3u) { ++cap.accepted_ar; ++cap.read_burst_hist[cap.scalars[13] & 255u]; }
        if ((flags & 12u) == 12u) ++cap.accepted_r;
        if ((flags & 96u) == 96u) { ++cap.accepted_aw; ++cap.write_burst_hist[cap.scalars[16] & 255u]; }
        if ((flags & 384u) == 384u) {
            ++cap.accepted_w;
            cap.last_output_w_cycle = cap.cycles+1;
            cap.valid_output_bytes += __builtin_popcount(cap.scalars[18] & 15u);
        }
        if ((flags & 3072u) == 3072u) { ++cap.accepted_b; cap.last_output_b_cycle = cap.cycles+1; }
    }
    if (cap.acc_dump && cap.scalars[7]) {
        cap.acc_dump.write(reinterpret_cast<const char*>(acc_values),
                           lane_count * sizeof(uint32_t));
    }
    if (cap.csv) {
        cap.csv << cap.cycles << ',' << cap.time_ps;
        for (uint32_t value : cap.scalars) cap.csv << ',' << value;
        for (const auto& vector : cap.lanes)
            for (uint32_t value : vector) cap.csv << ',' << value;
        cap.csv << '\n';
    }
    ++cap.cycles;
}
