# Plan — IN2 como sensor independiente (área/kurtosis en la FPGA)

Estado: **etapas 1-4 hechas; etapa 5 espera el T de OUT1 a IN1+IN2** (2026-10-06). Reemplaza la "opción A" de
`docs/plan_dos_canales.md` (FPGA solo IN1, IN2 crudo): el IN2 tiene que
funcionar **igual que el IN1**, como un segundo sensor. Todo en la placa de
pruebas (`rp-f0fd8c`) hasta la última etapa; la placa de campo no se toca.

Regla del plan: **una etapa a la vez, cada una con un criterio de paso
medible y una vuelta atrás probada**. Si una etapa falla, se para ahí y se
entiende antes de seguir. Ninguna etapa mezcla FPGA y software nuevos a la
vez en el hardware.

## Punto de partida (verificado 2026-10-06)

- Bitstream en las dos placas: repo `fpga_pitaya`, rama `lectura-dio`,
  `7f23f7d` (Master fijo), Vivado 2025.1 (`~/vitis/2025.1`).
- `rp_oscilloscope.v` ya instancia `osc_top` **una vez por canal**
  (`generate` sobre `NUM_CHANNELS = 2`): cada canal tiene su decimador,
  su pasabanda y su acumulador. Pero `scope_cfg.sv` solo conecta a
  registros las sumas del **canal 0** (`0x328-0x348`). Las del canal 1 no
  salen a ningún lado, así que probablemente Vivado las eliminó al
  sintetizar (a confirmar, etapa 1a).
- Coeficientes del pasabanda (`0x300-0x324`) y largo de ventana (`0x328`)
  son **compartidos** por los dos canales: el C++ actual ya los configura
  para los dos sin cambios.
- Recursos del build actual: DSP 41/80 (51%), LUT 51%, BRAM 32%. Un
  segundo filtro + acumulador suma [Suposición] ~15-25 DSP -> ~70-80%.
  Entra, pero el timing ya costó cerrarlo una vez (port a 2026.1).
- Registro de ID `0x4020007C = 0x534D0001`: sirve para que el software sepa
  qué bitstream está cargado.

## Decisiones (usuario, 2026-10-06)

1. **Eventos independientes:** cada canal dispara y guarda **sus propios**
   eventos, sin interferir con el otro. Un evento del IN1 guarda solo el
   IN1 y uno del IN2 solo el IN2 (en dual, el IN1 deja de llevar el
   `_ch2.bin` de la Fase 1).
2. **Umbral del IN2:** propio (`UMBRAL2`), con el mismo valor que el IN1
   (hoy 3.4).
3. **CSV del IN2 aparte**, mismo formato. Propuesta de implementación:
   carpeta propia del IN2 (`<destino>/in2/`) con exactamente la misma
   estructura que la del IN1 (`evento_*.bin/.json`, `ventanas_*.csv`), así
   el visor, el organizador y el conversor a paquete sirven sin cambios.
   Hay que agregarla a la subida a GCS, al anotador y al control de
   espacio.
4. **Losant:** del IN2 alcanza con `kurt_max_1min_in2` y
   `area_max_1min_in2` (el detalle queda en los CSV).
5. **Mono** (`CANALES=1`): el IN2 no se calcula ni se reporta.

## Etapas

### Etapa 1 — RTL (repo `fpga_pitaya`, rama nueva desde `lectura-dio`)

- 1a. Confirmar en el reporte de síntesis jerárquico si el filtro +
  acumulador del canal 1 existen o fueron eliminados (cuánto agregan).
- 1b. 9 registros de solo lectura para el canal 1 a continuación de los del
  canal 0 (`0x34C-0x36C`: `window_count`, sumas |x|, x², x⁴), mismo
  formato. Verificar antes que esas direcciones estén libres.
- 1c. Subir el ID a `0x534D0002` (bitstream con IN2).
- **Paso:** compila la simulación sin warnings nuevos.
- **No cambia nada del canal 0** (mismas direcciones, misma lógica).

### Etapa 2 — Simulación (flujo `xsim` standalone que ya usamos)

- 2a. Regresión del canal 0: los mismos testbenches de siempre
  (`etapa4c_sim_bandpass.sh`, `etapa_simD_*`) tienen que dar lo mismo que
  antes, bit a bit.
- 2b. Canal 1 con **otra señal** que el canal 0 (p.ej. arena real en uno,
  reposo en el otro): cada canal coincide con el modelo Python y no se
  mezclan.
- 2c. `window_count` de los dos canales avanzan juntos.
- **Paso:** 2a idéntico, 2b dentro de lo ya aceptado para el canal 0.

### Etapa 3 — Build (Vivado 2025.1)

- Bitstream + `bootgen` (`.bit.bin`). Revisar timing (no peor que el build
  del 30/9) y recursos (DSP, LUT).
- **Si no cierra timing:** parar. Opciones a evaluar en ese momento
  (pipeline extra en el acumulador del canal 1, etc.), no improvisar.

### Etapa 4 — Placa de pruebas, solo registros (sin software nuevo)

- Cargar el bitstream nuevo en `rp-f0fd8c` con el método de siempre
  (`/opt/stream_app/fpga.bin`).
- 4a. **Compatibilidad hacia atrás:** el `capturar_eventos` actual (que no
  sabe nada del IN2) tiene que andar igual que hoy en mono y dual
  (mismos números de reposo, 0 saltadas). Esto es lo que permite
  actualizar campo sin cambiar el software a la vez.
- 4b. Con el stream corriendo en dual, leer a mano los registros nuevos
  (`window_count` del canal 1 avanza a 20/s junto con el del canal 0;
  área/kurtosis de reposo del IN2 con valores razonables).
- **Vuelta atrás:** volver a cargar el `fpga.bin` de `7f23f7d`.

### Etapa 5 — Loopback (necesita el T de OUT1 a IN1 + IN2)

- La misma señal entra a los dos canales: las sumas del IN1 y del IN2
  tienen que coincidir (salvo diferencias de ganancia de cada entrada).
- Pulsos y un tramo real de arena: kurtosis alta en los dos a la vez, en
  la misma ventana.
- Aprovechar para la prueba de forma de banda a dec64 con tonos (pendiente
  de la Fase 1b).

### Etapa 6 — C++ (`capturar_eventos`)

- Leer el ID; si es `0x534D0002` y `--canales 2`, leer también las sumas
  del canal 1. Con el bitstream viejo, seguir como hoy (sin IN2).
- Área/kurtosis del IN2 por ventana, disparo propio con `--umbral2`,
  eventos y CSV del IN2 en su carpeta (decisiones 1 y 3). El IN1 deja de
  guardar `_ch2.bin`.
- Pruebas en lab: reposo dual, escritura sostenida (tipo W15d64), disco
  lleno, mono después de dual.

### Etapa 7 — Anotador, Losant, PC

- `resumen_modo_evento.py`: `kurt_max_1min_in2` y `area_max_1min_in2`.
  `subir_csv_gcs.py`: la carpeta del IN2. Visor y organizador: sin cambios
  (misma estructura de carpeta).
- Crear los atributos en Losant (`test_SC` primero).

### Etapa 8 — Prueba larga en lab y vuelta atrás completa

- Una noche en dual con todo nuevo.
- Ensayar la vuelta atrás entera: bitstream `7f23f7d` + binario anterior.

### Etapa 9 — Campo (fecha a decidir)

- Bitstream con el procedimiento de actualización remota segura (Punto 5
  del repo `fpga_pitaya`).
- Primero **solo el bitstream con el software actual en mono** (etapa 4a
  en campo); recién después el software nuevo; recién después dual.
- Antes de dual: confirmar físicamente qué hay en el IN2 de campo y su
  jumper. El umbral del IN2 se calibra con datos de campo.

## Riesgos conocidos

- **Timing/recursos** (etapa 3): es donde más puede trabarse.
- **Bitstream de campo**: es la operación más delicada de todo el plan; por
  eso va sola y con el software viejo primero.
- El umbral y la escala del IN2 no se conocen hasta medir su sensor real.

## Bitácora

- 2026-10-06, etapa 1 (repo `fpga_pitaya`, rama `in2-sensor` desde
  `lectura-dio 7f23f7d`, sin commitear): `scope_cfg.sv` +32 líneas
  (registros del canal 1 `0x34C-0x368`, `AREA_ID` `0x36C = 0x534D0002`),
  `rp_oscilloscope.v` +8 líneas (cableado del canal 1 que ya instanciaba el
  `generate`). Camino de datos (`osc_top`, filtro, acumulador) sin tocar.
  OJO: `rp_oscilloscope.v` mezcla CRLF y LF; editar en binario.
- 2026-10-06, etapa 2: simulación nueva `etapa_simE_in2.sh` /
  `tb_rp_oscilloscope_simE.sv` (`rp_oscilloscope` completo, decimación 32
  por AXI, tono de 150kHz con el IN2 al doble de amplitud): **8/8 OK**,
  cocientes canal1/canal0 = 2.0014 (|x|), 4.0055 (x²), 16.04 (x⁴); ID ok;
  window_count iguales; AXI del canal 1 = salidas internas del 2.º
  `osc_top`. Regresión: diag5 7/7, bandpass 45897/45897, área 4/4, simB
  2/2, simC 2/2, dio 12/12, simD (4) completas sin error (no compilan los
  archivos tocados: idénticas por construcción).
  - Con el factor de decimación por defecto (0 = una muestra por ciclo) el
    biquad se descontrola (sumas que no dependen de la entrada): modo que
    la placa no usa; la simulación D ya corría con 32 por eso.
  - Vivado 2025.1 (`~/vitis/2025.1`) fuerza `LC_ALL=en_US.UTF-8`, que hoy no
    está instalado en la PC (aborta con `locale::facet::_S_create_c_locale`).
    Arreglo sin tocar el sistema: `localedef -i en_US -f UTF-8 DIR/en_US.UTF-8`
    y `export LOCPATH=DIR` antes de correr.
- 2026-10-06, etapa 3 (commit `20ac88b`): build Vivado 2025.1, ~20 min.
  **Timing cumplido** (WNS +0.157ns, antes +0.155ns). DSP 58/80 (72.5%,
  antes 41: +17 = filtro + acumulador del canal 1, que antes Vivado
  eliminaba), LUT 52.6% (51.5%), registros 37.2% (35.5%).
  `out/red_pitaya.bin` md5 `b34cd26f…`, mismo encabezado que el de campo.
  Copias: `~/bitstreams/in2_20ac88b_red_pitaya.bin` y
  `~/bitstreams/campo_7f23f7d_red_pitaya.bin` (md5 `1e6b2cf2…`, el de las
  placas); carpeta `out/` del 30/9 completa en
  `~/respaldo_bitstream_7f23f7d_out`. Tropiezos (documentados en
  `COMPILAR.md` del repo fpga): el objetivo es `out/red_pitaya.bin` (no
  `.bit.bin`) y `write_cfgmem` falla si quedó un `.prm` viejo.
- 2026-10-06, etapa 4 (`rp-f0fd8c`): `/opt/stream_app/fpga.bin` = bitstream
  IN2 (md5 `b34cd26f…`), respaldo `fpga.bin.bak_7f23f7d_20261006`.
  **Software actual sin tocar**: mono (dec32) y dual (dec64) andan igual que
  con el bitstream viejo (20 ventanas/s, 100% muestras, 0 saltadas, IN2 del
  stream al 100% y desfase 0). Registros nuevos (`leer_in2.py`, solo
  lectura): ID `0x534d0002`; `window_count` del canal 1 = canal 0 en cada
  ventana; reposo IN2 área ~0.507 / kurtosis ~2.97 a dec32 y ~0.563 / ~3.0
  a dec64 (IN1: ~0.515 y ~0.578), valores propios ventana a ventana.
  - **Reinicio de la placa por error mío:** leí los registros (`/dev/mem`)
    segundos después de `systemctl start`, mientras `overlay.sh` recargaba
    el bitstream. Lectura AXI con el PL reconfigurándose -> CPU colgada ->
    watchdog a los 30s (18:10:56 -> reinicio 18:11:26). El drop-in recién
    escrito quedó con 85 bytes en cero (sin `sync`). Repetido bien (leer
    recién después de "Calibracion"): sin problemas. Regla: nunca leer
    registros del PL durante un arranque de modo-evento; `sync` después de
    escribir configs en las placas.
  - Placa de pruebas queda en **mono con el bitstream IN2** y el software
    actual (prueba de compatibilidad corriendo).

