#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <vector>
#include <fstream>
#include <filesystem>
#include <string>
using Bytes = std::vector<std::uint8_t>;
inline std::vector<Bytes> pack(const Bytes& bytes, unsigned banks) {
 if(banks!=1 && banks!=2) throw std::runtime_error("Invalid bank count");
 std::vector<Bytes> result(banks);
 for(std::size_t pos=0;pos<bytes.size();pos+=256) {
  auto& dst=result[(pos/256)%banks];
  auto len=std::min<std::size_t>(256,bytes.size()-pos);
  dst.insert(dst.end(),bytes.begin()+pos,bytes.begin()+pos+len);
 }
 return result;
}
inline Bytes unpack(const std::vector<Bytes>& banks, std::size_t size) {
 if(banks.size()!=1 && banks.size()!=2) throw std::runtime_error("Invalid bank count");
 Bytes result(size);std::vector<std::size_t> offsets(banks.size());
 for(std::size_t pos=0;pos<size;pos+=256) {
  auto b=(pos/256)%banks.size(), len=std::min<std::size_t>(256,size-pos);
  if(offsets[b]+len>banks[b].size()) throw std::runtime_error("Truncated stripe");
  std::copy_n(banks[b].begin()+offsets[b],len,result.begin()+pos);offsets[b]+=len;
 }
 return result;
}

// Retain exact input bytes so collectors can SHA-256 the measured input.
inline std::string save_input(const Bytes& bytes,unsigned n,unsigned rep,const std::filesystem::path& directory=".") {
 auto name="input-"+std::to_string(n)+"-"+std::to_string(rep)+".bin";
 std::ofstream stream(directory/name,std::ios::binary|std::ios::trunc);
 if(!stream)throw std::runtime_error("Cannot record input bytes");
 if(!bytes.empty())stream.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
 if(!stream)throw std::runtime_error("Cannot finish input recording");
 return name;
}
