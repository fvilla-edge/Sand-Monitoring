// Medicion: si un hilo de prioridad alta puede leer, sin perderse
// ninguna actualizacion, el registro real AREA_WINDOW_COUNT del
// acumulador de area/kurtosis en la FPGA (Etapa 5/6/7/8 de
// ~/RedPitaya-FPGA-Release_2025.2) - antes de invertir en una FIFO en
// HW para el mismo problema (si el ARM no llega a leer los 9 registros
// antes de que la proxima ventana los pise, esa ventana se pierde sin
// aviso). El "productor" es la FPGA misma (su propio reloj de ADC), no
// hace falta simularlo - a diferencia de la version anterior de este
// archivo (notebook x86, sin HW real, ver historial de memoria del
// proyecto 2026-09-14).
//
// Requiere: bitstream con el acumulador de la Etapa 5/6 ya cargado (ver
// setup_placa.md -> "2b"/"FPGA nuevo" y el README de
// RedPitaya-FPGA-Release_2025.2) y correr ESTO EN el ARM real de la
// placa (no en una notebook) - la carga real que importa es la del
// sistema completo (captura real corriendo al mismo tiempo), no la
// lectura de registros en si.
//
// Resultado del 2026-09-14 (notebook x86, SIN privilegios de tiempo
// real, contador SIMULADO): 60s, 1199 ventanas, 0 perdidas, gap maximo
// = 1 - no concluyente para el ARM real, ver arriba.
//
// Compilar EN LA PLACA: gcc -O2 -Wall -o medir_polling_ventanas medir_polling_ventanas.c -lpthread
// Correr (como root, por /dev/mem):
//   ./medir_polling_ventanas   (si hay permiso de SCHED_FIFO lo usa, si
//   no cae a prioridad normal y lo avisa por stderr)
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <stdatomic.h>
#include <unistd.h>
#include <sys/mman.h>

#define POLL_US        10000       // intenta leer cada 10ms (5x margen contra 50ms de ventana)
#define DURATION_S     60
#define REG_BASE       0x40000000UL
#define REG_MAP_SIZE   0x1000UL
// etapa7 viejo (Release_2025.2): 0x228/0x22C; port a Release_2026.1: +0x100
// (2026.1 ocupo 0x200-0x214). Se detecta en main() con el registro de muestras
// por ventana (R/W, default 195312; lo no mapeado se lee 0).
#define OFF_WINDOW_SAMPLES 0x228
#define OFF_WINDOW_COUNT 0x22C

static atomic_int stop_flag = 0;
static volatile uint32_t *g_window_count_reg = NULL;

static void addms(struct timespec *t, long ms) {
    t->tv_nsec += ms * 1000000L;
    while (t->tv_nsec >= 1000000000L) { t->tv_nsec -= 1000000000L; t->tv_sec++; }
}

static void *consumidor(void *arg) {
    unsigned int last_seen = 0, primer_valor = 0, reads = 0;
    unsigned int missed_events = 0, missed_windows = 0, max_gap = 0;
    unsigned int primera_lectura = 1;
    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (!atomic_load(&stop_flag)) {
        unsigned int cur = *g_window_count_reg;
        reads++;
        if (primera_lectura) {
            // el contador de HW no arranca en 0 (corre solo desde que se
            // cargo el bitstream) - se resta este valor inicial al final
            // para reportar cuantas ventanas NUEVAS paso durante esta
            // corrida, no el valor absoluto del registro.
            last_seen = primer_valor = cur;
            primera_lectura = 0;
        } else {
            unsigned int gap = cur - last_seen;
            if (gap > max_gap) max_gap = gap;
            if (gap > 1) { missed_events++; missed_windows += (gap - 1); }
            last_seen = cur;
        }
        addms(&next, POLL_US / 1000);
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
    }
    printf("lecturas=%u ventanas_nuevas=%u eventos_de_perdida=%u ventanas_perdidas=%u gap_maximo=%u\n",
           reads, last_seen - primer_valor, missed_events, missed_windows, max_gap);
    return NULL;
}

int main(void) {
    int fd = open("/dev/mem", O_RDONLY);
    if (fd < 0) { perror("open /dev/mem (necesita root)"); return 1; }
    void *map = mmap(NULL, REG_MAP_SIZE, PROT_READ, MAP_SHARED, fd, REG_BASE);
    close(fd);
    if (map == MAP_FAILED) { perror("mmap /dev/mem"); return 1; }
    unsigned long base = 0;
    if (*(volatile uint32_t *)((char *)map + OFF_WINDOW_SAMPLES + 0x100) != 0) base = 0x100;
    else if (*(volatile uint32_t *)((char *)map + OFF_WINDOW_SAMPLES) == 0) {
        fprintf(stderr, "el bitstream cargado no tiene el acumulador de area/kurtosis (ni en 0x328 ni en 0x228)\n");
        return 1;
    }
    g_window_count_reg = (volatile uint32_t *)((char *)map + OFF_WINDOW_COUNT + base);

    pthread_t ct;
    pthread_attr_t attr;
    struct sched_param sp;
    int modo_rt = 1;

    pthread_attr_init(&attr);
    memset(&sp, 0, sizeof(sp));
    sp.sched_priority = 50;
    pthread_attr_setschedpolicy(&attr, SCHED_FIFO);
    pthread_attr_setschedparam(&attr, &sp);
    pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);

    int rc = pthread_create(&ct, &attr, consumidor, NULL);
    if (rc != 0) {
        fprintf(stderr, "No se pudo crear el hilo con SCHED_FIFO (%s) - probando con prioridad normal (peor caso realista sin privilegios de tiempo real)\n", strerror(rc));
        modo_rt = 0;
        pthread_create(&ct, NULL, consumidor, NULL);
    }

    printf("Modo: %s | registro real AREA_WINDOW_COUNT (0x%lX) | poll=%dus duracion=%ds\n",
           modo_rt ? "SCHED_FIFO (tiempo real)" : "prioridad normal (sin privilegios RT)",
           REG_BASE + OFF_WINDOW_COUNT + base, POLL_US, DURATION_S);

    sleep(DURATION_S);
    atomic_store(&stop_flag, 1);
    pthread_join(ct, NULL);
    munmap(map, REG_MAP_SIZE);
    return 0;
}
