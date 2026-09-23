# Se compila EN la placa (usa la API C++ del vendor instalada en /root/rpsa_client).
API = /root/rpsa_client/streaming_api
CXXFLAGS = -O2 -Wall -Wextra -std=c++17

capturar_eventos: capturar_eventos.cpp
	g++ $(CXXFLAGS) -isystem $(API) -o $@ $< -L$(API) -lstreaming_api -Wl,-rpath,$(API) -lpthread

clean:
	rm -f capturar_eventos

.PHONY: clean
