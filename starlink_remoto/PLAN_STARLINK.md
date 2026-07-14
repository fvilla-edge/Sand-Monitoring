# Acceso remoto vía Starlink con relé

## Contexto

Fase 1: equipo en campo con el usuario presente, haciendo pruebas y validando datos.
Fase 2: equipo queda solo en el sitio. La Red Pitaya no captura todo el tiempo — arranca
y para las capturas a demanda (orden del usuario, ej. para actualizar scripts). El
acceso remoto es por SSH a la Red Pitaya vía Starlink.

Para ahorrar energía, el kit Starlink (dish + router) se energiza solo durante una
ventana horaria fija, controlada por un relé. **Hoy el relé todavía no existe** — se
simula prendiendo/apagando el LED0 de la propia Red Pitaya, para poder probar toda la
lógica de horarios y de sincronización de reloj sin depender del hardware.

## Arquitectura

| Componente | Rol | Alimentación |
|---|---|---|
| Red Pitaya (la misma que corre `scripts_campo/`) | Corre los timers, controla el relé, corre las capturas cuando se le pide | Siempre encendida, fuente propia del sitio |
| Relé (simulado hoy con LED0) | Corta/habilita alimentación del kit Starlink | Controlado por escritura directa de registro desde la Red Pitaya |
| Starlink (dish + router) | Da conectividad para el SSH entrante | Detrás del relé — apagado por default |

Asunción a reconfirmar en sitio: el plan de Starlink da IP pública/gestionable, así que
el SSH entrante llega directo sin túnel intermedio (Tailscale, WireGuard, etc.). Si en
la práctica resulta ser CGNAT, este plan no alcanza y hace falta agregar esa capa.

## Cómo funciona

No hay `cron` instalado en esta placa (Ubuntu 24.04 mínimo, sin el paquete). Se usa
**systemd timers**, el reemplazo nativo — mismo concepto que cron, pero como parte del
propio systemd (que ya está siempre corriendo), sin instalar nada extra.

Son 3 archivos, todos en `starlink_remoto/`:

| Archivo | Qué es |
|---|---|
| `control_starlink.sh` | El script que realmente prende/apaga (hoy: el LED0; el día del relé real, cambia acá adentro nomás) |
| `systemd/starlink-rele@.service` | La "tarjeta" que dice qué hacer: correr `control_starlink.sh on` o `control_starlink.sh off` |
| `systemd/starlink-rele-on.timer` / `-off.timer` | Las "tarjetas" que dicen cuándo: 08:55 y 17:00 hora Argentina, todos los días |

El `on` además reintenta forzar la hora: reinicia `ntpsec` (que ya viene instalado en
esta placa), lo que dispara un `STEP` — corrección inmediata del reloj — en vez de
esperar el ciclo de sincronización normal, que puede tardar minutos. Esto importa
porque la placa no tiene RTC: el reloj sigue corriendo solo con el oscilador local
durante las ~16 hs sin red, así que puede llegar levemente desviado a cada ventana.

## Instalación (ya hecha en la placa 192.168.0.55, dejar acá para reflashear o replicar)

```bash
cd starlink_remoto

# copiar el script de control
scp control_starlink.sh root@<IP_PLACA>:/root/starlink_remoto/

# copiar las unidades systemd
scp systemd/starlink-rele@.service systemd/starlink-rele-on.timer systemd/starlink-rele-off.timer \
    root@<IP_PLACA>:/etc/systemd/system/

# instalar y activar
ssh root@<IP_PLACA> "
  chmod +x /root/starlink_remoto/control_starlink.sh
  systemctl daemon-reload
  systemctl enable --now starlink-rele-on.timer starlink-rele-off.timer
"
```

## Operación día a día

```bash
# ver cuándo dispara cada timer a continuación
ssh root@<IP_PLACA> "systemctl list-timers 'starlink*' --all"

# probar a mano ahora mismo, sin esperar el horario
ssh root@<IP_PLACA> "systemctl start starlink-rele@on.service"   # o @off.service

# ver si corrió bien y cuándo (incluye errores si los hay)
ssh root@<IP_PLACA> "journalctl -u starlink-rele@on.service"

# ver el estado actual simulado (1 = "prendido", 0 = "apagado")
ssh root@<IP_PLACA> "/opt/redpitaya/bin/monitor 0x40000030"
```

Para cambiar el horario: editar la línea `OnCalendar=` del `.timer` correspondiente
(local y en la placa), y en la placa correr `systemctl daemon-reload && systemctl
restart starlink-rele-on.timer` (o `-off.timer`). No hay que tocar el script.

## Validado en banco (placa real, sin Starlink conectado)

- `rp.rp_LEDSetState()` (propuesta inicial) **falla**: `rp_Init()` inicializa también
  el osciloscopio y choca (`Bus error`) con el `streaming-server` corriendo, que tiene
  el UIO del osciloscopio tomado en exclusiva. Por eso el control se hace con
  `/opt/redpitaya/bin/monitor 0x40000030 <valor>` — accede a la región de housekeeping,
  no a la del ADC, y no interfiere con una captura en curso.
- Ciclo completo `on`→`off`→`off` (idempotencia) probado disparando los `.service` a
  mano, LED y registro confirmados en cada paso, `streaming-server` sin interrupciones.
- Reloj desfasado a propósito (+30s, +45s) y corregido con `STEP` en menos de 10s tras
  el restart de `ntpsec` disparado por el propio `on`.
- Bug de zona horaria encontrado y corregido: la placa corre en UTC, así que
  `OnCalendar` sin zona explícita disparaba 3 hs antes de lo esperado. Se fijó con el
  sufijo `America/Argentina/Buenos_Aires` en cada `OnCalendar=`, sin tocar el reloj del
  sistema.

## Riesgos abiertos

| Riesgo | Estado |
|---|---|
| Starlink no queda usable al instante (boot + actualización de firmware) | Margen de 5 min antes de la hora "oficial"; el firmware update puede igual comerse parte de la ventana, sin mitigación total posible |
| Red Pitaya se cuelga/reinicia a mitad de ventana | `Persistent=true` en ambos timers dispara el que se perdió al volver a bootear, pero el estado *fail-safe* del relé físico (qué pasa sin señal de control) todavía no está definido — depende del modelo de relé |
| Drift real de reloj en 16 hs sin red | Mitigado con el restart de `ntpsec` en el `on`, pero no medido en campo real todavía |
| Asunción de IP pública resulta ser CGNAT | Reconfirmar con Starlink activo en sitio |

## Pendientes

- Modelo de relé y cableado físico: qué pin del conector de expansión de la Red
  Pitaya se usa, aislación, etc. — no definido todavía. Cuando esté, el cambio es
  únicamente en `control_starlink.sh` (reemplazar las dos líneas de `monitor
  0x40000030`).
- Confirmar el comportamiento fail-safe deseado del relé real.
- Decidir si esta carpeta se fusiona con `scripts_campo_comun/` (infraestructura
  compartida) una vez que el relé esté instalado, o queda separada.
