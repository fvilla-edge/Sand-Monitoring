// capturar_eventos.cpp — nucleo del "modo evento" en C++ (reemplaza el loop
// de capturar_eventos.py, que queda solo como lanzador: carga bitstream +
// streaming-server y hace exec de este binario).
//
// Por que C++ (medido en rp-f0fd8c, 2026-09-23): en Python, solo leer
// `ch.raw` de un paquete cuesta 3.2ms (la libreria SWIG arma una list de
// 32768 ints) y convertirlo a numpy otros 15ms, contra 8.4ms entre paquetes
// a decimacion 32 — el streaming-server descartaba ~63% de las muestras.
// Con la API C++ del vendor, `raw` es un std::vector<int16_t>: el callback
// completo (memcpy al buffer circular) tarda ~0.1ms y llega el 100%.
//
// Funcionamiento (igual que el diseño Python de la Fase 2):
//   - Streaming NET continuo, cada paquete se copia a un buffer circular en
//     RAM con los ultimos BUFFER_VENTANAS x 50ms de señal cruda.
//   - Hilo principal sondea el acumulador de area/kurtosis de la FPGA
//     (window_count + sumas, 0x4000022C..0x248) cada 2ms. Si una ventana
//     cruza kurtosis>=umbral, recorta esa ventana del buffer y la guarda
//     (.bin int16 LE + .json). Las ventanas tranquilas no se guardan.
//   - Alineacion window_count <-> indice de muestra propio: offset medido
//     una vez tras arrancar (ver calibrar()). Las muestras que el server
//     reporta perdidas (fpgaLost, cuenta MUESTRAS — verificado: recibidas +
//     fpgaLost ~= esperadas) avanzan el indice igual, asi un descarte no
//     desalinea: el hueco queda registrado y un evento que lo toque se marca
//     con "con_hueco": true.
//   - Si la deriva medida (window_count vs muestras propias) se sale de
//     TOLERANCIA_DERIVA (ej. stream congelado sin fpgaLost, visto al bajar
//     eth0), se recalibra y se loguea.
//
// Uso: capturar_eventos [--umbral 5.0] [--destino DIR] [--dec 32]
//                       [--estado-s 10] [--duracion-s 0] [--host IP]
//   --host: conectar a esa IP fija en vez del descubrimiento por broadcast
//           del vendor (que ata la conexion a la IP de eth0).
#include "adc_streaming.h"
#include "callbacks.h"
#include "config_streaming.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fcntl.h>
#include <mutex>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {

const double VENTANA_S = 0.05;
const int BUFFER_VENTANAS = 6;           // ~300ms de margen, igual que el Python
const int POLL_US = 2000;
const int64_t TOLERANCIA_DERIVA = 4 * 32768;  // 4 paquetes; jitter normal medido < 2

const uint32_t REG_BASE = 0x40000000;
const uint32_t OFF_WINDOW_COUNT = 0x22C, OFF_SUM_ABS_LO = 0x230, OFF_SUM_ABS_HI = 0x234,
               OFF_SUM_X2_LO = 0x238, OFF_SUM_X2_HI = 0x23C, OFF_SUM_X4_LO = 0x240,
               OFF_SUM_X4_MID = 0x244, OFF_SUM_X4_HI = 0x248;

std::atomic<bool> g_stop{false};

void on_signal(int) { g_stop = true; }

void log(const char* fmt, ...) {
    char ts[16];
    time_t t = time(nullptr);
    strftime(ts, sizeof ts, "%H:%M:%S", gmtime(&t));
    printf("  [LOG %s] ", ts);
    va_list ap;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
    fflush(stdout);
}

// Muestras recibidas indexadas por posicion ABSOLUTA desde el arranque del
// stream (incluye las perdidas reportadas por fpgaLost, que no se escriben).
class BufferCircular {
   public:
    explicit BufferCircular(size_t cap) : datos_(cap), cap_(cap) {}

    void escribir(const int16_t* x, size_t n, uint64_t perdidas) {
        std::lock_guard<std::mutex> g(mtx_);
        if (perdidas) {
            huecos_.push_back({total_, total_ + perdidas});
            while (huecos_.size() > 64) huecos_.pop_front();
            total_ += perdidas;
        }
        size_t pos = total_ % cap_, k = std::min(n, cap_ - pos);
        memcpy(&datos_[pos], x, k * sizeof(int16_t));
        if (n > k) memcpy(&datos_[0], x + k, (n - k) * sizeof(int16_t));
        total_ += n;
    }

    uint64_t total() {
        std::lock_guard<std::mutex> g(mtx_);
        return total_;
    }

    enum Resultado { OK, TODAVIA_NO, PISADA };

    Resultado extraer(int64_t inicio, size_t n, std::vector<int16_t>& out, bool& con_hueco) {
        std::lock_guard<std::mutex> g(mtx_);
        if (inicio < 0) return PISADA;
        uint64_t ini = (uint64_t)inicio, fin = ini + n;
        if (fin > total_) return TODAVIA_NO;
        if (total_ - ini > cap_) return PISADA;
        out.resize(n);
        size_t pos = ini % cap_, k = std::min(n, cap_ - pos);
        memcpy(out.data(), &datos_[pos], k * sizeof(int16_t));
        if (n > k) memcpy(out.data() + k, &datos_[0], (n - k) * sizeof(int16_t));
        con_hueco = false;
        for (auto& h : huecos_)
            if (h.first < fin && h.second > ini) con_hueco = true;
        return OK;
    }

   private:
    std::vector<int16_t> datos_;
    size_t cap_;
    uint64_t total_ = 0;
    std::deque<std::pair<uint64_t, uint64_t>> huecos_;
    std::mutex mtx_;
};

struct Stats {
    std::atomic<uint64_t> paquetes{0}, fpga_lost{0}, paquetes_con_lost{0};
    std::atomic<int64_t> ultimo_paquete_ms{0};
    std::atomic<bool> conectado{false};
};

int64_t ahora_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now().time_since_epoch()).count();
}

class CB : public ADCCallback {
   public:
    CB(BufferCircular& b, Stats& s) : buf_(b), st_(s) {}
    void receivePack(ADCStreamClient*, ADCPack& p) override {
        auto& ch = p.channel1;
        buf_.escribir(ch.raw.data(), ch.raw.size(), ch.fpgaLost);
        st_.paquetes++;
        if (ch.fpgaLost) {
            st_.fpga_lost += ch.fpgaLost;
            st_.paquetes_con_lost++;
        }
        st_.ultimo_paquete_ms = ahora_ms();
    }
    void connected(ADCStreamClient*, std::string h) override {
        st_.conectado = true;
        log("Conectado: %s", h.c_str());
    }
    void disconnected(ADCStreamClient*, std::string h) override {
        st_.conectado = false;
        log("WARNING Desconectado: %s", h.c_str());
    }
    void error(ADCStreamClient*, std::string h, int code) override {
        log("WARNING Error receivePack %s: %d", h.c_str(), code);
    }

   private:
    BufferCircular& buf_;
    Stats& st_;
};

class Registros {
   public:
    bool abrir() {
        int fd = open("/dev/mem", O_RDONLY | O_SYNC);
        if (fd < 0) return false;
        void* m = mmap(nullptr, 0x1000, PROT_READ, MAP_SHARED, fd, REG_BASE);
        close(fd);
        if (m == MAP_FAILED) return false;
        r_ = (volatile uint32_t*)m;
        return true;
    }
    uint32_t window_count() const { return r_[OFF_WINDOW_COUNT / 4]; }
    // Lee las sumas de la ultima ventana completa. Se relee window_count al
    // final: si cambio en el medio, las sumas pueden ser de dos ventanas
    // distintas y se vuelve a leer.
    uint32_t leer(double& s_abs, double& s_x2, double& s_x4) const {
        for (;;) {
            uint32_t wc = window_count();
            s_abs = r_[OFF_SUM_ABS_LO / 4] + ldexp((double)r_[OFF_SUM_ABS_HI / 4], 32);
            s_x2 = r_[OFF_SUM_X2_LO / 4] + ldexp((double)r_[OFF_SUM_X2_HI / 4], 32);
            s_x4 = r_[OFF_SUM_X4_LO / 4] + ldexp((double)r_[OFF_SUM_X4_MID / 4], 32) +
                   ldexp((double)r_[OFF_SUM_X4_HI / 4], 64);
            if (window_count() == wc) return wc;
        }
    }

   private:
    volatile uint32_t* r_ = nullptr;
};

// Misma formula que _area_kurtosis_de_suma (coleccionar_paquete_placa.py).
void area_kurtosis(double s_abs, double s_x2, double s_x4, double n, double fs, double& area,
                   double& kurt) {
    area = s_abs / fs;
    double m2 = s_x2 / n, m4 = s_x4 / n;
    kurt = m2 > 0 ? m4 / (m2 * m2) : m4 / 1e-30;
}

std::string guardar_evento(const std::string& destino, const std::vector<int16_t>& x, double fs,
                           double area, double kurt, uint32_t wc, bool con_hueco) {
    mkdir(destino.c_str(), 0755);
    auto now = std::chrono::system_clock::now();
    time_t t = std::chrono::system_clock::to_time_t(now);
    long us = std::chrono::duration_cast<std::chrono::microseconds>(now.time_since_epoch()).count() % 1000000;
    struct tm tm;
    gmtime_r(&t, &tm);
    char ts[32], iso[48], base[96];
    strftime(ts, sizeof ts, "%Y%m%d_%H%M%S", &tm);
    snprintf(base, sizeof base, "evento_%s_%06ld_wc%010u", ts, us, wc);
    strftime(iso, sizeof iso, "%Y-%m-%dT%H:%M:%S", &tm);

    std::string bin = destino + "/" + base + ".bin";
    FILE* f = fopen(bin.c_str(), "wb");
    if (f) {
        fwrite(x.data(), sizeof(int16_t), x.size(), f);  // ARM es little-endian
        fclose(f);
    }
    std::string js = destino + "/" + base + ".json";
    f = fopen(js.c_str(), "w");
    if (f) {
        fprintf(f,
                "{\n  \"formato\": \"evento_ventana_cruda_int16_le\",\n  \"fs_hz\": %.1f,\n"
                "  \"ventana_s\": %.2f,\n  \"muestras\": %zu,\n  \"window_count\": %u,\n"
                "  \"area\": %.9g,\n  \"kurtosis\": %.6g,\n  \"con_hueco\": %s,\n"
                "  \"timestamp_iso\": \"%s.%06ld+00:00\"\n}\n",
                fs, VENTANA_S, x.size(), wc, area, kurt, con_hueco ? "true" : "false", iso, us);
        fclose(f);
    }
    return base;
}

// offset tal que: indice_propio = wc*N - offset. Se mide con el stream ya
// corriendo y la decimacion ya aplicada (antes de configurarla, el contador
// de la FPGA corre a decimacion 1: 640 ventanas/s). Los paquetes llegan en
// rafagas, asi que (wc*N - total) oscila en ~1 paquete: se toma el MINIMO
// sobre `dur_ms` (el instante con la entrega mas al dia) en vez de una
// lectura suelta, que podia caer en medio de una rafaga (visto: +162k).
int64_t calibrar(const Registros& reg, BufferCircular& buf, int64_t n, int dur_ms) {
    int64_t mejor = INT64_MAX, t0 = ahora_ms();
    while (ahora_ms() - t0 < dur_ms) {
        mejor = std::min(mejor, (int64_t)reg.window_count() * n - (int64_t)buf.total());
        usleep(500);
    }
    return mejor;
}

}  // namespace

int main(int argc, char** argv) {
    double umbral = 5.0;
    std::string destino = "/root/eventos";
    int dec = 32;
    int estado_s = 10;
    int duracion_s = 0;  // 0 = hasta SIGINT/SIGTERM
    std::string host;    // vacio = descubrimiento por broadcast (default del vendor)
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto sig = [&](void) -> const char* {
            if (i + 1 >= argc) { fprintf(stderr, "falta valor para %s\n", a.c_str()); exit(2); }
            return argv[++i];
        };
        if (a == "--umbral") umbral = atof(sig());
        else if (a == "--destino") destino = sig();
        else if (a == "--dec") dec = atoi(sig());
        else if (a == "--estado-s") estado_s = atoi(sig());
        else if (a == "--duracion-s") duracion_s = atoi(sig());
        else if (a == "--host") host = sig();
        else { fprintf(stderr, "argumento desconocido: %s\n", a.c_str()); return 2; }
    }
    const double fs = 125e6 / dec;
    const int64_t N = (int64_t)(fs * VENTANA_S);

    Registros reg;
    if (!reg.abrir()) { log("ERROR no se pudo mapear /dev/mem"); return 1; }

    BufferCircular buf((size_t)N * BUFFER_VENTANAS);
    Stats st;

    auto conf = std::make_shared<ConfigStreamClient>();
    auto adc = std::make_shared<ADCStreamClient>(conf);
    conf->setVerbose(false);
    adc->setVerbose(false);
    bool ok = host.empty() ? conf->connect() : conf->connect(std::vector<std::string>{host});
    if (!ok) { log("ERROR no se pudo conectar al streaming-server%s%s", host.empty() ? "" : " en ", host.c_str()); return 1; }
    log("Config conectada via %s", host.empty() ? "descubrimiento broadcast" : host.c_str());
    conf->sendConfig("adc_pass_mode", "NET");
    conf->sendConfig("adc_decimation", std::to_string(dec));
    conf->sendConfig("channel_attenuator_1", "A_1_20");
    conf->sendConfig("channel_state_1", "ON");
    conf->sendConfig("channel_state_2", "OFF");
    adc->setCallback(std::make_shared<CB>(buf, st));

    log("Modo evento (C++) — umbral kurtosis>=%.2f, dec=%d (fs=%.0f Hz, ventana=%lld muestras), destino=%s",
        umbral, dec, fs, (long long)N, destino.c_str());
    if (!adc->startStreaming()) { log("ERROR startStreaming fallo"); return 1; }
    // Recien ahora: la libreria del vendor instala su propio handler con
    // signal() y pisaba el nuestro (Ctrl+C/SIGTERM no cortaban, visto en HW).
    struct sigaction sa_stop = {};
    sa_stop.sa_handler = on_signal;
    sigaction(SIGINT, &sa_stop, nullptr);
    sigaction(SIGTERM, &sa_stop, nullptr);

    // Esperar a que lleguen datos y el contador corra a la decimacion pedida.
    int64_t t_ini = ahora_ms();
    while (!g_stop && buf.total() == 0 && ahora_ms() - t_ini < 15000) usleep(10000);
    if (buf.total() == 0) { log("ERROR no llegaron muestras en 15s"); adc->stopStreaming(); return 1; }
    usleep(2000000);
    int64_t offset = calibrar(reg, buf, N, 1000);
    log("Calibracion: window_count=%u muestras_propias=%llu offset=%lld", reg.window_count(),
        (unsigned long long)buf.total(), (long long)offset);

    uint64_t ventanas_vistas = 0, ventanas_saltadas = 0, eventos = 0, eventos_perdidos = 0,
             recalibraciones = 0, sin_senal_periodo = 0;
    int ventanas_fuera = 0;  // ventanas seguidas con deriva fuera de tolerancia y stream fluyendo
    int64_t deriva_min_fuera = INT64_MAX;
    bool en_corte = false;
    int64_t deriva_min = INT64_MAX, deriva_max = INT64_MIN;
    uint64_t muestras_ult = buf.total(), lost_ult = st.fpga_lost;
    int64_t t_ult_estado = ahora_ms(), t_inicio = ahora_ms();
    double kurt_max_periodo = 0;

    struct Pendiente { uint32_t wc; double area, kurt; int64_t t_ms; };
    std::deque<Pendiente> pendientes;  // cruzaron el umbral, su señal todavia no llego
    std::vector<int16_t> ventana;

    double sa, s2, s4;
    uint32_t ultimo_wc = reg.leer(sa, s2, s4);

    while (!g_stop) {
        uint32_t wc = reg.leer(sa, s2, s4);
        if (wc != ultimo_wc) {
            uint32_t salto = wc - ultimo_wc;
            if (salto > 1) ventanas_saltadas += salto - 1;
            ventanas_vistas++;
            ultimo_wc = wc;

            // deriva: cuanto se corrio el offset respecto de la calibracion
            int64_t deriva = ((int64_t)wc * N - (int64_t)buf.total()) - offset;
            deriva_min = std::min(deriva_min, deriva);
            deriva_max = std::max(deriva_max, deriva);
            // Recalibrar solo si la deriva se sostiene >=1s (20 ventanas) con el
            // stream fluyendo. Un congelamiento (eth0 abajo) hace crecer la
            // deriva sola, y al volver el server reporta las muestras del
            // corte en fpgaLost (verificado: 882.924.756 = el corte exacto),
            // lo que ya la corrige sin recalibrar. Recalibrar en el borde del
            // corte metia un error (visto en HW: +224k y despues -249k).
            bool fluyendo = ahora_ms() - st.ultimo_paquete_ms < 100;
            if (std::llabs(deriva) > TOLERANCIA_DERIVA && fluyendo) {
                ventanas_fuera++;
                if (std::llabs(deriva) < std::llabs(deriva_min_fuera)) deriva_min_fuera = deriva;
                if (ventanas_fuera >= 20) {
                    offset += deriva_min_fuera;
                    recalibraciones++;
                    log("WARNING deriva de alineacion sostenida %lld muestras (%.1f ms) — recalibrado",
                        (long long)deriva_min_fuera, deriva_min_fuera / fs * 1000);
                    ventanas_fuera = 0;
                    deriva_min_fuera = INT64_MAX;
                }
            } else {
                ventanas_fuera = 0;
                deriva_min_fuera = INT64_MAX;
            }

            double area, kurt;
            area_kurtosis(sa, s2, s4, (double)N, fs, area, kurt);
            kurt_max_periodo = std::max(kurt_max_periodo, kurt);
            if (kurt >= umbral) pendientes.push_back({wc, area, kurt, ahora_ms()});
        }

        while (!pendientes.empty()) {
            auto& p = pendientes.front();
            bool con_hueco = false;
            auto r = buf.extraer((int64_t)(p.wc - 1) * N - offset, (size_t)N, ventana, con_hueco);
            // si la señal no llega en 2s (stream congelado), se da por perdida
            if (r == BufferCircular::TODAVIA_NO && ahora_ms() - p.t_ms < 2000) break;
            if (r == BufferCircular::OK) {
                std::string nombre = guardar_evento(destino, ventana, fs, p.area, p.kurt, p.wc, con_hueco);
                eventos++;
                log("[EVENTO] %s  area=%.4f kurtosis=%.2f%s", nombre.c_str(), p.area, p.kurt,
                    con_hueco ? "  (CON HUECO de muestras)" : "");
            } else if (r == BufferCircular::PISADA) {
                eventos_perdidos++;
                log("WARNING ventana wc=%u cruzo el umbral (kurt=%.2f) pero su señal ya estaba pisada en el buffer",
                    p.wc, p.kurt);
            } else {
                // stream congelado: se cuenta y va resumido en la linea de ESTADO
                eventos_perdidos++;
                sin_senal_periodo++;
            }
            pendientes.pop_front();
        }

        int64_t t = ahora_ms();
        bool corte = t - st.ultimo_paquete_ms > 1000;
        if (corte != en_corte) {
            en_corte = corte;
            if (corte) log("WARNING stream congelado: sin paquetes hace >1s");
            else log("Stream reanudado (fpgaLost acumulado=%llu)", (unsigned long long)st.fpga_lost.load());
        }
        if (t - t_ult_estado >= estado_s * 1000) {
            uint64_t m = buf.total(), l = st.fpga_lost;
            double dt = (t - t_ult_estado) / 1000.0;
            double pct = (m - muestras_ult - (l - lost_ult)) / (fs * dt) * 100;
            log("ESTADO muestras=%.1f%% perdidas_fpga=+%llu ventanas=%llu saltadas=%llu deriva=[%lld,%lld] "
                "kurt_max=%.2f eventos=%llu sin_senal=%llu%s",
                pct, (unsigned long long)(l - lost_ult), (unsigned long long)ventanas_vistas,
                (unsigned long long)ventanas_saltadas, (long long)deriva_min, (long long)deriva_max,
                kurt_max_periodo, (unsigned long long)eventos, (unsigned long long)sin_senal_periodo,
                corte ? "  SIN PAQUETES >1s" : "");
            sin_senal_periodo = 0;
            muestras_ult = m;
            lost_ult = l;
            t_ult_estado = t;
            deriva_min = INT64_MAX;
            deriva_max = INT64_MIN;
            kurt_max_periodo = 0;
        }
        if (duracion_s > 0 && t - t_inicio >= duracion_s * 1000LL) break;
        usleep(POLL_US);
    }

    // stopStreaming() del vendor puede trabarse: si no vuelve en 10s, salir igual.
    std::atomic<bool> parado{false};
    std::thread vigia([&] {
        for (int i = 0; i < 100 && !parado; i++) usleep(100000);
        if (!parado) { log("WARNING stopStreaming no volvio en 10s — salida forzada"); _exit(3); }
    });
    adc->stopStreaming();
    parado = true;
    vigia.join();

    log("Modo evento terminado. paquetes=%llu fpgaLost_total=%llu ventanas=%llu saltadas=%llu eventos=%llu "
        "eventos_perdidos=%llu recalibraciones=%llu",
        (unsigned long long)st.paquetes.load(), (unsigned long long)st.fpga_lost.load(),
        (unsigned long long)ventanas_vistas, (unsigned long long)ventanas_saltadas, (unsigned long long)eventos,
        (unsigned long long)eventos_perdidos, (unsigned long long)recalibraciones);
    return 0;
}
