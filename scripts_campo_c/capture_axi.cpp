// Captura continua CH1 via AXI DMA. Guarda datos crudos en archivo .bin.
// Uso: ./capture_axi [duracion_seg] [ruta_salida]
// Por defecto: 10 segundos, /root/capturas_c/captura_axi.bin
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <unistd.h>
#include <stdint.h>
#include <vector>
#include "rp.h"

// --- Parametros de adquisicion ---
static const uint32_t DECIMATION   = 32;
static const float    FS_EFECTIVA  = 125e6f / DECIMATION;  // 3,906,250 Hz
static const uint32_t RING_SAMPLES = 4000000;  // ~1 s de ring buffer en RP
static const uint32_t CHUNK_SIZE   = 100000;   // muestras por lectura (~25 ms)
static const uint32_t MIN_SAMPLES  = 50000;    // umbral minimo antes de leer

// --- Header del archivo .bin ---
// Siempre 40 bytes, little-endian, sin padding.
struct __attribute__((packed)) FileHeader {
    char     magic[4];      // "SNDM"
    uint32_t version;       // 1
    uint32_t fs;            // Hz efectivos (3906250)
    uint32_t decimation;    // factor de decimacion (32)
    uint32_t n_samples;     // muestras totales capturadas (se completa al final)
    uint32_t channels;      // 1 = solo CH1
    int64_t  timestamp;     // unix timestamp al inicio
    uint8_t  gain;          // 5 = RP_GAIN_5X (±20V)
    uint8_t  coupling;      // 0 = DC
    uint8_t  reserved[6];
};
static_assert(sizeof(FileHeader) == 40, "FileHeader debe ser exactamente 40 bytes");

static void check(int ret, const char *ctx) {
    if (ret != RP_OK) {
        fprintf(stderr, "\nERROR en %s: codigo %d\n", ctx, ret);
        rp_Release();
        _Exit(1);
    }
}

static double mono_seg() {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

int main(int argc, char *argv[]) {
    int         duracion_seg = (argc > 1) ? atoi(argv[1]) : 10;
    const char *out_path     = (argc > 2) ? argv[2] : "/root/capturas_c/captura_axi.bin";

    printf("=== capture_axi: AXI DMA CH1 ===\n");
    printf("fs = %.0f Hz | dec = %u | duracion = %d s\n",
           FS_EFECTIVA, DECIMATION, duracion_seg);
    printf("Output: %s\n\n", out_path);

    // 1. Init y reset limpio
    check(rp_Init(),     "rp_Init");
    check(rp_AcqReset(), "AcqReset");

    // 2. Configurar ADC CH1
    check(rp_AcqSetDecimationFactor(DECIMATION),    "SetDecimationFactor");
    check(rp_AcqSetGain(RP_CH_1, RP_HIGH),          "SetGain CH1");  // RP_HIGH = 5X (±20V)

    // 3. Configurar AXI DMA
    check(rp_AcqAxiEnable(RP_CH_1, true), "AxiEnable CH1");

    uint32_t axi_start, axi_size;
    check(rp_AcqAxiGetMemoryRegion(&axi_start, &axi_size), "GetMemoryRegion");

    uint32_t max_samples = axi_size / sizeof(int16_t);
    uint32_t buf_samples = (RING_SAMPLES < max_samples) ? RING_SAMPLES : max_samples;

    printf("Memoria AXI disponible: %.1f MB | ring buffer: %u muestras (%.2f s)\n\n",
           axi_size / 1e6f, buf_samples, buf_samples / FS_EFECTIVA);

    check(rp_AcqAxiSetBufferSamples(RP_CH_1, axi_start, buf_samples), "SetBufferSamples");

    // 4. Trigger deshabilitado: captura continua (free-running)
    check(rp_AcqSetTriggerSrc(RP_TRIG_SRC_DISABLED), "SetTriggerSrc");

    // 5. Abrir archivo y escribir header placeholder
    FILE *fp = fopen(out_path, "wb");
    if (!fp) {
        perror("fopen");
        rp_AcqAxiEnable(RP_CH_1, false);
        rp_Release();
        return 1;
    }

    FileHeader hdr = {};
    memcpy(hdr.magic, "SNDM", 4);
    hdr.version    = 1;
    hdr.fs         = (uint32_t)FS_EFECTIVA;
    hdr.decimation = DECIMATION;
    hdr.channels   = 1;
    hdr.timestamp  = (int64_t)time(nullptr);
    hdr.gain       = 5;
    hdr.coupling   = 0;
    fwrite(&hdr, sizeof(hdr), 1, fp);

    // 6. Iniciar captura
    check(rp_AcqStart(), "AcqStart");
    printf("Capturando");
    fflush(stdout);

    double t_inicio  = mono_seg();
    uint32_t last_ptr   = 0;
    uint32_t total_muestras = 0;
    bool primer_ciclo = true;

    std::vector<int16_t> read_buf(CHUNK_SIZE);

    while (true) {
        double elapsed = mono_seg() - t_inicio;
        if (elapsed >= duracion_seg) break;

        uint32_t write_ptr;
        check(rp_AcqAxiGetWritePointer(RP_CH_1, &write_ptr), "GetWritePointer");

        if (primer_ciclo) {
            last_ptr      = write_ptr;
            primer_ciclo  = false;
            usleep(10000);  // 10 ms de arranque
            continue;
        }

        // Muestras nuevas desde la ultima lectura (manejo de wrap-around)
        uint32_t nuevas;
        if (write_ptr >= last_ptr)
            nuevas = write_ptr - last_ptr;
        else
            nuevas = (buf_samples - last_ptr) + write_ptr;

        if (nuevas < MIN_SAMPLES) {
            usleep(10000);  // 10 ms, esperar mas datos
            continue;
        }

        // Leer sin cruzar el limite del ring buffer (evita wrap-around en un solo read)
        uint32_t to_read = (nuevas > CHUNK_SIZE) ? CHUNK_SIZE : nuevas;
        if (last_ptr + to_read > buf_samples)
            to_read = buf_samples - last_ptr;

        uint32_t got = to_read;
        check(rp_AcqAxiGetDataRaw(RP_CH_1, last_ptr, &got, read_buf.data()), "GetDataRaw");

        fwrite(read_buf.data(), sizeof(int16_t), got, fp);
        total_muestras += got;
        last_ptr = (last_ptr + got) % buf_samples;

        // Progreso cada ~0.5 s de datos capturados
        static uint32_t ultimo_report = 0;
        if (total_muestras - ultimo_report >= (uint32_t)(FS_EFECTIVA * 0.5f)) {
            printf("\r  %.1f s | %u muestras | %.1f MB",
                   elapsed, total_muestras, total_muestras * 2.0 / 1e6);
            fflush(stdout);
            ultimo_report = total_muestras;
        }
    }

    check(rp_AcqStop(), "AcqStop");

    // 7. Completar header con n_samples real
    hdr.n_samples = total_muestras;
    rewind(fp);
    fwrite(&hdr, sizeof(hdr), 1, fp);
    fclose(fp);

    // 8. Estadisticas de eficiencia
    double t_total            = mono_seg() - t_inicio;
    double duracion_capturada = total_muestras / FS_EFECTIVA;
    double eficiencia         = duracion_capturada / t_total * 100.0;

    printf("\n\n=== RESULTADO ===\n");
    printf("Muestras totales  : %u\n", total_muestras);
    printf("Duracion capturada: %.2f s\n", duracion_capturada);
    printf("Tiempo reloj      : %.2f s\n", t_total);
    printf("Eficiencia        : %.1f%%\n", eficiencia);
    printf("Archivo           : %s (%.1f MB)\n", out_path, total_muestras * 2.0 / 1e6);

    rp_AcqAxiEnable(RP_CH_1, false);
    rp_Release();
    return 0;
}
