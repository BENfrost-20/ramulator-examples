#include <stdint.h>
#ifdef BANKED
#pragma HLS bus mode = m_axi bank_number = 2 chunk_size = 256
#else
#pragma HLS bus mode = m_axi
#endif
#pragma HLS interface port = data mode = bus
void __attribute__((noinline)) memory_probe(uint32_t *data, unsigned n)
{
  for (unsigned i = 0; i < n; ++i)
    data[i] = (data[i] ^ 0x13579bdfu) + i;
}
#include <stdlib.h>
#ifdef __BAMBU_SIM__
#include <mdpi/mdpi_user.h>
#endif
int main(void)
{
  uint32_t data[513];
  for (unsigned i = 0; i < 513; ++i) data[i] = 7u * i + 3u;
#ifdef __BAMBU_SIM__
  m_param_alloc(0, sizeof(data));
#endif
  memory_probe(data, 513);
  for (unsigned i = 0; i < 513; ++i)
    if (data[i] != (((7u * i + 3u) ^ 0x13579bdfu) + i)) abort();
  return 0;
}
