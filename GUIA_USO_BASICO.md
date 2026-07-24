# Guía de uso básico — Sand Monitoring

Todo lo que sigue corre por SSH contra la Red Pitaya, salvo el paso de revisar datos
(eso corre en la PC).

---

## Flujo típico completo

### 1. Encender

Conectar la alimentación de la placa (batería + panel solar en campo, fuente en banco).
Esperar que bootee y conectarse por SSH:

```bash
ssh root@<IP_PLACA>
```

La IP depende de cómo está conectada la placa (router, o RJ45 directo a la PC) — ver
`scripts_campo/PLAN_CAMPO.md` → "IPs según topología de red".

### 2. Prender el Starlink (si el relé ya está instalado en esta placa)

En el sitio real, el relé se prende y apaga solo por horario (`starlink-rele-on/off.timer`,
configurado en `config_campo.json`) — no hace falta hacer nada. `prender-starlink` es para
forzarlo a mano cuando se necesita acceso fuera de ese horario, o en banco/pruebas donde
todavía no hay Starlink real conectado:

```bash
prender-starlink   # pulsa el relé a "on"
```

Si esta placa todavía no tiene el relé instalado, saltear este paso — no es necesario para
capturar, solo controla el link de datos remoto.

### 3. Verificar que el USB está listo (si se captura a `usb`)

```bash
df -h /mnt/usb
```

Si no aparece montado, ver `scripts_campo/plan_campo/operacion_campo.md` → paso 2 (montaje
a mano).

### 4. Lanzar la captura

**Mono (1 canal, captura corta de prueba — 4 chunks de 30s, 2 minutos total):**

```bash
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo --duracion_chunk 0.5 --duracion_total 2 --directorio /mnt/usb
```

**Dual (2 canales, sensor de referencia en IN2):**

```bash
python3 /root/scripts_campo/capturar_stream.py \
  --condicion reposo --canales 2 --decimacion 64 \
  --duracion_chunk 0.5 --duracion_total 2 --directorio /mnt/usb
```

`--condicion` es `reposo` o `con_arena` según lo que se esté probando. `--duracion_total`
hace que la sesión termine sola (acá, 2 minutos) — sin esto corre indefinido hasta
`Ctrl+C` (corta al terminar el chunk en curso). Para sesiones largas o sin supervisión
(de noche), usar el supervisor en vez del script solo — ver "Otros casos de uso" abajo.

Detalle completo de parámetros y qué se ve en pantalla:
`scripts_campo/plan_campo/operacion_campo.md`.

### 5. Terminar la captura

Con `--duracion_total` (como arriba) termina sola. Si se lanzó sin ese límite, `Ctrl+C` y
esperar a que cierre el chunk en curso (no matar el proceso a la fuerza).

### 6. Sacar los datos

Quedan en:

```
/mnt/usb/stream_adc/
  session_reposo_..._info.json
  campo_reposo_..._0001.bin
  campo_reposo_..._0002.bin
  ...
```

**Si estás en el sitio, con acceso físico a la placa:** desconectar el pendrive — el
automontaje se encarga de desmontarlo solo al detectar la desconexión, no hace falta un
comando de umount manual. Conectarlo a la PC y copiar la carpeta directo.

**Si el equipo no está al alcance (remoto, vía Starlink):**

- **Por SSH/scp**, cuando la placa se puede alcanzar directo por IP (misma red, o IP
  pública del Starlink sin CGNAT):

  ```bash
  scp -r root@<IP_PLACA>:/mnt/usb/stream_adc/ /home/facu-edge/datos_campo/
  ```

- **Por "agujero de gusano" (`magic-wormhole`)**, cuando no hay forma de alcanzar la
  placa directo (sin IP pública, detrás de CGNAT) — no necesita puertos abiertos ni IP
  fija en ninguno de los dos lados, solo que ambos tengan salida a internet (instalar una
  vez con `apt install magic-wormhole` o `pip install magic-wormhole`):

  ```bash
  # en la placa (root@<IP_PLACA>)
  wormhole send /mnt/usb/stream_adc/

  # en la PC, con el código que imprime el comando anterior
  wormhole receive <codigo>
  ```

(Si se capturó con `--destino red` en vez de `usb`, los archivos ya llegaron solos a la
PC durante la captura — no hace falta ninguno de estos pasos, ver "Otros casos de uso"
abajo.)

### 7. Revisar los datos (en la PC)

```bash
.venv/bin/python3 analisis/revisar.py /ruta/a/stream_adc/
```

Detecta solo si cada archivo es mono o dual y muestra kurtosis, crest factor, fracción
activa por archivo (más métricas cruzadas CH1/CH2 si es dual). Cómo interpretar los
números: `analisis/INTERPRETACION_RESULTADOS.md`.

### 8. Apagar el Starlink (si corresponde)

```bash
apagar-starlink
```

Corta la sesión SSH en el momento si se estaba conectado a través del mismo Starlink —
es lo esperado, no un error.

### 9. Apagar la placa

Apagado prolijo por SSH antes de cortar alimentación física, si se puede:

```bash
shutdown -h now
```

---

## Otros casos de uso

| Caso | Qué cambia del flujo típico |
|---|---|
| **Sesión larga o de noche, sin supervisión** | Lanzar con el supervisor en vez de `capturar_stream.py` solo: `bash /root/relanzar_captura.sh /root/scripts_campo/capturar_stream.py --condicion reposo --directorio /mnt/usb`. Relanza sola si crashea (bug conocido de la librería), no si termina limpio. |
| **Sin pendrive, directo a la PC por red** | Agregar `--destino red --pc_host usuario@IP --pc_ruta /ruta/en/pc` al comando de captura. Los archivos llegan solos a la PC, se saltea el paso 6 completo. |
| **Prueba rápida de banco (sin guardar nada)** | `probar_dual_stream.py` — captura corta de solo lectura para chequear que los 2 canales están bien mapeados, no toca el USB. Usar antes de confiar en una captura dual nueva. |
| **Cambiar el horario del Starlink** | Editar `starlink.hora_on`/`hora_off` en `scripts_campo_comun/config_campo.json`, después correr `/root/starlink_remoto/aplicar_horario.sh` en la placa. No tocar los `.timer` a mano. |
| **Desactivar el horario automático del Starlink** (ej. pruebas de campo) | `systemctl disable --now starlink-rele-on.timer starlink-rele-off.timer` en la placa. `prender-starlink`/`apagar-starlink` siguen funcionando igual. |

---

## Referencias (para más detalle)

- Todos los comandos y sus argumentos: `COMANDOS.md`
- Guía operativa completa de campo (setup, topologías de red, troubleshooting):
  `scripts_campo/PLAN_CAMPO.md` y `scripts_campo/plan_campo/`
- Arquitectura e historial del control remoto del relé: `starlink_remoto/HISTORIAL_STARLINK.md`
- Interpretación de resultados de `revisar.py`: `analisis/INTERPRETACION_RESULTADOS.md`
