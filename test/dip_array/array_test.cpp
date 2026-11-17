#include "Vws_systolic_array.h"
#include "verilated.h"

#include <algorithm>
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
std::mt19937 random_values(0x64697000u + size * 31u + data_bits * 7u + weight_bits);

void require(bool value, const std::string& message) {
    if (!value) throw std::runtime_error(message);
}

std::int64_t signed32(std::uint32_t value) {
    return value < 0x80000000u ? std::int64_t(value) : std::int64_t(value) - 0x100000000ll;
}

void tick(Vws_systolic_array& dut) {
    dut.clk = 0; dut.eval();
    dut.clk = 1; dut.eval();
    dut.clk = 0; dut.eval();
    ++cycles;
}

void zero_inputs(Vws_systolic_array& dut) {
    for (unsigned column = 0; column < size; ++column) {
        dut.data_in[column] = 0;
        dut.sum_in[column] = 0;
        dut.weight_in[column] = 0;
    }
}

void shadow_row(Vws_systolic_array& dut, const Matrix& weight, unsigned load_cycle) {
    // The host rotates each column before sending physical rows bottom first.
    const unsigned row = size - 1u - load_cycle;
    for (unsigned column = 0; column < size; ++column)
        dut.weight_in[column] = std::uint32_t(weight[(row + column) % size][column]) &
                                ((1u << weight_bits) - 1u);
}

void commit(Vws_systolic_array& dut) {
    zero_inputs(dut);
    dut.store_weight_req = 0;
    dut.weight_commit = 1;
    tick(dut);
    dut.weight_commit = 0;
    for (unsigned column = 0; column < size; ++column) {
        require(dut.sum_out[column] == 0, "Weight commit must clear the arithmetic pipeline");
        ++checks;
    }
}

void load(Vws_systolic_array& dut, const Matrix& weight) {
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

Sums stream(Vws_systolic_array& dut, const Matrix& input, const Matrix& weight,
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

void run_case(Vws_systolic_array& dut, unsigned rows, unsigned blocks,
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
}  // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    try {
        Vws_systolic_array dut;
        dut.weight_commit = 0;
        dut.store_weight_req = 0;
        zero_inputs(dut);
        for (unsigned rows : {1u, size - 1u, size, size + 1u, 2u * size + 3u})
            for (unsigned pattern = 1u; pattern <= 4u; ++pattern)
                run_case(dut, rows, 3, pattern, true, false);
        for (unsigned test = 0; test < 48u; ++test)
            run_case(dut, 1u + random_values() % (4u * size + 3u),
                     1u + random_values() % 4u, 0, test % 2u == 0u, test % 3u == 0u);
        dut.final();
        require(overflow_values && partial_injections && overlapped_weight_cycles,
                "Missing overflow, partial-sum injection, or concurrent weight loading");
        std::cout << "{\"passed\":true,\"size\":" << size
                  << ",\"data_bits\":" << data_bits << ",\"weight_bits\":" << weight_bits
                  << ",\"first_output_cycles\":" << size << ",\"cases\":" << cases
                  << ",\"checked_values\":" << checks << ",\"output_rows\":" << rows_checked
                  << ",\"partial_sum_injections\":" << partial_injections
                  << ",\"overlapped_weight_cycles\":" << overlapped_weight_cycles
                  << ",\"overflow_reference_values\":" << overflow_values
                  << ",\"cycles\":" << cycles << "}\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
