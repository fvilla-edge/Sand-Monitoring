# Procedimiento: placa del lab (`rp-f0fd8c`) → `SC2`, lista para viajar en demo

Plan general y bitácora: `docs/plan_demo_a_campo.md`. Este archivo es la lista
del día del cambio. Se hace **en la empresa, por LAN, al final** (decisión
24/11), cuando ya está el hardware. Termina con la placa en **demo** y con
identidad de **campo** (`SC2`).

Base: comparación del 24/11 entre el lab y SC1 (inventario del lab
`datos_campo/inventarios/inventario_rp-f0fd8c_campo_20261124.txt`, inventario
de SC1 del 20/10 y tag `campo-2026-10-21b`).

`IP` = IP de la placa en la LAN (24/11: `192.168.0.134`). Todo por SSH con la
clave de la PC.

---

## 0. Antes de empezar (todo tiene que estar en ✔)

- [ ] Hardware igual que PAD-118 soldado y cableado: RTC DS3231, relé con su
      capacitor, ESP32 por USB, pendrive de campo, sensores IN1/IN2.
- [ ] Losant: Device `SC2` con 73 atributos (SC1 + `me_equipo`,
      `me_equipo_cambio`), tags `canales=1`, `in2_modo=independiente`,
      `modo_starlink=permanente`, workflow de SC2 creado. **Hecho 24/11.**
- [ ] Credenciales de SC2 en la PC: `~/credenciales_losant/sc2.txt` (600,
      **nunca en el repo**).
- [ ] La placa arranca en **campo** (`bash /root/demo_presentacion/cambiar_equipo.sh estado`
      → `equipo: campo`). Todo lo de abajo se hace en campo; la demo va al final.
- Datos de prueba del lab: **se vacían todos** (decisión 24/11: no sirven y
  no se sube basura a la nube). Ver paso 4. `subir-csv-gcs` sube las horas de
  los últimos 30 días que no estén en su registro: con datos viejos en el
  pendrive o la SD los subiría a la carpeta de SC2.

## 1. Respaldo e inventario del "antes"

```bash
ssh root@IP 'bash -s' < scripts_campo_comun/inventario_placa.sh > datos_campo/inventarios/inventario_rp-f0fd8c_antes_sc2_$(date +%Y%m%d).txt
ssh root@IP 'tar czf - /root/scripts_campo_comun/config_campo.json /root/panel_solar_ble/losant_config.py /etc/systemd/network /etc/ssh/sshd_config' > ~/respaldo_rp-f0fd8c_antes_sc2_$(date +%Y%m%d).tgz
chmod 600 ~/respaldo_rp-f0fd8c_antes_sc2_*.tgz   # tiene la credencial de test_SC
```

## 2. Identidad de Losant: `test_SC` → `SC2`

1. Generar `losant_config.py` desde `~/credenciales_losant/sc2.txt` (mismo
   formato que el actual: `DEVICE_ID`, `ACCESS_KEY`, `ACCESS_SECRET`) en el
   scratchpad, con permisos 600. No imprimir el secreto.
2. Copiar a `/root/panel_solar_ble/losant_config.py`, `sync`, borrar la copia
   local y reiniciar `panel-solar-informe`.
3. Verificar: el journal dice "Conectado a Losant" y en Losant `SC2` figura
   conectado y `test_SC` desconectado. Con la placa en campo llegan los `me_*`
   a SC2 (incluidos `me_equipo=campo`).

## 3. Configuración de campo (`config_campo.json` de la placa)

Con respaldo (`cp config_campo.json config_campo.json.antes_sc2`) y `sync`:

| Clave | Lab hoy | SC2 |
|---|---|---|
| `gcs.prefijo` | `pruebas/csv_ventanas` | `campo/csv_ventanas` (igual que SC1; separa la subcarpeta `rp-f0fd8c`) |
| `url_aviso` | `http://127.0.0.1:9/aviso-ensayo-placa-pruebas` | la de SC1 (`https://sample-download-trigger-…southamerica-west1.run.app`, inventario SC1 línea ~338) |
| `modo_evento.canales` | 1 | 1 (= tag `canales=1`) |

SandVision lista `campo/` y `pruebas/` por subcarpeta de equipo (hostname),
así que los CSV de SC2 aparecen solos. Aparte (cuando esté en campo): sumar el
Device SC2 a los equipos que el servidor de SandVision lee de Losant
(Energía/Estado) y cargar su ubicación.

Después: `systemctl restart modo-evento` **no**: aplicar con un reinicio de la
placa (método de la demo: dejar config y reiniciar; nunca leer el PL mientras
recarga).

## 4. GCS

1. Vaciar los datos de prueba (con `modo-evento` parado y el timer de GCS
   todavía deshabilitado): CSV/eventos del pendrive (`/mnt/usb`, salvo lo que
   sea del sistema de montaje), `/root/eventos_sd/` y los registros de
   subidos (`gcs.registro_sd` = `/root/gcs_subidos.txt`,
   `gcs.subidos_file` = `/mnt/usb/gcs_subidos.txt`). Listar antes de borrar
   y confirmar con el usuario. Después `sync` y reinicio.
2. `systemctl enable --now subir-csv-gcs.timer` (en el lab está deshabilitado;
   en SC1 habilitado). No está en la lista de unidades de `cambiar_equipo.sh`,
   así que queda habilitado también en demo (sin datos nuevos no sube nada).
3. Verificar la primera subida en el bucket, bajo `campo/csv_ventanas/rp-f0fd8c/`
   (y que aparezca en SandVision como un equipo más).

## 5. Hardware (secciones de `scripts_campo/plan_campo/setup_placa.md`)

- [ ] RTC DS3231: sección 5b (`rtc-restaurar.service`; en el lab no existe).
- [ ] Relé / Starlink: sección 5 (ya instalado en el lab; verificar cableado y
      un ciclo on/off con el relé real).
- [ ] ESP32 del panel solar: sección 6 (el servicio ya está; verificar que
      lea `/dev/ttyACM0`).
- [ ] Pendrive de campo: sección 3.

## 6. Red

`/etc/systemd/network/wired.network` difiere del de SC1. El del lab tiene
DHCP + `IPForward`/`IPMasquerade` (comparte internet por la LAN). **A
definir** contra el de SC1 (contenido no está en el inventario, solo el
sha256; confirmarlo cuando SC1 vuelva a estar conectada o en
`setup_placa.md`). En la demo la placa va en la red del cliente por DHCP.

## 7. Limpieza de `/root` (con respaldo a la PC antes)

Restos de pruebas detectados el 24/11: `config_campo.json.bak*`,
`capturar_eventos.bak_pre_csv_cola`, `*.antes_equipo`, `prueba_eth0/`,
`tmp_compilar_csv/`, `aplicar_mods_web.py`, la copia vieja de
`scripts_campo/c/capturar_eventos.cpp` (reemplazar por la del tag). **No**
borrar `demo_presentacion/` (hace falta para la demo y el cambio a campo).

## 8. Prueba de los workflows de SC2 (todavía en campo)

1. En Losant cambiar el tag `modo_starlink` de SC2 → `ventana` y verificar que
   llegue el comando `modo` a la placa (`journalctl -u panel-solar-informe`) y
   que `sl_modo` se actualice. Volver a `permanente`.
2. Lo mismo con `canales` (1 → 2 → 1) si se quiere probar el cambio de canales.

## 9. Hardening SSH (sección 4b de `setup_placa.md`)

`PasswordAuthentication no` + `fail2ban` con `banaction=iptables` y la
verificación de que banea. **Antes de cerrar la sesión**, abrir otra y
confirmar que entra con la clave de la PC.

## 10. Ensayo final con SC2 y dejarla en demo

1. `bash /root/demo_presentacion/cambiar_equipo.sh demo` por SSH → `ok demo`.
   (Guarda la lista de Starlink habilitado para la vuelta a campo.)
2. Losant → `SC2` → *Send Device Command* `equipo` `{"modo":"campo"}` →
   `ok campo` en `me_equipo_cambio` de **SC2**, captura al 100 %, subida a GCS.
3. Otra vez `cambiar_equipo.sh demo` por SSH → `ok demo`. **Así viaja.**
4. Abrir la web (Scope, DFT, Arena) y repasar `demo_presentacion/HOJA_DEMO.md`.
5. Inventario del "después" y diferencia contra SC1: solo deben quedar
   credenciales, hostname, `gcs.prefijo`, red y los archivos de la demo.

## 11. En el sur

- Demo con el cliente (`HOJA_DEMO.md`).
- Después de la demo, cuando la placa quede instalada: comando `equipo`
  `{"modo":"campo"}` desde Losant (SC2). Seguir `me_equipo_cambio` hasta
  `ok campo`. Si da `error: no anduvo campo, volvio a demo`, la placa sigue
  recibiendo comandos: revisar y reintentar.
- Primeros días: lo mismo que la sección 7.5 de
  `scripts_campo/plan_campo/actualizar_placa_campo.md`.
