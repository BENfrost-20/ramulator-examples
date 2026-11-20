#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <ostream>
#include <stdexcept>
#include <string>

namespace probe_trace {
constexpr unsigned signature_register = 0x90;
constexpr std::uint32_t signature = 0x41584931;
enum Event { START, AR, R, AW, W, B, DONE, DRAIN, AR_VALID, AW_VALID, W_VALID,
             R_VALID, B_VALID, event_count };
constexpr std::array<const char*, event_count> names = {
    "START", "AR", "R", "AW", "W", "B", "DONE", "DRAIN",
    "AR_VALID", "AW_VALID", "W_VALID", "R_VALID", "B_VALID"
};

struct Snapshot {
    std::array<std::uint32_t, event_count> cycle{};
    std::uint64_t araddr, awaddr;
    std::uint32_t attributes;
};

template <typename Read>
Snapshot read_snapshot(Read read, std::uint64_t core, std::uint64_t drain,
                       std::uint64_t buffer_address) {
    const auto seen = read(0x94);
    const auto flags = read(0x98);
    if (seen != (1u << event_count) - 1 || flags)
        throw std::runtime_error("Incomplete or repeated AXI trace: seen=" +
                                 std::to_string(seen) + " flags=" + std::to_string(flags));

    Snapshot snapshot{};
    for (unsigned i = 0; i < event_count; ++i)
        snapshot.cycle[i] = read(0xa0 + 4 * i);
    const auto low_ar = read(0xd4), high_ar = read(0xd8);
    const auto low_aw = read(0xdc), high_aw = read(0xe0);
    snapshot.araddr = (std::uint64_t(high_ar) << 32) | low_ar;
    snapshot.awaddr = (std::uint64_t(high_aw) << 32) | low_aw;
    snapshot.attributes = read(0xe4);

    const auto& c = snapshot.cycle;
    if (c[START] != 0 || c[DONE] != core || c[DRAIN] != drain ||
        c[AR_VALID] > c[AR] || c[R_VALID] > c[R] || c[AW_VALID] > c[AW] ||
        c[W_VALID] > c[W] || c[B_VALID] > c[B] || c[AR] > c[R] ||
        c[R] > std::min(c[AW], c[W]) || std::max(c[AW], c[W]) > c[B] ||
        c[B] > c[DRAIN] || c[DONE] >= c[DRAIN])
        throw std::runtime_error("AXI trace ordering or wrapper counters do not agree");
    if (snapshot.araddr != buffer_address || snapshot.awaddr != buffer_address)
        throw std::runtime_error("AXI trace addresses differ from the programmed data address");
    const auto a = snapshot.attributes;
    if ((a & 0x3ff0) != 0x30f0 || ((a ^ (a >> 1)) & 0x5))
        throw std::runtime_error("Unexpected AXI strobe, last, ID or response in trace");
    return snapshot;
}

inline void write_events(std::ostream& out, const Snapshot& data, unsigned repetition) {
    const auto a = data.attributes;
    for (unsigned i = 0; i < event_count; ++i) {
        out << "{\"event\":\"" << names[i] << "\",\"n\":1,\"repetition\":" << repetition
            << ",\"cycles_from_start\":" << data.cycle[i];
        switch (i) {
        case AR: out << ",\"axi_addr\":" << data.araddr << ",\"id\":" << (a & 1); break;
        case R: out << ",\"axi_addr\":" << data.araddr << ",\"id\":" << ((a >> 1) & 1)
                    << ",\"resp\":" << ((a >> 8) & 3); break;
        case AW: out << ",\"axi_addr\":" << data.awaddr << ",\"id\":" << ((a >> 2) & 1); break;
        case W: out << ",\"wstrb\":" << ((a >> 4) & 15); break;
        case B: out << ",\"axi_addr\":" << data.awaddr << ",\"id\":" << ((a >> 3) & 1)
                    << ",\"resp\":" << ((a >> 10) & 3); break;
        }
        out << "}\n";
    }
    out.flush();
    if (!out) throw std::runtime_error("Cannot write board-axi.jsonl");
}
}
