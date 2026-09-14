// Medicion: si un hilo de prioridad alta puede leer un contador que
// avanza cada 50ms (simulando el registro AREA_WINDOW_COUNT del
// acumulador de area/kurtosis en la FPGA - ver repo aparte
// ~/RedPitaya-FPGA-Release_2025.2, Etapa 5/6) sin perderse ninguna
// actualizacion - antes de invertir en una FIFO en HW para el mismo
// problema (si el ARM no llega a leer los 9 registros antes de que la
// proxima ventana los pise, esa ventana se pierde sin aviso).
//
// PENDIENTE REAL: esto todavia simula el "registro" con un contador en
// memoria (productor/consumidor en la misma notebook, x86) - NO lee
// hardware de verdad todavia. Cuando llegue la placa nueva de pruebas y
// el bitstream de la Etapa 5/6 este flasheado, el siguiente paso es
// reemplazar `productor()` por una lectura real via mmap de
// /dev/mem (offset AREA_WINDOW_COUNT, 0x40000000+0x22C) y correr esto
// EN el ARM real (no en la notebook) con la captura real corriendo al
// mismo tiempo (la carga real que importa, no leer registros en si).
//
// Resultado del 2026-09-14 en esta notebook (x86, SIN privilegios de
// tiempo real - `ulimit -r` da 0 en esta cuenta): 60s, 1199 ventanas
// simuladas, 0 ventanas perdidas, gap maximo entre lecturas = 1. Buena
// señal pero no concluyente para el ARM real - ver nota de arriba.
//
// Compilar: gcc -O2 -Wall -o medir_polling_ventanas medir_polling_ventanas.c -lpthread
// Correr:   ./medir_polling_ventanas   (si hay permiso de SCHED_FIFO lo
//           usa, si no cae a prioridad normal y lo avisa por stderr)
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <stdatomic.h>
#include <unistd.h>

#define WINDOW_MS   50
#define POLL_US     10000   // intenta leer cada 10ms (5x margen contra 50ms)
#define DURATION_S  60

static atomic_uint window_count = 0;
static atomic_int  stop_flag    = 0;

static void addms(struct timespec *t, long ms) {
    t->tv_nsec += ms * 1000000L;
    while (t->tv_nsec >= 1000000000L) { t->tv_nsec -= 1000000000L; t->tv_sec++; }
}

static void *productor(void *arg) {
    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (!atomic_load(&stop_flag)) {
        addms(&next, WINDOW_MS);
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
        atomic_fetch_add(&window_count, 1);
    }
    return NULL;
}

static void *consumidor(void *arg) {
    unsigned int last_seen = 0, reads = 0, missed_events = 0, missed_windows = 0, max_gap = 0;
    struct timespec next;
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (!atomic_load(&stop_flag)) {
        unsigned int cur = atomic_load(&window_count);
        reads++;
        unsigned int gap = cur - last_seen;
        if (gap > max_gap) max_gap = gap;
        if (gap > 1) { missed_events++; missed_windows += (gap - 1); }
        last_seen = cur;
        addms(&next, POLL_US / 1000);
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
    }
    printf("lecturas=%u ventanas_totales=%u eventos_de_perdida=%u ventanas_perdidas=%u gap_maximo=%u\n",
           reads, last_seen, missed_events, missed_windows, max_gap);
    return NULL;
}

int main(void) {
    pthread_t pt, ct;
    pthread_attr_t attr;
    struct sched_param sp;
    int modo_rt = 1;

    pthread_create(&pt, NULL, productor, NULL);

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

    printf("Modo: %s | ventana=%dms poll=%dus duracion=%ds\n",
           modo_rt ? "SCHED_FIFO (tiempo real)" : "prioridad normal (sin privilegios RT)",
           WINDOW_MS, POLL_US, DURATION_S);

    sleep(DURATION_S);
    atomic_store(&stop_flag, 1);
    pthread_join(pt, NULL);
    pthread_join(ct, NULL);
    return 0;
}
