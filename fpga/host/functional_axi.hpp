#pragma once

#include <cstdint>
#include <deque>
#include <fstream>
#include <optional>

#include "abi.hpp"
#include "buffers.hpp"

#ifdef FPGA_WITH_RAMULATOR
#include "ramulator_timing.hpp"
static constexpr const char* simulation_mode = "ramulator";
static std::unique_ptr<RamulatorTiming> timing;
static std::ofstream axi_trace;
static unsigned trace_n, trace_rep;
static std::uint64_t model_data_base;

static void trace_axi(const char* event, std::uint64_t cycle,
                      std::optional<std::uint64_t> address = {}, std::optional<unsigned> id = {},
                      std::optional<std::uint64_t> model_address = {},
                      std::optional<std::uint64_t> dram_tick = {}) {
    axi_trace << "{\"event\":\"" << event << "\",\"n\":" << trace_n
              << ",\"repetition\":" << trace_rep << ",\"axi_cycle\":" << cycle
              << ",\"dram_tick\":" << dram_tick.value_or(timing->ticks());
    if (address) axi_trace << ",\"axi_addr\":" << *address;
    if (id) axi_trace << ",\"id\":" << *id;
    if (model_address) axi_trace << ",\"ramulator_addr\":" << *model_address;
    axi_trace << "}\n";
}
#else
static constexpr const char* simulation_mode = "functional_axi_ram";

static void trace_axi(const char*, std::uint64_t, std::optional<std::uint64_t> = {},
                      std::optional<unsigned> = {}) {}
#endif

struct Port {
    Bytes* bytes;
    std::uint64_t base;

    bool rv = false, bv = false;
    unsigned rid = 0, bid = 0, rd = 0;
    std::uint64_t reads = 0, writes = 0;

    struct Address {
        std::uint64_t value;
        unsigned id;
        int bytes;
    };
    struct Data {
        unsigned value;
        unsigned strobe;
    };
    std::optional<Address> pending_read;
    Address read_response{}, write_response{};
    std::deque<Address> aw;
    std::deque<Data> w;

#ifdef FPGA_WITH_RAMULATOR
    bool read_submitted = false;
    std::optional<std::uint64_t> read_completed_tick;
#else
    std::uint64_t read_due = 0, write_due = 0;
#endif

    bool arready(std::uint64_t cycle) const {
        return !pending_read && !rv && (is_timed || cycle % 3 != 0);
    }

    bool awready(std::uint64_t cycle) const {
        return aw.size() < 4 && (is_timed || cycle % 5 != 0);
    }

    bool wready(std::uint64_t cycle) const {
        return w.size() < 4 && (is_timed || cycle % 4 != 0);
    }

    void check(std::uint64_t address, unsigned size, unsigned len) const {
        if (len) throw std::runtime_error("AXI backend requires single-beat transfers");
        if (size > 2 || address < base || address - base >= bytes->size()
                || (1u << size) > bytes->size() - (address - base)) {
            throw std::runtime_error("Out-of-range AXI address or unsupported transfer size");
        }
    }

    void ar(std::uint64_t address, unsigned id, unsigned size, unsigned len, std::uint64_t cycle) {
        check(address, size, len);
        pending_read = Address{address, id, 1 << size};
        ++reads;
#ifndef FPGA_WITH_RAMULATOR
        read_due = cycle + 2 + cycle % 5;
#endif
        trace_axi("AR", cycle, address, id);
    }

    void write_addr(std::uint64_t address, unsigned id, unsigned size, unsigned len,
                    std::uint64_t cycle) {
        check(address, size, len);
        aw.push_back({address, id, 1 << size});
        ++writes;
        trace_axi("AW", cycle, address, id);
    }

    void write_data(unsigned data, unsigned strobe, bool last, std::uint64_t cycle) {
        if (!last) throw std::runtime_error("Missing WLAST");
        w.push_back({data, strobe});
        trace_axi("W", cycle);
    }

    void consume_read(std::uint64_t cycle) {
        trace_axi("R", cycle, read_response.value, rid);
        rv = false;
    }

    void consume_write(std::uint64_t cycle) {
        trace_axi("B", cycle, write_response.value, bid);
        bv = false;
    }

    void update(std::uint64_t cycle) {
#ifdef FPGA_WITH_RAMULATOR
        if (pending_read && !read_submitted) {
            const auto request = *pending_read;
            const auto address = model_address(request.value);
            read_submitted = timing->read(address, request.bytes, [this](Ramulator::Request&) {
                read_completed_tick = timing->ticks();
            });
            if (read_submitted) {
                // Keep the bytes at acceptance even if a later write changes the slab.
                rd = load_word(request.value);
                trace_axi("read_accepted", cycle, request.value, request.id, address);
            }
        }
        if (read_completed_tick) {
            const auto request = *pending_read;
            trace_axi("read_completed", cycle, request.value, request.id, model_address(request.value),
                      read_completed_tick);
            publish_read();
            read_submitted = false;
            read_completed_tick.reset();
        }
        if (!bv && !aw.empty() && !w.empty()) {
            const auto request = aw.front();
            const auto address = model_address(request.value);
            if (timing->write(address, request.bytes)) {
                commit_write();
                trace_axi("write_accepted", cycle, request.value, request.id, address);
                bv = true;
            }
        }
#else
        if (pending_read && cycle >= read_due) {
            rd = load_word(pending_read->value);
            publish_read();
        }
        if (!bv && !aw.empty() && !w.empty() && !write_due) {
            commit_write();
            write_due = cycle + 3;
        }
        if (write_due && cycle >= write_due) {
            bv = true;
            write_due = 0;
        }
#endif
    }

    bool empty() const {
#ifndef FPGA_WITH_RAMULATOR
        if (write_due) return false;
#endif
        return !rv && !bv && !pending_read && aw.empty() && w.empty();
    }

private:
#ifdef FPGA_WITH_RAMULATOR
    static constexpr bool is_timed = true;

    std::uint64_t model_address(std::uint64_t address) const {
        // Reproduce the logical addresses of the native Bambu probe.
        return model_data_base - abi::GUARD + (address - base);
    }
#else
    static constexpr bool is_timed = false;
#endif

    unsigned load_word(std::uint64_t address) const {
        const auto offset = (address - base) & ~std::uint64_t{3};
        unsigned data = 0;
        for (unsigned i = 0; i < 4; ++i) data |= unsigned((*bytes)[offset + i]) << (8 * i);
        return data;
    }

    void publish_read() {
        read_response = *pending_read;
        rid = read_response.id;
        rv = true;
        pending_read.reset();
    }

    void commit_write() {
        write_response = aw.front();
        const auto data = w.front();
        aw.pop_front();
        w.pop_front();
        const auto offset = (write_response.value - base) & ~std::uint64_t{3};
        for (unsigned i = 0; i < 4; ++i) {
            if (data.strobe & (1u << i)) (*bytes)[offset + i] = (data.value >> (8 * i)) & 255;
        }
        bid = write_response.id;
    }
};
