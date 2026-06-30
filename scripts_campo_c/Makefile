CXX      = g++
CXXFLAGS = -O2 -Wall -std=c++20 -I/opt/redpitaya/include
LDFLAGS  = -L/opt/redpitaya/lib -lrp -Wl,-rpath,/opt/redpitaya/lib

TARGETS  = hello_rp query_axi capture_axi capture_armkeep

all: $(TARGETS)

hello_rp: hello_rp.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)

query_axi: query_axi.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)

capture_axi: capture_axi.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)

capture_armkeep: capture_armkeep.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)

clean:
	rm -f $(TARGETS)
