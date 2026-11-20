int main(int argc,char** argv) {
  Verilated::commandArgs(argc,argv);
  try {
    Simulation s;
    const std::string argument=Verilated::commandArgsPlusMatch("BOUNDARY_TRACE=");
    const std::string prefix="+BOUNDARY_TRACE=";
    check(argument.rfind(prefix,0)==0,"missing offset trace path");
    s.window_trace.open(argument.substr(prefix.size()));
    check(s.window_trace.good(),"cannot open offset trace");
    s.trace_enabled=true;
    unsigned scenarios=0;
    for(int32_t offset=-127;offset<=128;offset++) {
      const uint32_t base=0x2003+(scenarios%128)*0x1000;
      auto config=configuration(base,16,1);
      config[12]=static_cast<uint32_t>(offset);
      for(unsigned byte=0;byte<256;byte++)s.memory.at(base+byte)=uint8_t(byte);
      s.configure(config);s.random_memory=true;
      std::vector<Request> contiguous;
      for(unsigned position=0;position<16;position++)contiguous.push_back({position,0,16,position%4});
      const auto first=s.cycle,before=s.elements;
      s.run(contiguous,true);
      config=configuration(base+0x1000,3,3);
      config[12]=static_cast<uint32_t>(offset);
      s.configure(config);
      std::vector<Request> scattered;
      for(unsigned i=0;i<4;i++)scattered.push_back({unsigned(s.random()%64),
        unsigned(s.random()%27),1+unsigned(s.random()%16),i%4});
      s.run(scattered,true);
      std::printf("CASE offset_boundary offset=%d requests=20 values=%llu cycles=%llu\n",offset,
        static_cast<unsigned long long>(s.elements-before),static_cast<unsigned long long>(s.cycle-first));
      scenarios++;
    }
    check(s.accepted==s.completed && s.expected.empty() && !s.top.busy,"offset windows did not drain");
    s.trace_enabled=false;s.window_trace.close();
    std::printf("OFFSET_BOUNDARY_PASS scenarios=%u accepted=%llu completed=%llu elements=%llu cycles=%llu\n",
      scenarios,static_cast<unsigned long long>(s.accepted),static_cast<unsigned long long>(s.completed),
      static_cast<unsigned long long>(s.elements),static_cast<unsigned long long>(s.cycle));
    s.top.final();return 0;
  } catch(const std::exception& e) {std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}
}
