#include "Vdip_array_tb.h"
#include "verilated.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr unsigned size = TEST_SIZE;
constexpr unsigned data_bits = TEST_DATA_BITS;
constexpr unsigned weight_bits = TEST_WEIGHT_BITS;
using Matrix = std::vector<std::vector<std::int32_t>>;
using Sums = std::vector<std::vector<std::uint32_t>>;
std::uint64_t cycles = 0, checks = 0, rows_checked = 0, cases = 0;
std::uint64_t partial_injections = 0, overlapped_weight_cycles = 0, overflow_values = 0;
std::uint64_t wave_commits = 0, mixed_valid_cycles = 0, protected_load_cycles = 0;
std::uint64_t simultaneous_load_commits = 0, row_select_checks = 0, selected_weight_checks = 0;
std::uint64_t reset_checks = 0;
std::mt19937 random_values(0x64697000u + size * 31u + data_bits * 7u + weight_bits);

void require(bool value, const std::string& message) {
    if (!value) throw std::runtime_error(message);
}

std::int64_t signed32(std::uint32_t value) {
    return value < 0x80000000u ? std::int64_t(value) : std::int64_t(value) - 0x100000000ll;
}

void tick(Vdip_array_tb& dut) {
    dut.clk = 0; dut.eval();
    dut.clk = 1; dut.eval();
    dut.clk = 0; dut.eval();
    ++cycles;
}

void zero_inputs(Vdip_array_tb& dut) {
    dut.input_valid = 0;
    for (unsigned column = 0; column < size; ++column) {
        dut.data_in[column] = 0;
        dut.sum_in[column] = 0;
        dut.weight_in[column] = 0;
    }
}

void shadow_row(Vdip_array_tb& dut, const Matrix& weight, unsigned load_cycle) {
    // The host rotates each column before sending physical rows bottom first.
    const unsigned row = size - 1u - load_cycle;
    for (unsigned column = 0; column < size; ++column)
        dut.weight_in[column] = std::uint32_t(weight[(row + column) % size][column]) &
                                ((1u << weight_bits) - 1u);
}

void commit(Vdip_array_tb& dut) {
    zero_inputs(dut);
    dut.store_weight_req = 0;
    dut.weight_commit = 1;
    tick(dut);
    dut.weight_commit = 0;
}

void load(Vdip_array_tb& dut, const Matrix& weight) {
    zero_inputs(dut);
    dut.weight_commit = 0;
    dut.store_weight_req = 1;
    for (unsigned cycle = 0; cycle < size; ++cycle) {
        shadow_row(dut, weight, cycle);
        tick(dut);
    }
    commit(dut);
}

Sums reference(const Matrix& input, const Matrix& weight, const Sums& prior, bool count_overflow = true) {
    Sums output(input.size(), std::vector<std::uint32_t>(size));
    for (unsigned row = 0; row < input.size(); ++row)
        for (unsigned column = 0; column < size; ++column) {
            std::int64_t sum = signed32(prior[row][column]);
            for (unsigned k = 0; k < size; ++k)
                sum += std::int64_t(input[row][k]) * std::int64_t(weight[k][column]);
            if (count_overflow) overflow_values += sum < -0x80000000ll || sum > 0x7fffffffll;
            output[row][column] = static_cast<std::uint32_t>(sum);
        }
    return output;
}

Sums stream(Vdip_array_tb& dut, const Matrix& input, const Matrix& weight,
            const Sums& injected, const Sums& expected_prior, const Matrix* next_weight,
            bool gaps) {
    const auto expected = reference(input, weight, expected_prior);
    Sums output(input.size(), std::vector<std::uint32_t>(size));
    std::vector<int> row_at_cycle;
    for (unsigned row = 0; row < input.size(); ++row) {
        if (gaps && row % 3u == 1u) row_at_cycle.push_back(-1);
        row_at_cycle.push_back(static_cast<int>(row));
    }
    const unsigned input_cycles = row_at_cycle.size();
    row_at_cycle.resize(input_cycles + size + 2u, -1);
    for (unsigned cycle = 0; cycle < row_at_cycle.size(); ++cycle) {
        zero_inputs(dut);
        const int row = row_at_cycle[cycle];
        dut.input_valid = row >= 0;
        if (row >= 0)
            for (unsigned column = 0; column < size; ++column) {
                dut.data_in[column] = std::uint32_t(input[row][column]) & ((1u << data_bits) - 1u);
                dut.sum_in[column] = injected[row][column];
            }
        dut.store_weight_req = next_weight && cycle < size;
        if (dut.store_weight_req) {
            shadow_row(dut, *next_weight, cycle);
            ++overlapped_weight_cycles;
        }
        tick(dut);
        const int expected_row = cycle + 1u >= size ? row_at_cycle[cycle + 1u - size] : -1;
        require(bool(dut.valid_rows & (1u << (size-1u))) == (expected_row >= 0),
                "Complete row valid timing differs");
        for (unsigned column = 0; column < size; ++column) {
            const std::uint32_t value = expected_row >= 0 ? expected[expected_row][column] : 0u;
            require(dut.sum_out[column] == value,
                    "Matrix value or cycle mismatch: case=" + std::to_string(cases) +
                    " cycle=" + std::to_string(cycle) + " row=" + std::to_string(expected_row) +
                    " column=" + std::to_string(column) + " expected=" + std::to_string(value) +
                    " actual=" + std::to_string(dut.sum_out[column]));
            if (expected_row >= 0) output[expected_row][column] = dut.sum_out[column];
            ++checks;
        }
        rows_checked += expected_row >= 0;
    }
    dut.store_weight_req = 0;
    return output;
}

std::int32_t operand(unsigned bits, unsigned pattern, unsigned index) {
    const std::int32_t minimum = -(1 << (bits - 1u));
    const std::int32_t maximum = (1 << (bits - 1u)) - 1;
    if (pattern == 1u) return minimum;
    if (pattern == 2u) return maximum;
    if (pattern == 3u) return index % 2u ? maximum : minimum;
    if (pattern == 4u) return static_cast<std::int32_t>((index * 13u + 3u) % 23u) - 11;
    const std::uint32_t raw = random_values() & ((1u << bits) - 1u);
    return raw < (1u << (bits - 1u)) ? static_cast<std::int32_t>(raw)
                                    : static_cast<std::int32_t>(raw) - (1 << bits);
}

void run_case(Vdip_array_tb& dut, unsigned rows, unsigned blocks,
              unsigned pattern, bool overlap, bool gaps) {
    std::vector<Matrix> inputs, weights;
    for (unsigned block = 0; block < blocks; ++block) {
        Matrix input(rows, std::vector<std::int32_t>(size));
        Matrix weight(size, std::vector<std::int32_t>(size));
        for (unsigned row = 0; row < rows; ++row)
            for (unsigned k = 0; k < size; ++k)
                input[row][k] = operand(data_bits, pattern, block * rows * size + row * size + k);
        for (unsigned k = 0; k < size; ++k)
            for (unsigned column = 0; column < size; ++column)
                weight[k][column] = operand(weight_bits, pattern == 2u ? 1u : pattern,
                                           block * size * size + k * size + column);
        inputs.push_back(std::move(input));
        weights.push_back(std::move(weight));
    }
    Sums injected(rows, std::vector<std::uint32_t>(size));
    for (unsigned row = 0; row < rows; ++row)
        for (unsigned column = 0; column < size; ++column)
            injected[row][column] = pattern == 1u ? 0x7fffffffu : pattern == 2u ? 0x80000000u : random_values();
    Sums expected = injected;
    load(dut, weights[0]);
    for (unsigned block = 0; block < blocks; ++block) {
        if (block) {
            if (overlap) commit(dut);
            else load(dut, weights[block]);
            partial_injections += std::uint64_t(rows) * size;
        }
        const Matrix* next = overlap && block + 1u < blocks ? &weights[block + 1u] : nullptr;
        const Sums output = stream(dut, inputs[block], weights[block], injected, expected, next, gaps);
        expected = reference(inputs[block], weights[block], expected, false);
        injected = output;
    }
    ++cases;
}

void reset(Vdip_array_tb& dut) {
    zero_inputs(dut);
    dut.weight_commit = dut.store_weight_req = 0;
    dut.rst_n = 0;
    tick(dut); tick(dut);
    require(dut.row_select == 0 && dut.valid_rows == 0, "Reset must initialize row selectors");
    ++reset_checks;
    dut.rst_n = 1;
}

void run_wave_case(Vdip_array_tb& dut, unsigned bubble, bool gaps, bool delayed_load) {
    reset(dut);
    constexpr unsigned tiles = 4;
    std::array<Matrix, tiles> weights;
    for (unsigned tile=0; tile<tiles; ++tile) {
        weights[tile] = Matrix(size, std::vector<std::int32_t>(size));
        for (unsigned k=0; k<size; ++k)
            for (unsigned column=0; column<size; ++column)
                weights[tile][k][column] = operand(weight_bits, 0, tile*size*size+k*size+column);
    }
    dut.store_weight_req = 1;
    for (unsigned cycle=0; cycle<size; ++cycle) {
        shadow_row(dut, weights[0], cycle);
        tick(dut);
    }
    dut.store_weight_req = 0;
    struct Stage {
        bool valid = false;
        unsigned tile = 0;
        bool select = false;
        std::array<std::uint32_t, size> sum{};
    };
    std::array<Stage, size> stages{};
    bool input_select = false;
    auto step = [&](int tile, unsigned row, bool change, int load_tile, unsigned load_cycle) {
        zero_inputs(dut);
        dut.weight_commit = change;
        dut.store_weight_req = load_tile >= 0;
        if (load_tile >= 0) shadow_row(dut, weights[load_tile], load_cycle);
        if (change) { input_select = !input_select; ++wave_commits; }
        Stage incoming;
        incoming.select = input_select;
        incoming.valid = tile >= 0;
        incoming.tile = tile >= 0 ? unsigned(tile) : 0;
        if (tile >= 0) {
            dut.input_valid = 1;
            std::array<std::int32_t, size> input{};
            for (unsigned k=0; k<size; ++k) {
                input[k] = operand(data_bits, 0, row*size+k);
                dut.data_in[k] = std::uint32_t(input[k]) & ((1u << data_bits)-1u);
            }
            for (unsigned column=0; column<size; ++column) {
                dut.sum_in[column] = random_values();
                std::int64_t sum = signed32(dut.sum_in[column]);
                for (unsigned k=0; k<size; ++k)
                    sum += std::int64_t(input[k]) * weights[tile][k][column];
                incoming.sum[column] = std::uint32_t(sum);
            }
        }
        dut.clk=0; dut.eval();
        if (dut.store_weight_req && dut.row_load_enable != ((1u << size)-1u))
            ++protected_load_cycles;
        simultaneous_load_commits += change && dut.store_weight_req;
        for (unsigned stage=size-1u; stage>0; --stage) stages[stage]=stages[stage-1u];
        stages[0]=incoming;
        tick(dut);
        bool found_zero=false, found_one=false;
        for (unsigned stage=0; stage<size; ++stage) {
            require(bool(dut.row_select & (1u << stage)) == stages[stage].select,
                    "Row selector must follow the input registers");
            require(bool(dut.valid_rows & (1u << stage)) == stages[stage].valid,
                    "Row validity differs during a weight selection wave");
            ++row_select_checks;
            if (!stages[stage].valid) continue;
            found_zero |= !stages[stage].select;
            found_one |= stages[stage].select;
            for (unsigned column=0; column<size; ++column) {
                const auto expected = std::uint32_t(weights[stages[stage].tile][(stage+column)%size][column]) &
                                      ((1u << weight_bits)-1u);
                require(dut.selected_weight[stage*size+column] == expected,
                        "A valid physical row selected another tile's weight");
                ++selected_weight_checks;
            }
        }
        mixed_valid_cycles += found_zero && found_one;
        if (stages.back().valid) {
            for (unsigned column=0; column<size; ++column) {
                require(dut.sum_out[column] == stages.back().sum[column],
                        "Overlapping matrix streams differ at output");
                ++checks;
            }
            ++rows_checked;
        }
    };
    for (unsigned tile=0; tile<tiles; ++tile) {
        const unsigned count = tile+1u == tiles ? 1u : size+2u+tile*3u;
        unsigned row=0, cycle=0, shifts=0;
        bool first=true;
        while (row<count || (tile+1u<tiles && shifts<size)) {
            const bool valid = row<count && (!gaps || cycle%4u != 2u);
            const bool loading = tile+1u<tiles && shifts<size &&
                                 (!delayed_load || (cycle>=1u && cycle%3u != 1u));
            step(valid ? int(tile) : -1, row, first, loading ? int(tile+1u) : -1, shifts);
            if (valid) ++row;
            if (loading) ++shifts;
            first=false; ++cycle;
        }
        for (unsigned gap=0; gap<bubble; ++gap) step(-1, 0, false, -1, 0);
    }
    for (unsigned cycle=0; cycle<size; ++cycle) step(-1, 0, false, -1, 0);
    dut.weight_commit = dut.store_weight_req = 0;
    ++cases;
}
}  // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    try {
        Vdip_array_tb dut;
        dut.weight_commit = 0;
        dut.store_weight_req = 0;
        zero_inputs(dut);
        reset(dut);
        for (unsigned rows : {1u, size - 1u, size, size + 1u, 2u * size + 3u})
            for (unsigned pattern = 1u; pattern <= 4u; ++pattern)
                run_case(dut, rows, 3, pattern, true, false);
        for (unsigned test = 0; test < 48u; ++test)
            run_case(dut, 1u + random_values() % (4u * size + 3u),
                     1u + random_values() % 4u, 0, test % 2u == 0u, test % 3u == 0u);
        for (unsigned bubble : {0u, 1u})
            for (bool gaps : {false, true})
                for (bool delayed_load : {false, true})
                    run_wave_case(dut, bubble, gaps, delayed_load);
        dut.final();
        require(overflow_values && partial_injections && overlapped_weight_cycles,
                "Missing overflow, partial-sum injection, or concurrent weight loading");
        require(mixed_valid_cycles && protected_load_cycles && simultaneous_load_commits && reset_checks,
                "Missing row selection overlap, protected loading, or reset scenarios");
        std::cout << "{\"passed\":true,\"size\":" << size
                  << ",\"data_bits\":" << data_bits << ",\"weight_bits\":" << weight_bits
                  << ",\"first_output_cycles\":" << size << ",\"cases\":" << cases
                  << ",\"checked_values\":" << checks << ",\"output_rows\":" << rows_checked
                  << ",\"partial_sum_injections\":" << partial_injections
                  << ",\"overlapped_weight_cycles\":" << overlapped_weight_cycles
                  << ",\"overflow_reference_values\":" << overflow_values
                  << ",\"wave_commits\":" << wave_commits
                  << ",\"mixed_valid_cycles\":" << mixed_valid_cycles
                  << ",\"protected_load_cycles\":" << protected_load_cycles
                  << ",\"simultaneous_load_commits\":" << simultaneous_load_commits
                  << ",\"row_select_checks\":" << row_select_checks
                  << ",\"selected_weight_checks\":" << selected_weight_checks
                  << ",\"reset_checks\":" << reset_checks
                  << ",\"cycles\":" << cycles << "}\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
