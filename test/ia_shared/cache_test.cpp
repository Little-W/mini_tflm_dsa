#include "Via_shared_cache_tb.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef TEST_BANK_BYTES
#define TEST_BANK_BYTES 2048
#endif
#ifndef TEST_BANK_COUNT
#define TEST_BANK_COUNT 7
#endif
#ifndef TEST_DMA_LANES
#define TEST_DMA_LANES 4
#endif

namespace {
constexpr int kSize = 16;
constexpr int kDmaLanes = TEST_DMA_LANES;
constexpr int kBankBytes = TEST_BANK_BYTES, kBanks = TEST_BANK_COUNT;
constexpr int kBankRows = kBankBytes/16, kMaxSlots = 4*kBankBytes/256;
using Word = std::array<std::uint32_t, 4>;
using Tile = std::array<std::array<std::int16_t, kSize>, kSize>;
std::array<Tile, kMaxSlots> expected{};
std::array<Word, (kBanks-1)*kBankRows> ps_expected{};
std::uint64_t cycles = 0, value_checks = 0, cycle_value_checks = 0;
std::uint64_t padding_checks = 0, s8_checks = 0, s16_checks = 0;
std::uint64_t control_checks = 0, port_checks = 0, ps_word_checks = 0;
std::uint64_t ia_read_words = 0, ia_write_words = 0, ia_write_bytes = 0;
std::uint64_t ps_read_words = 0, ps_write_words = 0;
std::uint64_t simultaneous_ia_rw = 0, simultaneous_ia_ps = 0;
std::uint64_t cross_word_writes = 0, mask_patterns = 0, wrapped_groups = 0;
std::uint64_t compact_groups = 0, wide_groups = 0, tile_checks = 0;
std::uint64_t initialization_groups = 0, final_groups = 0;
unsigned expected_columns[kMaxSlots]{};
int allocated_banks = 1, ps_banks = kBanks-1;
bool ps_background = false;

std::int16_t signed16(std::uint16_t value) {
    return static_cast<std::int16_t>(value < 32768U ? static_cast<int>(value)
                                                   : static_cast<int>(value) - 65536);
}
int signed8(unsigned value) { return value < 128U ? static_cast<int>(value)
                                                : static_cast<int>(value) - 256; }
void require(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message + " at cycle " + std::to_string(cycles));
}
unsigned bits(unsigned value) {
    unsigned result = 0;
    for (; value; value >>= 1) result += value & 1U;
    return result;
}
std::uint32_t pattern(std::uint32_t input) {
    input ^= input << 13;
    input ^= input >> 17;
    input ^= input << 5;
    return input;
}
void set_byte(Word& word, unsigned index, unsigned value) {
    const unsigned shift = (index % 4U) * 8U;
    word[index / 4U] = (word[index / 4U] & ~(0xffU << shift)) |
                      ((value & 0xffU) << shift);
}
void clear_write(Via_shared_cache_tb& dut) {
    for (int i = 0; i < kDmaLanes; ++i) dut.wr_valid[i] = 0;
}
void ps_drive_background(Via_shared_cache_tb& dut) {
    if (!ps_background) return;
    const unsigned ports = unsigned(ps_banks < 4 ? ps_banks : 4);
    dut.ps_read_en = (1U << ports) - 1U;
    dut.ps_write_en = (1U << ports) - 1U;
    for (unsigned port = 0; port < ports; ++port) {
        const unsigned bank = (cycles + port) % unsigned(ps_banks);
        const unsigned row = (cycles * 13U + port * 17U) % unsigned(kBankRows);
        dut.ps_read_addr[port] = bank * unsigned(kBankRows) + row;
    }
    for (unsigned port = 0; port < ports; ++port) {
        const unsigned bank = (cycles * 3U + port) % unsigned(ps_banks);
        unsigned row = (cycles * 7U + port * 23U + 64U) % unsigned(kBankRows);
        for (unsigned reader = 0; reader < ports; ++reader)
            if (dut.ps_read_addr[reader] == bank * unsigned(kBankRows) + row) row = (row + 1U) % unsigned(kBankRows);
        dut.ps_write_addr[port] = bank * unsigned(kBankRows) + row;
        for (unsigned part = 0; part < 4; ++part)
            dut.ps_write_data[port][part] = pattern(static_cast<std::uint32_t>(
                cycles * 131U + port * 31U + part + 1U));
    }
}
void tick(Via_shared_cache_tb& dut) {
    static Word pending_write[2]{};
    static unsigned pending_masks[2]{};
    static unsigned pending_address[2]{};
    static unsigned pending_en = 0;

    ps_drive_background(dut);
    dut.clk = 0;
    dut.eval();
    Word expected_write[2]{};
    unsigned masks[2]{};
    const unsigned row_word = (unsigned(dut.wr_slot) * 16U + unsigned(dut.wr_row)) *
                              (dut.compact_mode ? 1U : 2U);
    for (unsigned i = 0; i < kDmaLanes; ++i) {
        const unsigned column = unsigned(dut.wr_col_base) + i;
        if (!dut.wr_valid[i] || column >= 16U) continue;
        const unsigned port = dut.compact_mode ? 0U : column / 8U;
        const unsigned byte = dut.compact_mode ? column : (column % 8U) * 2U;
        const int value = signed16(dut.wr_data[i]);
        const unsigned raw = dut.compact_mode ?
            static_cast<unsigned>(value - signed16(dut.compact_offset)) & 255U :
            static_cast<unsigned>(value) & 65535U;
        masks[port] |= 1U << byte;
        set_byte(expected_write[port], byte, raw);
        if (!dut.compact_mode) {
            masks[port] |= 1U << (byte + 1U);
            set_byte(expected_write[port], byte + 1U, raw >> 8);
        }
        expected[dut.wr_slot][dut.wr_row][column] = static_cast<std::int16_t>(value);
        if(dut.wr_row==0) expected_columns[dut.wr_slot]=column+1U;
    }
    const unsigned expected_en = (masks[0] ? 1U : 0U) | (masks[1] ? 2U : 0U);
    require(dut.ia_write_en == pending_en, "Registered IA write enables");
    for (unsigned port = 0; port < 2; ++port) {
        if ((pending_en >> port) & 1U) {
            require(dut.ia_write_addr[port] == pending_address[port], "Registered IA write word address");
            require(dut.ia_write_mask[port] == pending_masks[port], "Registered IA byte write mask");
            for (unsigned byte=0;byte<16;++byte) if((pending_masks[port]>>byte)&1U) {
                const unsigned shift=(byte%4U)*8U;
                require(((dut.ia_write_data[port][byte/4U]>>shift)&255U)==
                        ((pending_write[port][byte/4U]>>shift)&255U), "Registered IA enabled byte");
            }
            port_checks += 6;
        }
    }
    if (dut.rst_n && !dut.cfg_valid) {
        require(dut.physical_read_count == bits(dut.ia_read_en) + bits(dut.ps_read_en),
                "Physical synchronous read count");
        require(dut.physical_write_count == bits(dut.ia_write_en) + bits(dut.ps_write_en),
                "Physical synchronous write count");
        require(!dut.physical_address_collision, "Physical SRAM address collision");
        control_checks += 3;
    }
    if (dut.ia_read_en) {
        require(dut.ia_read_en == (dut.compact_mode ? 1U : 3U), "IA row read ports");
        require(dut.ia_read_addr[0] < unsigned(allocated_banks * kBankRows), "IA read allocation");
        if (!dut.compact_mode) {
            require(allocated_banks >= 2, "Wide IA requires two independently read banks");
            require(dut.ia_read_addr[1] == dut.ia_read_addr[0] + 1U,
                    "Wide IA second word address");
            require((dut.ia_read_addr[0] % allocated_banks) !=
                    (dut.ia_read_addr[1] % allocated_banks), "Wide IA read banks");
        }
    }
    ia_read_words += bits(dut.ia_read_en);
    ia_write_words += bits(dut.ia_write_en);
    ia_write_bytes += bits(masks[0]) + bits(masks[1]);
    ps_read_words += bits(dut.ps_read_en);
    ps_write_words += bits(dut.ps_write_en);
    simultaneous_ia_rw += dut.ia_read_en && dut.ia_write_en;
    simultaneous_ia_ps += (dut.ia_read_en || dut.ia_write_en) &&
                          (dut.ps_read_en || dut.ps_write_en);
    cross_word_writes += !dut.compact_mode && dut.wr_col_base == 7 && dut.ia_write_en == 3;

    Word read_value[4]{};
    for (unsigned port = 0; port < 4; ++port) {
        if ((dut.ps_read_en >> port) & 1U) read_value[port] = ps_expected[dut.ps_read_addr[port]];
        if ((dut.ps_write_en >> port) & 1U)
            for (unsigned part = 0; part < 4; ++part)
                ps_expected[dut.ps_write_addr[port]][part] = dut.ps_write_data[port][part];
    }
    dut.clk = 1;
    dut.eval();
    require(!dut.capacity_fault, "Shared RAM capacity fault");
    require(dut.shared_valid == dut.local_valid, "Local/shared row valid");
    require(dut.shared_init == dut.local_init, "Local/shared init");
    require(dut.shared_final == dut.local_final, "Local/shared final");
    require(dut.shared_tile_done == dut.local_tile_done, "Local/shared tile completion");
    require(dut.shared_l1_done == dut.local_l1_done, "Local/shared group completion");
    require(dut.shared_tile_start == dut.local_tile_start, "Local/shared tile start");
    control_checks += 6;
    for (unsigned lane = 0; lane < 16; ++lane) {
        require(dut.shared_out[lane] == dut.local_out[lane],
                "Local/shared row value at lane " + std::to_string(lane));
        ++cycle_value_checks;
    }
    for (unsigned bank = 0; bank < 4; ++bank)
        if ((dut.ps_read_en >> bank) & 1U) {
            for (unsigned part = 0; part < 4; ++part)
                require(dut.ps_read_data[bank][part] == read_value[bank][part],
                        "PS read value during IA traffic");
            ++ps_word_checks;
        }
    pending_en=dut.rst_n ? expected_en : 0U;
    for (unsigned port=0;port<2;++port) {
        pending_write[port]=expected_write[port];pending_masks[port]=masks[port];pending_address[port]=row_word+port;
    }
    dut.clk = 0;
    dut.eval();
    ++cycles;
}
void configure(Via_shared_cache_tb& dut, int banks, bool legacy = false) {
    ps_background = false;
    dut.ps_read_en = 0;
    dut.ps_write_en = 0;
    clear_write(dut);
    dut.l1_start = 0;
    dut.cfg_valid = 0;
    dut.rst_n = 0;
    tick(dut);
    tick(dut);
    allocated_banks = banks;
    ps_banks = kBanks - banks;
    dut.cfg_cache_blocks = legacy ? 0 : banks * (kBankBytes/512);
    dut.cfg_ia_banks = banks;
    dut.rst_n = 1;
    dut.cfg_valid = 1;
    tick(dut);
    dut.cfg_valid = 0;
    tick(dut);
    for (unsigned first_bank = 0; first_bank < unsigned(ps_banks); first_bank += 4U) {
        const unsigned ports = unsigned(ps_banks) - first_bank < 4U ?
            unsigned(ps_banks) - first_bank : 4U;
        for (unsigned row = 0; row < unsigned(kBankRows); ++row) {
            dut.ps_write_en = (1U << ports) - 1U;
            for (unsigned port = 0; port < ports; ++port) {
                dut.ps_write_addr[port] = (first_bank + port) * unsigned(kBankRows) + row;
                for (unsigned part = 0; part < 4; ++part)
                    dut.ps_write_data[port][part] = pattern(row * 71U + port * 13U + part);
            }
            tick(dut);
        }
    }
    dut.ps_write_en = 0;
    ps_background = true;
    for (int slot = 0; slot < kMaxSlots; ++slot) dut.slot_rows[slot] = 16;
}
void drive_write(Via_shared_cache_tb& dut, int slot, int row, int column,
                 unsigned mask, const std::array<std::int16_t, 4>& values) {
    clear_write(dut);
    dut.wr_slot = slot;
    dut.wr_row = row;
    dut.wr_col_base = column;
    for (unsigned i = 0; i < 4; ++i) {
        dut.wr_valid[i] = (mask >> i) & 1U;
        dut.wr_data[i] = static_cast<std::uint16_t>(values[i]);
    }
}
void fill_slots(Via_shared_cache_tb& dut, int slots,
                const std::function<std::int16_t(int, int, int)>& value) {
    // 压缩行按全部输入通道写入；宽元素行保留跨存储字边界的四通道测试。
    const int lanes = dut.compact_mode ? kDmaLanes : 4;
    for (int slot = 0; slot < slots; ++slot)
        for (int row = 0; row < 16; ++row)
            for (int col = 0; col < 16; col += lanes) {
                clear_write(dut);
                dut.wr_slot = slot;
                dut.wr_row = row;
                dut.wr_col_base = col;
                for (int lane = 0; lane < lanes; ++lane) {
                    dut.wr_valid[lane] = col + lane < 16;
                    dut.wr_data[lane] = static_cast<std::uint16_t>(value(slot, row, col + lane));
                }
                tick(dut);
            }
    clear_write(dut);
}
void read_group(Via_shared_cache_tb& dut, int first, int last, bool init = true,
                bool final = true, const std::function<void(int)>& concurrent = {},
                const std::function<void(std::int16_t)>& inspect = {}) {
    const int slots = allocated_banks * (kBankBytes/(dut.compact_mode ? 256 : 512));
    std::vector<std::pair<int, int>> order;
    std::vector<int> first_rows, last_rows;
    for (int slot = first;; slot = (slot + 1) % slots) {
        first_rows.push_back(static_cast<int>(order.size()));
        for (int row = 0; row < dut.slot_rows[slot]; ++row) order.emplace_back(slot, row);
        last_rows.push_back(static_cast<int>(order.size()) - 1);
        if (slot == last) break;
    }
    dut.l1_slot_start = first;
    dut.l1_slot_end = last;
    dut.l1_is_init = init;
    dut.l1_calc_done = final;
    int completed = 0, tile_completed = 0, first_count = 0;
    for (int step = 0; step < static_cast<int>(order.size()) + 3; ++step) {
        dut.l1_start = step == 0;
        if (concurrent) concurrent(step);
        dut.eval();
        bool expected_first = false;
        for (int index : first_rows) expected_first |= index == step;
        require(bool(dut.shared_tile_start) == expected_first, "Tile-start issue cycle");
        first_count += dut.shared_tile_start;
        tick(dut);
        for (int lane = 0; lane < 16; ++lane) {
            const int index = step - 1;
            const bool valid = index >= 0 && index < static_cast<int>(order.size());
            const auto value = valid && unsigned(lane)<expected_columns[order[index].first] ?
                expected[order[index].first][order[index].second][lane] : 0;
            require(signed16(dut.shared_out[lane]) == value,
                    "Independent row value, step " + std::to_string(step) +
                    ", lane " + std::to_string(lane));
            if (valid) {
                ++value_checks;
                padding_checks += value == 0;
                if (inspect) inspect(static_cast<std::int16_t>(value));
            }
            if (lane == 15) {
                require(bool(dut.shared_valid) == valid, "Complete-row valid cycle");
                require(bool(dut.shared_init) == (valid && init), "Init flag cycle");
                require(bool(dut.shared_final) == (valid && final), "Final flag cycle");
                bool expected_tile_done = false;
                for (int last_row : last_rows) expected_tile_done |= valid && index == last_row;
                require(bool(dut.shared_tile_done) == expected_tile_done, "Tile completion cycle");
                require(bool(dut.shared_l1_done) ==
                        (valid && index + 1 == static_cast<int>(order.size())), "Group completion cycle");
                control_checks += 5;
            }
        }
        completed += dut.shared_l1_done;
        tile_completed += dut.shared_tile_done;
    }
    dut.l1_start = 0;
    clear_write(dut);
    require(completed == 1, "Group completion count");
    require(tile_completed == static_cast<int>(first_rows.size()), "Tile completion count");
    require(first_count == tile_completed, "Tile start count");
    tile_checks += tile_completed;
    wrapped_groups += first > last;
    initialization_groups += init;
    final_groups += final;
    if (dut.compact_mode) ++compact_groups;
    else ++wide_groups;
}
void exhaustive(Via_shared_cache_tb& dut, int banks) {
    configure(dut, banks);
    dut.compact_mode = 1;
    const int compact_slots = banks * (kBankBytes/256);
    for (int offset = -127; offset <= 128; ++offset) {
        dut.compact_offset = static_cast<std::uint16_t>(offset);
        dut.wr_use_16bits = offset & 1;
        fill_slots(dut, compact_slots, [&](int slot, int row, int lane) {
            return static_cast<std::int16_t>(signed8(unsigned(row * 16 + lane + slot * 31) & 255U) + offset);
        });
        std::array<bool, 256> seen{};
        read_group(dut, 0, compact_slots - 1, offset & 1, offset & 2, {}, [&](std::int16_t value) {
            seen[static_cast<unsigned>(int(value) - offset) & 255U] = true;
            ++s8_checks;
        });
        for (bool present : seen) require(present, "Missing S8 value for offset");
    }
    if (banks == 1) return;
    dut.compact_mode = 0;
    dut.compact_offset = 0;
    dut.wr_use_16bits = 1;
    const int wide_slots = banks * (kBankBytes/512);
    std::array<bool, 65536> seen{};
    for (int batch = 0; batch < 65536 / (wide_slots * 256); ++batch) {
        fill_slots(dut, wide_slots, [&](int slot, int row, int lane) {
            return signed16(static_cast<std::uint16_t>(batch * wide_slots * 256 + slot * 256 + row * 16 + lane));
        });
        read_group(dut, 0, wide_slots - 1, batch & 1, batch & 2, {}, [&](std::int16_t value) {
            seen[static_cast<std::uint16_t>(value)] = true;
            ++s16_checks;
        });
    }
    for (bool present : seen) require(present, "Missing S16 bit pattern");
}
void tails_masks_and_overlap(Via_shared_cache_tb& dut, int banks) {
    for (int compact = 0; compact <= 1; ++compact) {
        if (!compact && banks == 1) continue;
        dut.compact_mode = compact;
        dut.compact_offset = static_cast<std::uint16_t>(compact ? -127 : 0);
        const int slots = banks * (kBankBytes/(compact ? 256 : 512));
        for (int slot = 0; slot < slots; ++slot) dut.slot_rows[slot] = 1 + (slot * 5 % 16);
        fill_slots(dut, slots, [&](int slot, int row, int lane) {
            if (row >= dut.slot_rows[slot] || lane > (slot * 3 % 16)) return std::int16_t(0);
            const int raw = signed8(unsigned(row * 17 + lane + slot) & 255U);
            return static_cast<std::int16_t>(compact ? raw - 127 : raw * 251);
        });
        read_group(dut, 0, slots - 1, false, true);
        read_group(dut, slots - 2, 1, true, false);

        for (int slot = 0; slot < slots; ++slot) dut.slot_rows[slot] = 16;
        for (int col = 0; col < 16; ++col)
            for (unsigned mask = 0; mask < 16; ++mask) {
                std::array<std::int16_t, 4> values{};
                for (unsigned i = 0; i < 4; ++i) {
                    const unsigned raw = unsigned(col) * 31U + mask * 11U + i * 53U;
                    values[i] = compact ? static_cast<std::int16_t>(signed8(raw & 255U) - 127)
                                        : signed16(static_cast<std::uint16_t>(pattern(raw)));
                }
                drive_write(dut, col % slots, (col + int(mask)) % 16, col, mask, values);
                tick(dut);
                ++mask_patterns;
            }
        clear_write(dut);
        read_group(dut, 0, slots - 1);

        read_group(dut, 0, slots / 2 - 1, true, true, [&](int step) {
            if (step < slots * 8) {
                const int slot = slots / 2 + step / 64;
                const int row = (step / 4) % 16;
                const int col = step % 4 * 4;
                std::array<std::int16_t, 4> values{};
                for (unsigned i = 0; i < 4; ++i) {
                    const unsigned raw = unsigned(step) * 19U + i * 37U + 3U;
                    values[i] = compact ? static_cast<std::int16_t>(signed8(raw & 255U) - 127)
                                        : signed16(static_cast<std::uint16_t>(pattern(raw)));
                }
                drive_write(dut, slot, row, col, 15, values);
            } else clear_write(dut);
        });
        read_group(dut, slots / 2, slots - 1, false, false);
    }
}
}  // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    try {
        Via_shared_cache_tb dut;
        for (int banks : {1, 2, 4}) {
            exhaustive(dut, banks);
            tails_masks_and_overlap(dut, banks);
        }
        configure(dut, 4, true);
        for (int compact = 0; compact <= 1; ++compact) {
            dut.compact_mode = compact;
            dut.compact_offset = compact ? 128 : 0;
            const int slots = compact ? kMaxSlots : kMaxSlots/2;
            fill_slots(dut, slots, [&](int slot, int row, int lane) {
                const unsigned raw = unsigned(slot * 127 + row * 31 + lane);
                return compact ? static_cast<std::int16_t>(signed8(raw & 255U) + 128)
                               : signed16(static_cast<std::uint16_t>(pattern(raw)));
            });
            read_group(dut, slots - 2, 1);
        }
        require(s8_checks == 256ULL * 7 * (kBankBytes/256) * 256, "S8 exhaustive value count");
        require(s16_checks == 2 * 65536, "S16 exhaustive value count");
        require(cross_word_writes > 0 && simultaneous_ia_rw > 0 && simultaneous_ia_ps > 0,
                "Missing concurrent or cross-word coverage");
        require(ps_read_words == ps_word_checks, "PS read comparison coverage");
        dut.final();
        std::cout << "{\"passed\":true,\"shared_data_ram_bytes\":" << kBankBytes*kBanks
                  << ",\"allocation_bank_bytes\":" << kBankBytes << ",\"physical_banks\":" << kBanks
                  << ",\"bank_width_bits\":128,\"bank_depth\":" << kBankRows << ",\"profiles\":[";
        for (int banks : {1,2,4}) {
            std::cout << (banks==1 ? "" : ",") << "{\"ia_banks\":" << banks
                      << ",\"ia_bytes\":" << banks*kBankBytes << ",\"ps_bytes\":" << (kBanks-banks)*kBankBytes
                      << ",\"compact_slots\":" << banks*kBankBytes/256
                      << ",\"wide_slots\":" << banks*kBankBytes/512
                      << ",\"compact_reuse\":" << banks*kBankBytes/512
                      << ",\"wide_reuse\":" << banks*kBankBytes/1024
                      << ",\"wide_supported\":" << (banks>=2 ? "true" : "false") << "}";
        }
        std::cout << "],"
                  << "\"s8_offsets_per_profile\":256,\"wide_profiles\":2,\"s16_bit_patterns_per_wide_profile\":65536,"
                  << "\"s8_value_checks\":" << s8_checks << ",\"s16_value_checks\":" << s16_checks
                  << ",\"value_checks\":" << value_checks << ",\"cycle_value_checks\":" << cycle_value_checks
                  << ",\"zero_checks\":" << padding_checks << ",\"control_checks\":" << control_checks
                  << ",\"port_checks\":" << port_checks << ",\"ps_word_checks\":" << ps_word_checks
                  << ",\"ia_read_words\":" << ia_read_words << ",\"ia_write_words\":" << ia_write_words
                  << ",\"ia_write_bytes\":" << ia_write_bytes << ",\"ps_read_words\":" << ps_read_words
                  << ",\"ps_write_words\":" << ps_write_words << ",\"simultaneous_ia_rw_cycles\":" << simultaneous_ia_rw
                  << ",\"simultaneous_ia_ps_cycles\":" << simultaneous_ia_ps
                  << ",\"wide_col7_cross_word_writes\":" << cross_word_writes
                  << ",\"mask_patterns\":" << mask_patterns << ",\"wrapped_groups\":" << wrapped_groups
                  << ",\"compact_groups\":" << compact_groups << ",\"wide_groups\":" << wide_groups
                  << ",\"tile_checks\":" << tile_checks << ",\"initialization_groups\":" << initialization_groups
                  << ",\"final_groups\":" << final_groups << ",\"legacy_default_groups\":2,\"cycles\":" << cycles << "}\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
