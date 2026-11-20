# Se compila EN la placa. Copia de demo de scripts_campo/c/capturar_eventos
# con --en-vivo (solo rama demo-presentacion; no va a campo).
API = /root/rpsa_client/streaming_api
CAMPO_C = /root/scripts_campo/c
CXXFLAGS = -O2 -Wall -Wextra -std=c++17

capturar_eventos_demo: capturar_eventos_demo.cpp
	g++ $(CXXFLAGS) -isystem $(API) -I$(CAMPO_C) -o $@ $< -L$(API) -lstreaming_api -Wl,-rpath,$(API) -lpthread

clean:
	rm -f capturar_eventos_demo

.PHONY: clean
