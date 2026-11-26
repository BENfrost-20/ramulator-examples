#pragma once
#include <cstdint>
namespace abi {
constexpr unsigned COMMAND = 0;
constexpr unsigned GENERATION = 4;
constexpr unsigned N = 16;
constexpr unsigned BASE0 = 32;
constexpr unsigned CORE_CYCLES = 128;
constexpr unsigned DRAIN_CYCLES = 136;
constexpr unsigned BUSY = 1;
constexpr unsigned CORE_DONE = 2;
constexpr unsigned DRAINED = 4;
constexpr unsigned ERROR = 8;
constexpr unsigned GUARD = 256;
}
