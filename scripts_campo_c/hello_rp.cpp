// Paso 1: valida que librp linkea y rp_Init funciona en la RP.
// Si esto corre sin errores, el entorno C++ está OK.
#include <cstdio>
#include "rp.h"

int main() {
    printf("=== hello_rp: test de linking librp ===\n");

    int ret = rp_Init();
    if (ret != RP_OK) {
        fprintf(stderr, "FALLO rp_Init: codigo %d\n", ret);
        return 1;
    }

    // Imprimir version de la libreria
    const char *ver = rp_GetVersion();
    printf("librp version : %s\n", ver ? ver : "(no disponible)");

    rp_Release();
    printf("OK — entorno C++ funciona.\n");
    return 0;
}
