// Captura continua CH1 via ArmKeep. Guarda datos crudos en archivo .bin.
// Uso: ./capture_armkeep [duracion_seg] [ruta_salida]
// Por defecto: 10 segundos, /root/capturas_c/captura_armkeep.bin
//
// ArmKeep: el ADC se re-arma solo tras cada trigger, eliminando el dead time
// de rp_AcqStart(). Eficiencia estimada: 50-60% (vs 21% en Python).
// El buffer circular es de 16384 muestras = 4.2ms. Debemos leer antes de que
// se complete una vuelta completa (4.2ms), de lo contrario perdemos datos.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <unistd.h>
#include <stdint.h>
#include <vector>
#include "rp.h"

static const uint32_t DECIMATION  = 32;
static const float    FS_EFECTIVA = 125e6f / DECIMATION;  // 3,906,250 Hz
static const uint32_t BUF_SAMPLES = 16384;  // buffer circular de la RP
static const uint32_t CHUNK       = 4096;   // muestras por lectura (~1 ms)
static const uint32_t MIN_NEW     = 2048;   // umbral minimo antes de leer (~0.5 ms)

// Header identico al de capture_axi.cpp para que revisar_axi.py lea ambos.
struct __attribute__((packed)) FileHeader {
    char     magic[4];
    uint32_t version;
    uint32_t fs;
    uint32_t decimation;
    uint32_t n_samples;
    uint32_t channels;
    int64_t  timestamp;
    uint8_t  gain;
    uint8_t  coupling;
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
    const char *out_path     = (argc > 2) ? argv[2] : "/root/capturas_c/captura_armkeep.bin";

    printf("=== capture_armkeep: ArmKeep CH1 ===\n");
    printf("fs = %.0f Hz | dec = %u | buffer = %u muestras (%.1f ms)\n",
           FS_EFECTIVA, DECIMATION, BUF_SAMPLES, BUF_SAMPLES / FS_EFECTIVA * 1000.0f);
    printf("chunk = %u muestras (%.1f ms) | duracion = %d s\n",
           CHUNK, CHUNK / FS_EFECTIVA * 1000.0f, duracion_seg);
    printf("Output: %s\n\n", out_path);

    // 1. Init sin cargar calibracion del EEPROM (reset=false mantiene calib en cero).
    //    rp_AcqGetDataRaw falla si hay calibracion no-cero cargada (RP_NOTS codigo 24).
    check(rp_InitReset(false), "rp_InitReset");
    check(rp_AcqReset(),       "AcqReset");

    check(rp_AcqSetDecimationFactor(DECIMATION), "SetDecimationFactor");
    check(rp_AcqSetGain(RP_CH_1, RP_HIGH),       "SetGain CH1");  // RP_HIGH = 5X (±20V)
    // Mover calibracion al FPGA para que GetDataRaw pueda leer sin aplicar cal en SW
    check(rp_AcqSetCalibInFPGA(RP_CH_1), "SetCalibInFPGA CH1");
    check(rp_AcqSetArmKeep(true), "SetArmKeep");

    // 2. Abrir archivo y escribir header placeholder
    FILE *fp = fopen(out_path, "wb");
    if (!fp) {
        perror("fopen");
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

    // 3. Iniciar captura — ArmKeep + TRIG_SRC_NOW: trigger dispara inmediatamente,
    //    ADC se re-arma solo, leemos el buffer anterior mientras el siguiente se llena.
    check(rp_AcqStart(), "AcqStart");
    check(rp_AcqSetTriggerSrc(RP_TRIG_SRC_NOW), "SetTriggerSrc NOW");

    printf("Capturando");
    fflush(stdout);

    double   t_inicio       = mono_seg();
    uint32_t total_muestras = 0;

    // GetDataRaw falla con RP_HIGH (calibracion no-cero en modo raw no soportado).
    // Usamos GetOldestDataV (float voltios) y convertimos a int16. Para kurtosis
    // el scale no importa; el formato de archivo queda identico al de capture_axi.
    std::vector<float>   volt_buf(BUF_SAMPLES);
    std::vector<int16_t> read_buf(BUF_SAMPLES);

    while (true) {
        double elapsed = mono_seg() - t_inicio;
        if (elapsed >= duracion_seg) break;

        // Esperar a que el ADC haya capturado el buffer completo tras el trigger
        rp_acq_trig_state_t state;
        do {
            check(rp_AcqGetTriggerState(&state), "GetTriggerState");
        } while (state != RP_TRIG_STATE_TRIGGERED);

        // Leer el buffer completo en voltios (±20V range = RP_HIGH)
        uint32_t size = BUF_SAMPLES;
        check(rp_AcqGetOldestDataV(RP_CH_1, &size, volt_buf.data()), "GetOldestDataV");

        // Convertir float V → int16: 32767 / 20.0V = escala full range
        for (uint32_t i = 0; i < size; i++)
            read_buf[i] = (int16_t)(volt_buf[i] * (32767.0f / 20.0f));

        fwrite(read_buf.data(), sizeof(int16_t), size, fp);
        total_muestras += size;

        // Re-disparar inmediatamente — ArmKeep ya re-armo el ADC
        check(rp_AcqSetTriggerSrc(RP_TRIG_SRC_NOW), "SetTriggerSrc NOW re");

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

    // Actualizar header con n_samples real
    hdr.n_samples = total_muestras;
    rewind(fp);
    fwrite(&hdr, sizeof(hdr), 1, fp);
    fclose(fp);

    // Estadisticas
    double t_total            = mono_seg() - t_inicio;
    double duracion_capturada = total_muestras / FS_EFECTIVA;
    double eficiencia         = duracion_capturada / t_total * 100.0;

    printf("\n\n=== RESULTADO ===\n");
    printf("Muestras totales  : %u\n", total_muestras);
    printf("Duracion capturada: %.2f s\n", duracion_capturada);
    printf("Tiempo reloj      : %.2f s\n", t_total);
    printf("Eficiencia        : %.1f%%\n", eficiencia);
    printf("Archivo           : %s (%.1f MB)\n", out_path, total_muestras * 2.0 / 1e6);

    rp_Release();
    return 0;
}
