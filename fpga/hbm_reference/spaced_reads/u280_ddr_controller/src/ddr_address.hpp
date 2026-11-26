#pragma once

#include <array>
#include <cstdint>
#include <stdexcept>

namespace ddr {
constexpr std::uint64_t aperture = 0x1000000000ULL;
constexpr std::uint64_t capacity = 1ULL << 34;
constexpr std::uint64_t alignment = 1ULL << 18;
constexpr std::uint64_t slab_size = 2 * alignment;
constexpr std::array<const char*, 3> names{"same-row", "same-bank", "different-bank"};
constexpr std::array<std::uint64_t, 3> masks{0x100, 0x20000, 0x200};
constexpr std::uint32_t word_a = 0x12345678;
constexpr std::uint32_t word_b = 0x89abcdef;

constexpr bool valid_anchor(std::uint64_t address) {
    return address >= aperture && address < aperture + capacity &&
           (address - aperture) % alignment == 0;
}

struct Location {
    unsigned row, group, bank, column;
};

constexpr Location decode(std::uint64_t address) {
    const auto a = address - aperture;
    return {unsigned(a >> 17), unsigned((a >> 6) & 3), unsigned((a >> 9) & 3),
            unsigned(((a >> 11) & 63) << 4 | ((a >> 8) & 1) << 3 | ((a >> 3) & 7))};
}

// RoBaRaCoCh consumes 7 burst-column bits, then BG, BA and row.
constexpr std::uint64_t model_address(std::uint64_t address) {
    const auto loc = decode(address);
    return (std::uint64_t(loc.row) << 17) | (loc.bank << 15) |
           (loc.group << 13) | (loc.column << 3) | (address & 7);
}
}
