// Paso 2: consulta cuanta memoria tiene disponible el canal AXI DMA.
// El resultado (bytes disponibles) define cuantos segundos puede tener el ring buffer.
// Ejecutar ANTES de capture_axi para saber con que tamanio de buffer trabajar.
#include <cstdio>
#include <cstdint>
#include "rp.h"

static const uint32_t DECIMATION  = 32;
static const float    FS_EFECTIVA = 125e6f / DECIMATION;  // 3,906,250 Hz

static void check(int ret, const char *ctx) {
    if (ret != RP_OK) {
        fprintf(stderr, "ERROR en %s: codigo %d\n", ctx, ret);
        rp_Release();
        _Exit(1);
    }
}

int main() {
    printf("=== query_axi: consulta memoria AXI DMA ===\n\n");

    check(rp_Init(), "rp_Init");
    check(rp_AcqReset(), "AcqReset");

    check(rp_AcqAxiEnable(RP_CH_1, true), "AxiEnable CH1");

    uint32_t start, size;
    check(rp_AcqAxiGetMemoryRegion(&start, &size), "GetMemoryRegion");

    uint32_t max_samples = size / sizeof(int16_t);
    float    max_segundos = max_samples / FS_EFECTIVA;

    printf("CH1 AXI region:\n");
    printf("  start    = 0x%08X\n", start);
    printf("  size     = %u bytes (%.1f MB)\n", size, size / 1e6f);
    printf("  muestras = %u\n", max_samples);
    printf("  tiempo   = %.2f s a fs=%.0f Hz\n", max_segundos, FS_EFECTIVA);

    check(rp_AcqAxiEnable(RP_CH_1, false), "AxiDisable CH1");
    rp_Release();
    return 0;
}
