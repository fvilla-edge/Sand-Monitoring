// generador_pulsos.h — modo de PRUEBA de capturar_eventos (Fase 3):
// genera por OUT1 (streaming de DAC del vendor) una serie de pulsos conocidos
// para validar con un loopback OUT1->IN1 que se guarda la ventana correcta.
//
// Va dentro del mismo proceso que la captura, compartiendo el
// ConfigStreamClient: el streaming-server acepta una sola conexion de
// configuracion — si se conecta una segunda, a la primera le llega "End of
// file" y la libreria del vendor muere por SIGSEGV (visto con strace en HW,
// 2026-09-23). Tampoco sirve `generate`: con stream_app no hay generador de
// funciones clasico (en 0x40200000 esta el bloque GPIO).
//
// Pulso: senoidal amortiguada A*sin(2*pi*f*t)*exp(-t/tau), dentro de la banda
// del pasabanda (50-400 kHz). Periodo "raro" (default 2.37s, no multiplo de
// 50ms) para que cada pulso caiga en una posicion distinta de su ventana. El
// DAC se alimenta por callback (modo sink): ceros salvo donde toca un pulso,
// asi la cadencia es exacta en muestras del DAC.
#ifndef GENERADOR_PULSOS_H
#define GENERADOR_PULSOS_H

#include "callbacks.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <algorithm>
#include <cstring>
#include <string>
#include <vector>

struct ParamsPulsos {
    int n = 0;  // 0 = modo prueba apagado
    double periodo_s = 2.37, freq = 150000, tau_us = 20, amp = 0.8, rate = 7812500;
    std::string log = "pulsos.csv";
};

class GeneradorPulsos : public DACCallback {
   public:
    GeneradorPulsos(const ParamsPulsos& p, FILE* log) : p_(p), log_(log) {
        periodo_ = (uint64_t)llround(p.periodo_s * p.rate);
        size_t largo = (size_t)(p.tau_us * 1e-6 * 5 * p.rate);  // 5 tau
        for (size_t i = 0; i < largo; i++) {
            double t = i / p.rate;
            pulso_.push_back((int16_t)lround(p.amp * 32767 * sin(2 * M_PI * p.freq * t) *
                                             exp(-t / (p.tau_us * 1e-6))));
        }
        primero_ = periodo_ / 2;  // medio periodo de silencio al arrancar
        fprintf(log_, "n,indice_dac,t_unix\n");
    }

    bool streamData16Bit(DACStreamClient*, int16_t* ch1, int16_t* ch2, size_t size) override {
        if (ch1) memset(ch1, 0, size * sizeof(int16_t));
        if (ch2) memset(ch2, 0, size * sizeof(int16_t));
        uint64_t ini = pos_, fin = pos_ + size;
        while (emitidos_ < (uint64_t)p_.n) {
            uint64_t inicio_pulso = primero_ + emitidos_ * periodo_;
            if (inicio_pulso >= fin) break;
            for (size_t i = 0; i < pulso_.size(); i++) {
                uint64_t k = inicio_pulso + i;
                if (k >= ini && k < fin && ch1) ch1[k - ini] = pulso_[i];
            }
            if (inicio_pulso + pulso_.size() > fin) break;  // sigue en el proximo bloque
            registrar(inicio_pulso);
            emitidos_++;
        }
        pos_ = fin;
        return false;
    }

    bool terminado() const { return emitidos_ >= (uint64_t)p_.n; }
    uint64_t emitidos() const { return emitidos_; }
    size_t largo_pulso() const { return pulso_.size(); }

   private:
    void registrar(uint64_t idx) {
        double t = std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
        fprintf(log_, "%llu,%llu,%.6f\n", (unsigned long long)emitidos_ + 1, (unsigned long long)idx, t);
        fflush(log_);
    }

    ParamsPulsos p_;
    FILE* log_;
    std::vector<int16_t> pulso_;
    uint64_t periodo_, primero_, pos_ = 0;
    std::atomic<uint64_t> emitidos_{0};
};

// Modo archivo (Fase 3 etapa B): reproduce UNA vez por el DAC un tramo de
// señal real (int16 LE, cuentas de ADC, a la misma tasa que --pulso-rate),
// multiplicado por `escala` (4 con el loopback digital: el ADC recibe los 14
// bits altos del DAC). Medio segundo de silencio antes y despues.
class GeneradorArchivo : public DACCallback {
   public:
    GeneradorArchivo(const std::string& ruta, double escala, double rate) {
        FILE* f = fopen(ruta.c_str(), "rb");
        if (!f) return;
        fseek(f, 0, SEEK_END);
        long bytes = ftell(f);
        fseek(f, 0, SEEK_SET);
        datos_.resize(bytes / 2);
        size_t leidos = fread(datos_.data(), 2, datos_.size(), f);
        fclose(f);
        datos_.resize(leidos);
        for (auto& v : datos_) {
            long y = lround(v * escala);
            v = (int16_t)std::max(-32767L, std::min(32767L, y));
        }
        silencio_ = (uint64_t)(rate / 2);
    }

    bool ok() const { return !datos_.empty(); }
    size_t muestras() const { return datos_.size(); }

    bool streamData16Bit(DACStreamClient*, int16_t* ch1, int16_t* ch2, size_t size) override {
        if (ch2) memset(ch2, 0, size * sizeof(int16_t));
        for (size_t i = 0; i < size; i++) {
            uint64_t k = pos_ + i;
            int16_t v = 0;
            if (k >= silencio_ && k - silencio_ < datos_.size()) v = datos_[k - silencio_];
            if (ch1) ch1[i] = v;
        }
        pos_ += size;
        if (pos_ >= silencio_ * 2 + datos_.size()) terminado_ = true;
        return false;
    }

    bool terminado() const { return terminado_; }

   private:
    std::vector<int16_t> datos_;
    uint64_t silencio_ = 0, pos_ = 0;
    std::atomic<bool> terminado_{false};
};

#endif
