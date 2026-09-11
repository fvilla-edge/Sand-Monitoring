/*
 * paquete_area.c — la parte pesada de exportar_paquete_area.py reescrita en
 * C: leer el .bin (formato segmentado de revisar.py), filtrar pasabanda
 * (CAUSAL, una pasada — ver sec.172 de la memoria del proyecto) y calcular
 * area/kurtosis por ventana, todo por bloques de memoria acotada (mismo
 * diseño ya validado en area_kurtosis.py: margen de datos reales entre
 * bloques para el asentamiento del filtro + un "residual" de muestras
 * filtradas sin ventanear que se arrastra entre bloques para no reiniciar
 * la grilla de ventanas en cada uno).
 *
 * Medido en la placa real (rp-f0fbda): la version Python/NumPy/SciPy
 * tarda ~10x el tiempo real de la señal AUN SOLA, sin competir con
 * ninguna captura (245.9s para procesar 25.7s de audio) — de ahi esta
 * reescritura. La primera version de esta reescritura (zero-phase,
 * sosfiltfilt-equivalente) llego a 0.32x tiempo real (79.5s) — sigue sin
 * alcanzar. Sec.172 midio que el filtro zero-phase cuesta ~2x el causal
 * (benchmark en Python, clasificacion de kurtosis 99.3% igual entre ambos
 * en datos reales) — esta version pasa a causal por ese motivo.
 *
 * NO calcula los coeficientes del filtro (evita reimplementar el diseño
 * Butterworth en C, riesgo de un bug numerico sutil): los recibe ya
 * calculados por scipy.signal.butter desde el wrapper Python
 * (exportar_paquete_area_c.py), en un archivo de texto simple. Este
 * programa solo aplica esos coeficientes — la parte que de verdad hace
 * falta que sea rapida.
 *
 * Uso:
 *   paquete_area <archivo.bin> <coefs.txt> <fs_hz> <v_ref> <ventana_s>
 *                <bloque_s> <margen_s> <dual:0|1> <salida.json>
 *
 * Formato de coefs.txt: primera linea con la cantidad de secciones SOS,
 * despues una linea por seccion con "b0 b1 b2 a1 a2" (a0 siempre 1.0,
 * scipy normaliza asi el formato 'sos' — no se incluye).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>

#define MARKER_LEN 12
#define OFF_SIZE_CH 4
#define MAX_SECCIONES 16

typedef struct { double b0, b1, b2, a1, a2; } Seccion;
typedef struct { float b0, b1, b2, a1, a2; } SeccionF;

typedef struct {
    double *t, *area, *kurt;
    size_t n, cap;
} Salida;

static void salida_agregar(Salida *s, double t, double area, double kurt) {
    if (s->n == s->cap) {
        s->cap = s->cap ? s->cap * 2 : 1024;
        s->t = realloc(s->t, s->cap * sizeof(double));
        s->area = realloc(s->area, s->cap * sizeof(double));
        s->kurt = realloc(s->kurt, s->cap * sizeof(double));
    }
    s->t[s->n] = t;
    s->area[s->n] = area;
    s->kurt[s->n] = kurt;
    s->n++;
}

/* --- Filtro CAUSAL, una sola pasada (equivalente a scipy.signal.sosfilt,
 * sin el ajuste de condiciones iniciales de scipy: arranca en silencio
 * (zi=0) en vez de estado estacionario). El margen IZQUIERDO entre bloques
 * (>=195312 muestras en el uso real, >> los ~437 muestras que mide el
 * asentamiento real del filtro, ver docs/plan del feature) hace que el
 * transitorio de arranque decaiga del todo antes de llegar al tramo "core"
 * que de verdad se usa — validado numericamente contra la version
 * Python/SciPy (99.3% de coincidencia de clasificacion en datos reales,
 * sec.172). El margen DERECHO ya no hace falta para este filtro (solo
 * miraba "adelante" para la pasada inversa del zero-phase, que ya no
 * existe) — se mantiene por ahora sin tocar el resto del pipeline de
 * bloques, es inofensivo, solo un poco de trabajo de mas.
 *
 * En simple precision (float) a proposito, no double: medido en HW real
 * (placa Zynq 7010, Cortex-A9) — el doble precision puro tardaba ~4-5x mas
 * que Python/SciPy solo con -O3 (no alcanzaba), la FPU de este core (VFPv3,
 * sin NEON de doble precision) es mucho mas rapida en simple precision. La
 * señal ya se guarda en float32 en el .bin original (int16) y
 * _filtrar_pasabanda de la version Python igual castea el resultado a
 * float32 al final — no se pierde precision real que ya existiera antes. --- */
static void aplicar_sos_inplace(const SeccionF *sos, int n_sec, float *x, long n) {
    for (int s = 0; s < n_sec; s++) {
        float z1 = 0.0f, z2 = 0.0f;
        const SeccionF *sc = &sos[s];
        for (long i = 0; i < n; i++) {
            float xi = x[i];
            float yi = sc->b0 * xi + z1;
            z1 = sc->b1 * xi - sc->a1 * yi + z2;
            z2 = sc->b2 * xi - sc->a2 * yi;
            x[i] = yi;
        }
    }
}

/* --- Lectura del .bin (mismo formato que revisar.py::_iterar_segmentos) --- */

static int detectar_header_size(FILE *f, long tam) {
    int candidatos[2] = {144, 112};
    unsigned char header[144];
    for (int c = 0; c < 2; c++) {
        int candidato = candidatos[c];
        if (candidato + MARKER_LEN > tam) continue;
        fseek(f, 0, SEEK_SET);
        if ((long)fread(header, 1, candidato, f) != candidato) continue;
        uint32_t size_ch[4];
        memcpy(size_ch, header + OFF_SIZE_CH, sizeof(size_ch));
        long marker_off = candidato + (long)size_ch[0] + size_ch[1] + size_ch[2] + size_ch[3];
        if (marker_off + MARKER_LEN > tam) continue;
        fseek(f, marker_off, SEEK_SET);
        unsigned char marker[MARKER_LEN];
        if ((long)fread(marker, 1, MARKER_LEN, f) != MARKER_LEN) continue;
        int ok = 1;
        for (int i = 0; i < MARKER_LEN; i++) if (marker[i] != 0xFF) { ok = 0; break; }
        if (ok) return candidato;
    }
    return -1;
}

/* --- Estado del procesamiento por bloques --- */

typedef struct {
    double *residual;
    size_t n_residual;
    Salida salida;
} Canal;

/* Filtra el bloque COMPLETO (margen+core+margen, ya en Volts, en float —
 * ver nota de precision en aplicar_sos_inplace) y agrega a `canal` las
 * ventanas completas que se puedan armar con residual_anterior+core — ver
 * area_kurtosis.py::_area_kurtosis_de_bloque (misma logica, ya validada
 * contra la version Python). El residual y las sumas de ventana SI quedan
 * en double (mismo criterio que _area_por_ventana/_kurtosis_por_ventana de
 * Python, que castean la ventana a float64 antes de sumar) — son arrays
 * chicos (una ventana, ~195k muestras), no el cuello de botella. */
static void procesar_canal(const SeccionF *sos, int n_sec, float *volts_bloque, long n_total,
                            long n_izq, long n_core_real, double fs, double ventana_s,
                            double t_offset_s, Canal *canal) {
    aplicar_sos_inplace(sos, n_sec, volts_bloque, n_total);
    float *core = volts_bloque + n_izq;

    long n_combinado = (long)canal->n_residual + n_core_real;
    double *combinado = malloc((n_combinado > 0 ? n_combinado : 1) * sizeof(double));
    if (canal->n_residual) memcpy(combinado, canal->residual, canal->n_residual * sizeof(double));
    for (long i = 0; i < n_core_real; i++) combinado[canal->n_residual + i] = (double)core[i];

    long n_ventana = (long)(fs * ventana_s);
    if (n_ventana < 1) n_ventana = 1;
    long n_completas = n_combinado / n_ventana;
    long usado = n_completas * n_ventana;

    for (long k = 0; k < n_completas; k++) {
        double *ventana = combinado + k * n_ventana;
        double suma_abs = 0.0, suma = 0.0;
        for (long i = 0; i < n_ventana; i++) {
            suma_abs += fabs(ventana[i]);
            suma += ventana[i];
        }
        double area = suma_abs / fs;
        double media = suma / (double)n_ventana;
        double m2 = 0.0, m4 = 0.0;
        for (long i = 0; i < n_ventana; i++) {
            double d = ventana[i] - media;
            double d2 = d * d;
            m2 += d2;
            m4 += d2 * d2;
        }
        m2 /= (double)n_ventana;
        m4 /= (double)n_ventana;
        double kurt = m4 / (m2 > 0.0 ? m2 * m2 : 1e-30);
        double t_local = (k + 0.5) * ventana_s;
        double t_abs = t_local + t_offset_s - (double)canal->n_residual / fs;
        salida_agregar(&canal->salida, t_abs, area, kurt);
    }

    size_t n_nuevo_residual = (size_t)(n_combinado - usado);
    double *nuevo_residual = malloc((n_nuevo_residual ? n_nuevo_residual : 1) * sizeof(double));
    if (n_nuevo_residual) memcpy(nuevo_residual, combinado + usado, n_nuevo_residual * sizeof(double));
    free(canal->residual);
    canal->residual = nuevo_residual;
    canal->n_residual = n_nuevo_residual;

    free(combinado);
}

static float *a_volts(const int16_t *i16, long n, double v_ref) {
    float *v = malloc((n > 0 ? n : 1) * sizeof(float));
    float factor = (float)(v_ref / 32767.0);
    for (long i = 0; i < n; i++) v[i] = i16[i] * factor;
    return v;
}

static float *diferencia_a_volts(const int16_t *a, const int16_t *b, long n, double v_ref) {
    float *v = malloc((n > 0 ? n : 1) * sizeof(float));
    float factor = (float)(v_ref / 32767.0);
    for (long i = 0; i < n; i++) v[i] = ((float)a[i] - (float)b[i]) * factor;
    return v;
}

/* Arma un bloque (cola + hasta n_core+n_margen de buf) y lo procesa por
 * canal (IN1, IN2 y Limpia si dual) — equivalente a _flush +
 * _area_kurtosis_de_bloque de area_kurtosis.py. Se llama tanto cuando ya
 * se acumulo un bloque completo como una unica vez al final (con lo que
 * haya quedado, aunque sea menos de un bloque entero: min() se encarga). */
static void flush_bloque(const SeccionF *sos, int n_sec, double fs, double v_ref,
                          double ventana_s, long n_core, long n_margen, int dual,
                          int16_t *buf0, int16_t *buf1, long *n_buf,
                          int16_t *cola0, int16_t *cola1, long *n_cola,
                          long *muestras_core_emitidas,
                          Canal *in1, Canal *in2, Canal *limpia) {
    long n_izq = *n_cola;
    long n_core_real = n_core < *n_buf ? n_core : *n_buf;
    long n_der = *n_buf - n_core_real;
    if (n_der > n_margen) n_der = n_margen;
    long n_total = n_izq + n_core_real + n_der;

    int16_t *raw0 = malloc((n_total > 0 ? n_total : 1) * sizeof(int16_t));
    memcpy(raw0, cola0, n_izq * sizeof(int16_t));
    memcpy(raw0 + n_izq, buf0, (n_core_real + n_der) * sizeof(int16_t));

    double t_offset_s = (double)*muestras_core_emitidas / fs;
    float *v0 = a_volts(raw0, n_total, v_ref);
    procesar_canal(sos, n_sec, v0, n_total, n_izq, n_core_real, fs, ventana_s, t_offset_s, in1);
    free(v0);

    int16_t *raw1 = NULL;
    if (dual) {
        raw1 = malloc((n_total > 0 ? n_total : 1) * sizeof(int16_t));
        memcpy(raw1, cola1, n_izq * sizeof(int16_t));
        memcpy(raw1 + n_izq, buf1, (n_core_real + n_der) * sizeof(int16_t));

        float *v1 = a_volts(raw1, n_total, v_ref);
        procesar_canal(sos, n_sec, v1, n_total, n_izq, n_core_real, fs, ventana_s, t_offset_s, in2);
        free(v1);

        float *vl = diferencia_a_volts(raw0, raw1, n_total, v_ref);
        procesar_canal(sos, n_sec, vl, n_total, n_izq, n_core_real, fs, ventana_s, t_offset_s, limpia);
        free(vl);
    }

    /* nueva cola (margen para el proximo bloque) = ultimas n_margen
     * muestras de (cola + core real) — se arma ANTES de liberar raw0/raw1 */
    long n_core_hasta_ahora = n_izq + n_core_real;
    long n_nueva_cola = n_core_hasta_ahora < n_margen ? n_core_hasta_ahora : n_margen;
    memmove(cola0, raw0 + (n_core_hasta_ahora - n_nueva_cola), n_nueva_cola * sizeof(int16_t));
    if (dual) memmove(cola1, raw1 + (n_core_hasta_ahora - n_nueva_cola), n_nueva_cola * sizeof(int16_t));
    *n_cola = n_nueva_cola;
    free(raw0);
    if (dual) free(raw1);

    *muestras_core_emitidas += n_core_real;

    /* correr el buffer: descartar lo usado como CORE; lo usado como margen
     * derecho ("espiado" para el asentamiento del filtro de este bloque)
     * NO se descarta — se vuelve a leer como parte del proximo bloque. */
    long resto = *n_buf - n_core_real;
    memmove(buf0, buf0 + n_core_real, resto * sizeof(int16_t));
    if (dual) memmove(buf1, buf1 + n_core_real, resto * sizeof(int16_t));
    *n_buf = resto;
}

int main(int argc, char **argv) {
    if (argc != 10) {
        fprintf(stderr,
            "uso: %s <archivo.bin> <coefs.txt> <fs_hz> <v_ref> <ventana_s> "
            "<bloque_s> <margen_s> <dual:0|1> <salida.json>\n", argv[0]);
        return 1;
    }
    const char *ruta_bin = argv[1];
    const char *ruta_coefs = argv[2];
    double fs = atof(argv[3]);
    double v_ref = atof(argv[4]);
    double ventana_s = atof(argv[5]);
    double bloque_s = atof(argv[6]);
    double margen_s = atof(argv[7]);
    int dual = atoi(argv[8]);
    const char *ruta_salida = argv[9];

    FILE *fc = fopen(ruta_coefs, "r");
    if (!fc) { perror("coefs.txt"); return 1; }
    int n_sec;
    if (fscanf(fc, "%d", &n_sec) != 1 || n_sec <= 0 || n_sec > MAX_SECCIONES) {
        fprintf(stderr, "coefs.txt invalido\n"); return 1;
    }
    Seccion sos_d[MAX_SECCIONES];
    for (int i = 0; i < n_sec; i++) {
        if (fscanf(fc, "%lf %lf %lf %lf %lf",
                   &sos_d[i].b0, &sos_d[i].b1, &sos_d[i].b2, &sos_d[i].a1, &sos_d[i].a2) != 5) {
            fprintf(stderr, "coefs.txt invalido (seccion %d)\n", i); return 1;
        }
    }
    fclose(fc);
    /* Los coeficientes se leen en double (los manda scipy con esa
     * precision) pero el filtro corre en float (ver nota de precision en
     * aplicar_sos_inplace) — se convierten una sola vez aca, no en el loop. */
    SeccionF sos[MAX_SECCIONES];
    for (int i = 0; i < n_sec; i++) {
        sos[i].b0 = (float)sos_d[i].b0;
        sos[i].b1 = (float)sos_d[i].b1;
        sos[i].b2 = (float)sos_d[i].b2;
        sos[i].a1 = (float)sos_d[i].a1;
        sos[i].a2 = (float)sos_d[i].a2;
    }

    FILE *f = fopen(ruta_bin, "rb");
    if (!f) { perror(ruta_bin); return 1; }
    fseek(f, 0, SEEK_END);
    long tam = ftell(f);
    int header_size = detectar_header_size(f, tam);
    if (header_size < 0) {
        fprintf(stderr, "no se pudo determinar el tamaño de header de %s\n", ruta_bin);
        return 1;
    }

    long n_core = (long)llround(fs * bloque_s);
    if (n_core < 1) n_core = 1;
    long n_margen = (long)llround(fs * margen_s);
    if (n_margen < 1) n_margen = 1;

    size_t cap_buf = (size_t)(n_core + n_margen) * 2 + 8192;
    int16_t *buf0 = malloc(cap_buf * sizeof(int16_t));
    int16_t *buf1 = dual ? malloc(cap_buf * sizeof(int16_t)) : NULL;
    long n_buf = 0;

    int16_t *cola0 = malloc((size_t)(n_margen > 0 ? n_margen : 1) * sizeof(int16_t));
    int16_t *cola1 = dual ? malloc((size_t)(n_margen > 0 ? n_margen : 1) * sizeof(int16_t)) : NULL;
    long n_cola = 0;

    long muestras_core_emitidas = 0;
    Canal in1 = {0}, in2 = {0}, limpia = {0};

    long pos = 0;
    while (pos + header_size <= tam) {
        unsigned char header[144];
        fseek(f, pos, SEEK_SET);
        if ((long)fread(header, 1, header_size, f) != header_size) break;
        uint32_t size_ch[4];
        memcpy(size_ch, header + OFF_SIZE_CH, sizeof(size_ch));
        long fin_datos = pos + header_size + (long)size_ch[0] + size_ch[1] + size_ch[2] + size_ch[3];
        if (fin_datos + MARKER_LEN > tam) {
            fprintf(stderr, "[!] segmento truncado al final del archivo (offset %ld), se descarta\n", pos);
            break;
        }

        long muestras_nuevas0 = size_ch[0] / 2;
        if ((size_t)(n_buf + muestras_nuevas0) > cap_buf) {
            cap_buf = (size_t)(n_buf + muestras_nuevas0) * 2;
            buf0 = realloc(buf0, cap_buf * sizeof(int16_t));
            if (dual) buf1 = realloc(buf1, cap_buf * sizeof(int16_t));
        }
        fseek(f, pos + header_size, SEEK_SET);
        if (fread(buf0 + n_buf, 1, size_ch[0], f) != size_ch[0]) {
            fprintf(stderr, "[!] lectura incompleta de datos ch0 (offset %ld), se descarta\n", pos);
            break;
        }
        if (dual && fread(buf1 + n_buf, 1, size_ch[1], f) != size_ch[1]) {
            fprintf(stderr, "[!] lectura incompleta de datos ch1 (offset %ld), se descarta\n", pos);
            break;
        }
        n_buf += muestras_nuevas0;

        fseek(f, fin_datos, SEEK_SET);
        unsigned char marker[MARKER_LEN];
        if (fread(marker, 1, MARKER_LEN, f) != MARKER_LEN) {
            fprintf(stderr, "[!] no se pudo leer el marcador (offset %ld), se descarta\n", fin_datos);
            break;
        }
        int marker_ok = 1;
        for (int i = 0; i < MARKER_LEN; i++) if (marker[i] != 0xFF) { marker_ok = 0; break; }
        if (!marker_ok) {
            fprintf(stderr, "[!] marcador invalido (offset %ld), se corta la lectura ahi\n", fin_datos);
        }

        if (n_buf >= n_core + n_margen) {
            flush_bloque(sos, n_sec, fs, v_ref, ventana_s, n_core, n_margen, dual,
                         buf0, buf1, &n_buf, cola0, cola1, &n_cola,
                         &muestras_core_emitidas, &in1, &in2, &limpia);
        }

        if (!marker_ok) break;
        pos = fin_datos + MARKER_LEN;
    }
    fclose(f);

    if (n_buf > 0) {
        flush_bloque(sos, n_sec, fs, v_ref, ventana_s, n_core, n_margen, dual,
                     buf0, buf1, &n_buf, cola0, cola1, &n_cola,
                     &muestras_core_emitidas, &in1, &in2, &limpia);
    }

    FILE *out = fopen(ruta_salida, "w");
    if (!out) { perror(ruta_salida); return 1; }
    const char *nombre_archivo = strrchr(ruta_bin, '/') ? strrchr(ruta_bin, '/') + 1 : ruta_bin;
    fprintf(out, "{\"archivo\":\"%s\",\"fs_hz\":%.6f,\"ventana_s\":%.6f,\"canales\":[",
            nombre_archivo, fs, ventana_s);

    const char *nombres[3] = {"IN1", "IN2", "Limpia (IN1-IN2)"};
    Canal *canales[3] = {&in1, &in2, &limpia};
    int n_canales = dual ? 3 : 1;
    for (int c = 0; c < n_canales; c++) {
        Canal *canal = canales[c];
        fprintf(out, "%s{\"canal\":\"%s\",\"t_centro_s\":[", c ? "," : "", nombres[c]);
        for (size_t i = 0; i < canal->salida.n; i++) fprintf(out, "%s%.6f", i ? "," : "", canal->salida.t[i]);
        fprintf(out, "],\"area\":[");
        for (size_t i = 0; i < canal->salida.n; i++) fprintf(out, "%s%.9g", i ? "," : "", canal->salida.area[i]);
        fprintf(out, "],\"kurtosis\":[");
        for (size_t i = 0; i < canal->salida.n; i++) fprintf(out, "%s%.9g", i ? "," : "", canal->salida.kurt[i]);
        fprintf(out, "]}");
    }
    fprintf(out, "]}\n");
    fclose(out);

    fprintf(stderr, "[OK] %s: %d canal(es), %zu ventanas (IN1)\n", ruta_salida, n_canales, in1.salida.n);
    return 0;
}
