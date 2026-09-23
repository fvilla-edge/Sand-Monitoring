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
//     (.bin int16 LE + .json) con un margen de --margen-ms (default 10ms) a
//     cada lado. Las ventanas tranquilas no se guardan.
//   - Margen: la Fase 3 (loopback DAC->ADC con pulsos conocidos, 2026-09-23)
//     mostro que las fronteras de ventana de la FPGA quedan corridas ~2.6-3.5ms
//     respecto de las del buffer propio — la calibracion toma el instante de
//     entrega mas al dia, pero la entrega nunca tiene retraso cero (DMA + red),
//     y el retraso cambia entre corridas. Sin margen, un pulso cerca del borde
//     quedaba en la ventana cruda de al lado. El .json dice donde empieza la
//     ventana "oficial" dentro del archivo (`inicio_ventana_en_archivo`).
//   - La escritura a disco va en un hilo aparte (cola acotada): escribir ~0.5MB
//     en la SD puede tardar mas que una ventana y el registro de la FPGA solo
//     guarda la ultima — escribir en el hilo de sondeo hacia perder ventanas.
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
//                       [--estado-s 10] [--duracion-s 0] [--host IP] [--margen-ms 10]
//   --host: conectar a esa IP fija en vez del descubrimiento por broadcast
//           del vendor (que ata la conexion a la IP de eth0).
//
// Modo PRUEBA (Fase 3, loopback OUT1->IN1, ver generador_pulsos.h):
//   --prueba-pulsos N [--pulso-periodo-s 2.37] [--pulso-freq 150000]
//   [--pulso-tau-us 20] [--pulso-amp 0.8] [--pulso-log pulsos.csv]
//   [--pulso-loopback-digital]  (DAC->ADC canal 1 dentro de la FPGA, registro
//   0x40000040 bit1 — con el bitstream etapa7 la salida fisica OUT1 no anda)
//   Genera N pulsos por OUT1 y corta sola ~3s despues del ultimo.
//   --prueba-archivo RUTA [--dac-escala 4] [--dac-rate 7812500]: en vez de
//   pulsos, reproduce una vez un tramo de señal real (int16 LE) por el DAC
//   (Fase 3 etapa B) y corta sola ~3s despues.
//
// OJO: el streaming-server acepta UNA sola conexion de configuracion. Si otro
// cliente se conecta, a este le llega "End of file" y la libreria del vendor
// muere por SIGSEGV (visto con strace en HW, 2026-09-23). No hay forma de
// atraparlo desde aca: no correr otro cliente contra el server a la vez.
#include "adc_streaming.h"
#include "callbacks.h"
#include "config_streaming.h"
#include "dac_streaming.h"
#include "generador_pulsos.h"

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
#include <condition_variable>
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
    std::atomic<int> raw_max{0};  // max |x| crudo desde la ultima linea de ESTADO
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
        int m = 0;
        for (int16_t x : ch.raw) m = std::max(m, std::abs((int)x));
        if (m > st_.raw_max) st_.raw_max = m;
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

struct Evento {
    std::vector<int16_t> x;  // ventana + margen a cada lado
    double fs, area, kurt;
    uint32_t wc;
    int64_t indice_inicio;   // indice absoluto (stream propio) de x[0]
    int64_t margen;          // muestras de margen antes (y despues) de la ventana oficial
    int64_t ventana;         // muestras de la ventana oficial
    bool con_hueco;
    std::string base, iso;   // nombre y hora de deteccion
};

Evento nuevo_evento(uint32_t wc) {
    Evento e;
    e.wc = wc;
    auto now = std::chrono::system_clock::now();
    time_t t = std::chrono::system_clock::to_time_t(now);
    long us = std::chrono::duration_cast<std::chrono::microseconds>(now.time_since_epoch()).count() % 1000000;
    struct tm tm;
    gmtime_r(&t, &tm);
    char ts[32], iso[48], base[96];
    strftime(ts, sizeof ts, "%Y%m%d_%H%M%S", &tm);
    snprintf(base, sizeof base, "evento_%s_%06ld_wc%010u", ts, us, wc);
    strftime(iso, sizeof iso, "%Y-%m-%dT%H:%M:%S", &tm);
    e.base = base;
    e.iso = std::string(iso) + "." + std::to_string(1000000 + us).substr(1) + "+00:00";
    return e;
}

void guardar_evento(const std::string& destino, const Evento& e) {
    mkdir(destino.c_str(), 0755);
    std::string bin = destino + "/" + e.base + ".bin";
    FILE* f = fopen(bin.c_str(), "wb");
    if (f) {
        fwrite(e.x.data(), sizeof(int16_t), e.x.size(), f);  // ARM es little-endian
        fclose(f);
    }
    std::string js = destino + "/" + e.base + ".json";
    f = fopen(js.c_str(), "w");
    if (f) {
        fprintf(f,
                "{\n  \"formato\": \"evento_ventana_cruda_int16_le\",\n  \"fs_hz\": %.1f,\n"
                "  \"ventana_s\": %.2f,\n  \"ventana_muestras\": %lld,\n  \"margen_muestras\": %lld,\n"
                "  \"inicio_ventana_en_archivo\": %lld,\n  \"muestras\": %zu,\n  \"window_count\": %u,\n"
                "  \"indice_inicio\": %lld,\n"
                "  \"area\": %.9g,\n  \"kurtosis\": %.6g,\n  \"con_hueco\": %s,\n"
                "  \"timestamp_iso\": \"%s\"\n}\n",
                e.fs, VENTANA_S, (long long)e.ventana, (long long)e.margen, (long long)e.margen, e.x.size(), e.wc,
                (long long)e.indice_inicio, e.area, e.kurt, e.con_hueco ? "true" : "false", e.iso.c_str());
        fclose(f);
    }
}

// Escribe los eventos en disco desde un hilo propio. Cola acotada: si se
// llena (disco trabado), el evento se descarta y se cuenta, en vez de
// comerse la RAM de la placa (~0.5MB por evento, 459MB en total).
class Escritor {
   public:
    static const size_t MAX_COLA = 40;

    explicit Escritor(std::string destino) : destino_(std::move(destino)), hilo_([this] { correr(); }) {}
    ~Escritor() {
        if (hilo_.joinable()) cerrar();
    }

    bool encolar(Evento&& e) {
        {
            std::lock_guard<std::mutex> g(mtx_);
            if (cola_.size() >= MAX_COLA) return false;
            cola_.push_back(std::move(e));
        }
        cv_.notify_one();
        return true;
    }

    void cerrar() {  // escribe lo que quede y termina
        {
            std::lock_guard<std::mutex> g(mtx_);
            fin_ = true;
        }
        cv_.notify_one();
        hilo_.join();
    }

    uint64_t escritos() const { return escritos_; }

   private:
    void correr() {
        for (;;) {
            Evento e;
            {
                std::unique_lock<std::mutex> g(mtx_);
                cv_.wait(g, [this] { return fin_ || !cola_.empty(); });
                if (cola_.empty()) return;
                e = std::move(cola_.front());
                cola_.pop_front();
            }
            guardar_evento(destino_, e);
            escritos_++;
        }
    }

    std::string destino_;
    std::mutex mtx_;
    std::condition_variable cv_;
    std::deque<Evento> cola_;
    bool fin_ = false;
    std::atomic<uint64_t> escritos_{0};
    std::thread hilo_;
};

// offset tal que: indice_propio = wc*N - offset. Se mide con el stream ya
// corriendo y la decimacion ya aplicada (antes de configurarla, el contador
// de la FPGA corre a decimacion 1: 640 ventanas/s).
//
// Se mide SOLO en el instante en que window_count cambia: entre cambios el
// contador va atrasado hasta una ventana entera respecto de las muestras, y
// medir en instantes cualquiera (version anterior) calibraba ~1 ventana
// corrido — la deriva lo detectaba y recalibraba ~47ms al segundo en todas
// las corridas (visto en HW, Fase 3). Los paquetes llegan en rafagas, asi que
// (wc*N - total) oscila en ~1 paquete: se toma el MINIMO sobre `dur_ms` (el
// instante con la entrega mas al dia), mismo criterio que la recalibracion.
int64_t calibrar(const Registros& reg, BufferCircular& buf, int64_t n, int dur_ms) {
    int64_t mejor = INT64_MAX, t0 = ahora_ms();
    uint32_t ultimo = reg.window_count();
    while (ahora_ms() - t0 < dur_ms) {
        uint32_t wc = reg.window_count();
        if (wc != ultimo) {
            mejor = std::min(mejor, (int64_t)wc * n - (int64_t)buf.total());
            ultimo = wc;
        }
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
    double margen_ms = 10;
    int duracion_s = 0;  // 0 = hasta SIGINT/SIGTERM
    std::string host;    // vacio = descubrimiento por broadcast (default del vendor)
    ParamsPulsos pp;     // modo prueba, apagado si pp.n == 0
    bool loopback_digital = false;
    std::string prueba_archivo;
    double dac_escala = 4;
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
        else if (a == "--margen-ms") margen_ms = atof(sig());
        else if (a == "--duracion-s") duracion_s = atoi(sig());
        else if (a == "--host") host = sig();
        else if (a == "--prueba-pulsos") pp.n = atoi(sig());
        else if (a == "--pulso-periodo-s") pp.periodo_s = atof(sig());
        else if (a == "--pulso-freq") pp.freq = atof(sig());
        else if (a == "--pulso-tau-us") pp.tau_us = atof(sig());
        else if (a == "--pulso-amp") pp.amp = atof(sig());
        else if (a == "--pulso-log") pp.log = sig();
        else if (a == "--pulso-loopback-digital") loopback_digital = true;
        else if (a == "--prueba-archivo") prueba_archivo = sig();
        else if (a == "--dac-escala") dac_escala = atof(sig());
        else if (a == "--dac-rate") pp.rate = atof(sig());
        else { fprintf(stderr, "argumento desconocido: %s\n", a.c_str()); return 2; }
    }
    const double fs = 125e6 / dec;
    const int64_t N = (int64_t)(fs * VENTANA_S);

    Registros reg;
    if (!reg.abrir()) { log("ERROR no se pudo mapear /dev/mem"); return 1; }

    const int64_t M = (int64_t)(fs * margen_ms / 1000);
    if (2 * M >= (int64_t)N * (BUFFER_VENTANAS - 2)) { log("ERROR --margen-ms demasiado grande para el buffer"); return 1; }
    BufferCircular buf((size_t)N * BUFFER_VENTANAS);
    Escritor escritor(destino);
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

    // Modo prueba: DAC por el MISMO ConfigStreamClient (una segunda conexion
    // de configuracion tira la primera, ver generador_pulsos.h).
    std::shared_ptr<DACStreamClient> dac;
    std::shared_ptr<GeneradorPulsos> gen;
    std::shared_ptr<GeneradorArchivo> gen_archivo;
    FILE* pulsos_log = nullptr;
    if (!prueba_archivo.empty()) {
        gen_archivo = std::make_shared<GeneradorArchivo>(prueba_archivo, dac_escala, pp.rate);
        if (!gen_archivo->ok()) { log("ERROR no se pudo leer %s", prueba_archivo.c_str()); return 1; }
        char rate[32];
        snprintf(rate, sizeof rate, "%.0f", pp.rate);
        conf->sendConfig("dac_pass_mode", "DAC_NET");
        conf->sendConfig("dac_rate", rate);
        log("PRUEBA: dac_rate pedido=%s leido=%s", rate, conf->getConfig("dac_rate").c_str());
        dac = std::make_shared<DACStreamClient>(conf);
        dac->setVerbose(false);
        dac->setCallback(gen_archivo);
    } else if (pp.n > 0) {
        pulsos_log = fopen(pp.log.c_str(), "w");
        if (!pulsos_log) { log("ERROR no se pudo abrir %s", pp.log.c_str()); return 1; }
        char rate[32];
        snprintf(rate, sizeof rate, "%.0f", pp.rate);
        conf->sendConfig("dac_pass_mode", "DAC_NET");
        conf->sendConfig("dac_rate", rate);
        dac = std::make_shared<DACStreamClient>(conf);
        dac->setVerbose(false);
        gen = std::make_shared<GeneradorPulsos>(pp, pulsos_log);
        dac->setCallback(gen);
    }

    log("Modo evento (C++) — umbral kurtosis>=%.2f, dec=%d (fs=%.0f Hz, ventana=%lld muestras, margen=%lld), "
        "destino=%s", umbral, dec, fs, (long long)N, (long long)M, destino.c_str());
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
    if (buf.total() == 0) {
        log("ERROR no llegaron muestras en 15s");
        adc->stopStreaming();
        return 1;
    }
    usleep(2000000);
    int64_t offset = calibrar(reg, buf, N, 1000);
    log("Calibracion: window_count=%u muestras_propias=%llu offset=%lld", reg.window_count(),
        (unsigned long long)buf.total(), (long long)offset);

    // el DAC arranca despues de calibrar, para no meter pulsos en la calibracion
    int64_t t_fin_pulsos = 0;
    if (gen_archivo) {
        if (!dac->startStreamingFromMemorySink(host.empty() ? "127.0.0.1" : host, true, false, DAC_16BIT)) {
            log("ERROR no arranco el DAC");
            adc->stopStreaming();
            return 1;
        }
        log("PRUEBA: reproduciendo %s por el DAC (%zu muestras, %.1fs a %.0f Hz, escala %.1f)",
            prueba_archivo.c_str(), gen_archivo->muestras(), gen_archivo->muestras() / pp.rate, pp.rate, dac_escala);
    }
    if (gen) {
        if (!dac->startStreamingFromMemorySink(host.empty() ? "127.0.0.1" : host, true, false, DAC_16BIT)) {
            log("ERROR no arranco el DAC");
            adc->stopStreaming();
                return 1;
        }
        log("PRUEBA: generando %d pulsos por OUT1 (periodo %.3fs, %.0f Hz, tau %.0f us, amp %.2f, %zu muestras DAC) "
            "-> %s", pp.n, pp.periodo_s, pp.freq, pp.tau_us, pp.amp, gen->largo_pulso(), pp.log.c_str());
    }
    if (loopback_digital) {
        int fd = open("/dev/mem", O_RDWR | O_SYNC);
        void* m = fd < 0 ? MAP_FAILED : mmap(nullptr, 0x1000, PROT_READ | PROT_WRITE, MAP_SHARED, fd, REG_BASE);
        if (fd >= 0) close(fd);
        if (m == MAP_FAILED) { log("ERROR no se pudo mapear /dev/mem para el loopback"); adc->stopStreaming(); return 1; }
        volatile uint32_t* lb = (volatile uint32_t*)m + 0x40 / 4;
        *lb = *lb | 0x2;
        log("PRUEBA: loopback digital DAC->ADC canal 1 activado (reg 0x40000040=%08x)", *lb);
    }

    uint64_t ventanas_vistas = 0, ventanas_saltadas = 0, eventos = 0, eventos_perdidos = 0,
             recalibraciones = 0, sin_senal_periodo = 0;
    int ventanas_fuera = 0;  // ventanas seguidas con deriva fuera de tolerancia y stream fluyendo
    int64_t fuera_min = INT64_MAX, fuera_max = INT64_MIN;
    int64_t t_disturbio = 0;  // ultima reanudacion o reporte de fpgaLost
    uint64_t lost_visto = 0;
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
            // Recalibrar solo si la deriva se sostiene >=1s (20 ventanas), con el
            // stream fluyendo, ESTABLE (varia menos de 2 paquetes en ese
            // segundo) y lejos (>5s) de una reanudacion o un reporte de
            // fpgaLost. Un congelamiento (eth0 abajo) hace crecer la deriva
            // sola, y al volver el server reporta las muestras del corte en
            // fpgaLost (verificado: 882.924.756 = el corte exacto), lo que ya
            // la corrige sin recalibrar. Visto en HW (Fase 3): recalibrar en el
            // borde del corte, o durante la rafaga de entrega atrasada despues
            // de reanudar (deriva sostenida pero bajando), desalineaba todo lo
            // que venia despues.
            int64_t ahora = ahora_ms();
            if (st.fpga_lost != lost_visto) {
                lost_visto = st.fpga_lost;
                t_disturbio = ahora;
            }
            bool fluyendo = ahora - st.ultimo_paquete_ms < 100;
            bool calmo = ahora - t_disturbio > 5000;
            if (std::llabs(deriva) > TOLERANCIA_DERIVA && fluyendo && calmo) {
                ventanas_fuera++;
                fuera_min = std::min(fuera_min, deriva);
                fuera_max = std::max(fuera_max, deriva);
                if (ventanas_fuera >= 20) {
                    if (fuera_max - fuera_min <= 2 * 32768) {
                        // mismo criterio que calibrar(): el minimo es el instante de entrega mas al dia
                        offset += fuera_min;
                        recalibraciones++;
                        log("WARNING deriva de alineacion sostenida y estable %lld muestras (%.1f ms) — recalibrado",
                            (long long)fuera_min, fuera_min / fs * 1000);
                    }
                    ventanas_fuera = 0;
                    fuera_min = INT64_MAX;
                    fuera_max = INT64_MIN;
                }
            } else {
                ventanas_fuera = 0;
                fuera_min = INT64_MAX;
                fuera_max = INT64_MIN;
            }

            double area, kurt;
            area_kurtosis(sa, s2, s4, (double)N, fs, area, kurt);
            kurt_max_periodo = std::max(kurt_max_periodo, kurt);
            if (kurt >= umbral) pendientes.push_back({wc, area, kurt, ahora_ms()});
        }

        while (!pendientes.empty()) {
            auto& p = pendientes.front();
            bool con_hueco = false;
            int64_t idx_ini = (int64_t)(p.wc - 1) * N - offset - M;
            auto r = buf.extraer(idx_ini, (size_t)(N + 2 * M), ventana, con_hueco);
            // si la señal no llega en 2s (stream congelado), se da por perdida
            if (r == BufferCircular::TODAVIA_NO && ahora_ms() - p.t_ms < 2000) break;
            if (r == BufferCircular::OK) {
                Evento e = nuevo_evento(p.wc);
                e.x = std::move(ventana);
                e.fs = fs;
                e.area = p.area;
                e.kurt = p.kurt;
                e.indice_inicio = idx_ini;
                e.margen = M;
                e.ventana = N;
                e.con_hueco = con_hueco;
                std::string nombre = e.base;
                if (escritor.encolar(std::move(e))) {
                    eventos++;
                    log("[EVENTO] %s  area=%.4f kurtosis=%.2f%s", nombre.c_str(), p.area, p.kurt,
                        con_hueco ? "  (CON HUECO de muestras)" : "");
                } else {
                    eventos_perdidos++;
                    log("WARNING cola de escritura llena (%zu) — evento wc=%u descartado", Escritor::MAX_COLA, p.wc);
                }
                ventana = std::vector<int16_t>();
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
            if (!corte) t_disturbio = t;
            if (corte) log("WARNING stream congelado: sin paquetes hace >1s");
            else log("Stream reanudado (fpgaLost acumulado=%llu)", (unsigned long long)st.fpga_lost.load());
        }
        if (t - t_ult_estado >= estado_s * 1000) {
            uint64_t m = buf.total(), l = st.fpga_lost;
            double dt = (t - t_ult_estado) / 1000.0;
            double pct = (m - muestras_ult - (l - lost_ult)) / (fs * dt) * 100;
            log("ESTADO muestras=%.1f%% perdidas_fpga=+%llu ventanas=%llu saltadas=%llu deriva=[%lld,%lld] "
                "kurt_max=%.2f raw_max=%d eventos=%llu sin_senal=%llu%s",
                pct, (unsigned long long)(l - lost_ult), (unsigned long long)ventanas_vistas,
                (unsigned long long)ventanas_saltadas, (long long)deriva_min, (long long)deriva_max,
                kurt_max_periodo, st.raw_max.exchange(0), (unsigned long long)eventos,
                (unsigned long long)sin_senal_periodo,
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
        if ((gen && gen->terminado()) || (gen_archivo && gen_archivo->terminado())) {
            if (t_fin_pulsos == 0) t_fin_pulsos = t;
            else if (t - t_fin_pulsos > 3000) break;
        }
        usleep(POLL_US);
    }

    // stopStreaming() del vendor puede trabarse: si no vuelve en 10s, salir igual.
    std::atomic<bool> parado{false};
    std::thread vigia([&] {
        for (int i = 0; i < 100 && !parado; i++) usleep(100000);
        if (!parado) { log("WARNING stopStreaming no volvio en 10s — salida forzada"); _exit(3); }
    });
    if (dac) dac->stopStreaming();
    adc->stopStreaming();
    parado = true;
    vigia.join();
    escritor.cerrar();

    log("Modo evento terminado. paquetes=%llu fpgaLost_total=%llu ventanas=%llu saltadas=%llu eventos=%llu "
        "(escritos=%llu) eventos_perdidos=%llu recalibraciones=%llu",
        (unsigned long long)st.paquetes.load(), (unsigned long long)st.fpga_lost.load(),
        (unsigned long long)ventanas_vistas, (unsigned long long)ventanas_saltadas, (unsigned long long)eventos,
        (unsigned long long)escritor.escritos(), (unsigned long long)eventos_perdidos,
        (unsigned long long)recalibraciones);
    if (gen) {
        log("PRUEBA: pulsos emitidos=%llu", (unsigned long long)gen->emitidos());
        fclose(pulsos_log);
    }
    return 0;
}
