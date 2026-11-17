#ifndef PS_HANDOFF_WINDOW_SCHEDULER_HPP
#define PS_HANDOFF_WINDOW_SCHEDULER_HPP

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>

namespace ps_schedule {

constexpr std::uint32_t tile_size = 16;
constexpr std::uint32_t max_frames = 16;

struct Config {
    std::uint32_t stream_rows = 0;
    std::uint32_t stationary_rows = 0;
    std::uint32_t reduction = 0;
    std::uint32_t reuse_rows = 1;
    std::uint32_t window_frames = 1;
    std::uint32_t slice_tiles = 0;
};

struct Command {
    std::uint32_t frame_id = 0;
    std::uint32_t p0 = 0;
    std::uint32_t q0 = 0;
    std::uint32_t column0 = 0;
    std::uint32_t rows = 0;
    std::uint32_t cols = 0;
    std::uint32_t reduction = 0;
    bool init = false;
    bool final = false;
    std::uint32_t reserve_rows = 0;

    bool operator==(const Command &other) const {
        return frame_id == other.frame_id && p0 == other.p0 && q0 == other.q0 &&
               column0 == other.column0 && rows == other.rows && cols == other.cols &&
               reduction == other.reduction && init == other.init && final == other.final &&
               reserve_rows == other.reserve_rows;
    }
};

struct FrameState {
    std::uint32_t column0 = 0;
    std::uint32_t p0 = 0;
    std::uint32_t rows = 0;
    std::uint32_t next_k = 0;
    bool started = false;
    bool live = false;
    bool finished = false;
};

enum class Phase { Idle, Opening, Sweeping, Draining, Complete };

struct Statistics {
    std::uint64_t commands = 0;
    std::uint64_t completed_frames = 0;
    std::uint64_t windows = 0;
    std::uint64_t pressures = 0;
    std::uint64_t opening_pressures = 0;
    std::uint64_t update_pressures = 0;
    std::uint64_t drain_commands = 0;
    std::uint32_t max_resident = 0;
};

// Coordinates use physical stream/stationary directions. The caller maps these
// to WS or IS and performs storage admission before accept(). A completion means
// that computation and all PS or final-output writes have finished.
class WindowScheduler {
public:
    void start(const Config &config) {
        require(phase_ == Phase::Idle || phase_ == Phase::Complete,
                "A scheduler job is already active");
        require(config.stream_rows && config.stationary_rows && config.reduction,
                "Matrix dimensions must be positive");
        require(config.reuse_rows && config.window_frames && config.window_frames <= max_frames,
                "The requested reuse window is invalid");
        require(config.reuse_rows <= std::numeric_limits<std::uint32_t>::max() / tile_size,
                "The physical row group exceeds the coordinate range");
        require(config.slice_tiles <= config.reuse_rows &&
                    (config.slice_tiles & (config.slice_tiles - 1U)) == 0,
                "The slice size must be zero or a supported power of two");
        config_ = config;
        stats_ = {};
        p0_ = 0;
        next_column_tile_ = 0;
        next_row_part_ = 0;
        active_.reset();
        begin_window();
        select_candidate();
    }

    std::optional<Command> candidate() const {
        return active_ ? std::nullopt : pending_;
    }

    void accept() {
        require(!active_ && pending_.has_value(), "No command is available for acceptance");
        active_ = pending_;
    }

    void complete() {
        require(active_.has_value(), "No accepted command is available for completion");
        const Command command = *active_;
        auto &frame = frames_[command.frame_id];
        if (command.init) {
            require(!frame.started, "A frame cannot be initialized twice");
            frame.started = true;
            frame.column0 = command.column0;
            frame.p0 = command.p0;
            frame.rows = command.rows;
            ++opened_;
            if (++next_row_part_ == group_parts()) {
                next_row_part_ = 0;
                ++next_column_tile_;
            }
        }
        ++frame.next_k;
        frame.live = !command.final;
        frame.finished = command.final;
        ++stats_.commands;
        if (command.final) {
            ++stats_.completed_frames;
            if (protected_ && *protected_ == command.frame_id) protected_.reset();
        } else {
            protected_ = command.frame_id;
        }
        stats_.max_resident = std::max(stats_.max_resident, resident_count());
        if (phase_ == Phase::Draining) {
            ++stats_.drain_commands;
            if (command.final) {
                phase_ = Phase::Sweeping;
                cursor_ = resume_.value_or(0);
                resume_.reset();
            }
        } else if (phase_ == Phase::Sweeping) {
            cursor_ = (command.frame_id + 1) % opened_;
        }
        active_.reset();
        select_candidate();
    }

    // A rejected candidate has not changed its data or K cursor. The protected
    // frame is admitted by the same per-bank RAW bound as its previous update.
    void pressure() {
        require(!active_ && pending_.has_value(), "Pressure requires an unaccepted command");
        require(!pending_->final, "A final command does not allocate intermediate PS");
        require(phase_ == Phase::Opening || phase_ == Phase::Sweeping,
                "The protected frame must remain executable");
        require(protected_.has_value() && frames_[*protected_].live,
                "Capacity must accommodate one complete RAW frame");
        require(*protected_ != pending_->frame_id,
                "Capacity pressure violates the protected-frame invariant");
        if (phase_ == Phase::Opening) {
            require(opened_ != 0, "A window cannot close before its first frame");
            target_ = opened_;
            resume_.reset();
            ++stats_.opening_pressures;
            phase_ = Phase::Sweeping;
            cursor_ = 0;
        } else {
            resume_ = pending_->frame_id;
            ++stats_.update_pressures;
            phase_ = Phase::Draining;
        }
        ++stats_.pressures;
        select_candidate();
    }

    bool done() const { return phase_ == Phase::Complete; }
    bool inflight() const { return active_.has_value(); }
    Phase phase() const { return phase_; }
    const Config &config() const { return config_; }
    const Statistics &statistics() const { return stats_; }
    const std::array<FrameState, max_frames> &frames() const { return frames_; }
    std::optional<std::uint32_t> protected_frame() const { return protected_; }
    std::uint32_t resident_count() const {
        std::uint32_t count = 0;
        for (const auto &frame : frames_) count += frame.live ? 1U : 0U;
        return count;
    }

private:
    Config config_{};
    Statistics stats_{};
    std::array<FrameState, max_frames> frames_{};
    Phase phase_ = Phase::Idle;
    std::optional<Command> pending_, active_;
    std::optional<std::uint32_t> protected_, resume_;
    std::uint32_t p0_ = 0, next_column_tile_ = 0, next_row_part_ = 0;
    std::uint32_t opened_ = 0, target_ = 0, cursor_ = 0;

    static void require(bool condition, const char *message) {
        if (!condition) throw std::logic_error(message);
    }

    std::uint32_t column_tiles() const { return 1 + (config_.stationary_rows - 1) / tile_size; }
    std::uint32_t current_rows() const {
        return std::min(config_.reuse_rows * tile_size, config_.stream_rows - p0_);
    }
    std::uint32_t slice_rows() const {
        return (config_.slice_tiles ? config_.slice_tiles : config_.reuse_rows) * tile_size;
    }
    std::uint32_t group_parts() const {
        return 1 + (current_rows() - 1) / slice_rows();
    }

    void begin_window() {
        frames_ = {};
        protected_.reset();
        resume_.reset();
        opened_ = 0;
        cursor_ = 0;
        target_ = std::min<std::uint64_t>(max_frames, std::min<std::uint64_t>(
            std::uint64_t(config_.window_frames) * group_parts(),
            std::uint64_t(column_tiles() - next_column_tile_) * group_parts() - next_row_part_));
        phase_ = Phase::Opening;
        ++stats_.windows;
    }

    Command command_for(std::uint32_t id, bool initial) const {
        Command command;
        command.frame_id = id;
        command.p0 = initial ? p0_ + next_row_part_ * slice_rows() : frames_[id].p0;
        command.q0 = initial ? 0 : frames_[id].next_k * tile_size;
        command.column0 = initial ? next_column_tile_ * tile_size : frames_[id].column0;
        command.rows = initial ? std::min(slice_rows(), current_rows() - next_row_part_ * slice_rows())
                               : frames_[id].rows;
        command.reserve_rows = std::min(slice_rows(), current_rows());
        command.cols = std::min(tile_size, config_.stationary_rows - command.column0);
        command.reduction = std::min(tile_size, config_.reduction - command.q0);
        command.init = initial;
        command.final = command.reduction == config_.reduction - command.q0;
        return command;
    }

    void select_candidate() {
        pending_.reset();
        for (;;) {
            if (phase_ == Phase::Opening) {
                if (opened_ < target_) {
                    pending_ = command_for(opened_, true);
                    return;
                }
                phase_ = Phase::Sweeping;
                cursor_ = 0;
            }
            if (phase_ == Phase::Draining) {
                require(protected_.has_value() && frames_[*protected_].live,
                        "A drain requires a resident protected frame");
                pending_ = command_for(*protected_, false);
                return;
            }
            if (phase_ == Phase::Sweeping) {
                for (std::uint32_t offset = 0; offset < opened_; ++offset) {
                    const auto id = (cursor_ + offset) % opened_;
                    if (frames_[id].live) {
                        pending_ = command_for(id, false);
                        return;
                    }
                }
                if (next_column_tile_ == column_tiles()) {
                    p0_ += current_rows();
                    next_column_tile_ = 0;
                    next_row_part_ = 0;
                    if (p0_ == config_.stream_rows) {
                        phase_ = Phase::Complete;
                        return;
                    }
                }
                begin_window();
                continue;
            }
            return;
        }
    }
};

} // namespace ps_schedule
#endif
