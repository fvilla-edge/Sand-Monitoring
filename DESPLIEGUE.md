# Despliegue — qué hacer después de tocar cada archivo

La placa **no tiene `.git`** — el repo se despliega copiando archivos sueltos por
`scp`/`wormhole`. **Ningún cambio hecho solo en el repo local existe en la placa hasta
que se copie explícitamente.** Todo lo de abajo asume que el archivo ya está
actualizado en la placa; si no se copió todavía, nada de esto aplica.

Regla general para decidir si algo necesita reinicio: **¿el archivo lo ejecuta un
proceso que corre en loop indefinidamente (`Restart=always`), o un proceso que se
lanza de cero en cada uso (timer, evento, o a mano)?** Solo el primer caso necesita
`systemctl restart`. Bash y Python no releen su propio archivo fuente mientras ya
están corriendo — un proceso de vida corta simplemente lo vuelve a leer entero la
próxima vez que arranca.

---

## No hace falta nada (se re-lee solo en la próxima ejecución)

| Archivo(s) | Quién lo dispara | Cuándo se nota el cambio |
|---|---|---|
| `starlink_remoto/aplicar_objetivo.sh`, `decidir_objetivo.sh`, `control_starlink.sh`, `mux_ps10_common.sh` | `starlink-aplicar-objetivo.service` (oneshot), disparado por `starlink-reconciliador.timer` (cada 5 min), `starlink-rele-on.timer`/`-off.timer` (08:55/17:00), o a mano (`starlink_manual.sh`) | En el próximo tick/horario, o de inmediato si se corre a mano |
| `scripts_campo_comun/config_campo.json` — **cualquier clave**, salvo la excepción de abajo | Todo lo que llama `python3 cfg.py <clave>` (proceso nuevo por invocación — `cfg.py` cachea solo dentro de un mismo proceso, no entre procesos) | En la próxima invocación de quien lea esa clave |
| `scripts_campo/capturar_stream.py`, `campo_common.py`, `scripts_campo_comun/repetir_captura.sh`, `relanzar_captura.sh`, `starlink_manual.sh`, `estado_starlink.sh`, `analisis/revisar.py` | El operador, a mano, cada vez | En la próxima corrida |
| `scripts_campo_comun/udev-automount/automount_usb.sh` | `mnt-usb-automount@.service`, disparado por udev en cada conexión/desconexión física real del USB | En el próximo evento físico real — un `umount` manual sin desconectar el USB **no** cuenta como evento nuevo (`BindsTo=dev-%i.device` no reacciona), hace falta desconectar de verdad o `systemctl restart mnt-usb-automount@sda1.service` |

---

## Hace falta reiniciar un servicio

| Archivo(s) | Servicio a reiniciar | Por qué |
|---|---|---|
| `indicador_estado/indicador_estado.sh`, `mux_ps11_common.sh` | `systemctl restart pitaya-indicador-estado.service` | Es un loop bash (`while true`) que ya está corriendo (`Type=simple`, `Restart=always`) — bash no relee el archivo desde disco mientras el loop sigue vivo |
| `panel_solar_ble/publicar_losant.py` (y los módulos que importa: `victron_scanner.py`, `puerto.py`, `config.py`, `losant_config.py`) | `systemctl restart panel-solar-informe.service` | Mismo motivo: `Type=simple`, `Restart=always`, loop de por vida (`while True` en `main()`) |
| `scripts_campo_comun/config_campo.json`, clave **`panel_solar.informe_intervalo_min`** únicamente | `systemctl restart panel-solar-informe.service` | Única excepción a la regla de "config se relee sola": `publicar_losant.py` la lee **una sola vez**, al importar el módulo (`INTERVALO_INFORME_S = cfg.obtener(...) * 60`, fuera del loop) y la cachea en una constante para toda la vida del proceso. Si se agrega una lectura nueva de `cfg.obtener()` a ese script fuera del `while True`, va a tener el mismo problema — dentro del loop, en cambio, se releería sola |

---

## Solo aplica en el próximo reboot (o forzando el servicio a mano)

| Archivo(s) | Servicio (oneshot, `RemainAfterExit=yes`) | Cómo forzarlo sin reboot |
|---|---|---|
| `indicador_estado/asegurar_mux_ps11.sh` | `pitaya-mux-ps11.service` | `systemctl restart pitaya-mux-ps11.service` |
| `starlink_remoto/asegurar_mux_ps10.sh` | `starlink-mux-ps10.service` | `systemctl restart starlink-mux-ps10.service` — con cuidado, esto reconfigura el mux de PS_MIO10 y puede togglear el relé solo (glitch conocido, ver `control_starlink.sh`) |

Estos dos scripts están pensados para correr una única vez por boot (configuran un mux
de hardware). `RemainAfterExit=yes` hace que systemd los marque `active` sin
volver a ejecutarlos — un `restart` sí los vuelve a correr, pero un reboot es la
forma normal en que esto pasa.
