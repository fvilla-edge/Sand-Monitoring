# Plan de acceso remoto vía Starlink con relé

## Contexto

Fase 1: equipo en campo con el usuario presente, haciendo pruebas y validando datos.
Fase 2: equipo queda solo en el sitio. Acceso por SSH a la Red Pitaya vía Starlink.
Para ahorrar energía, el kit Starlink (dish + router) se energiza solo durante una
ventana horaria fija, controlada por un relé.

## Arquitectura

| Componente | Rol | Alimentación |
|---|---|---|
| Red Pitaya (la misma que corre `scripts_campo/`) | Corre el cron, controla el relé por GPIO, captura datos | Siempre encendida, fuente propia del sitio |
| Relé | Corta/habilita alimentación del kit Starlink | Controlado por GPIO desde la Red Pitaya |
| Starlink (dish + router) | Da conectividad para el SSH entrante | Detrás del relé — apagado por default |

Asunción a reconfirmar en sitio: el plan de Starlink da IP pública/gestionable, así que
el SSH entrante llega directo sin túnel intermedio (Tailscale, WireGuard, etc.). Si en
la práctica resulta ser CGNAT, este plan no alcanza y hace falta agregar esa capa.

## Horario

- **ON:** 08:55 (5 min de margen antes de las 09:00 para que el dish termine de
  bootear y enganchar satélite antes de que el usuario intente conectarse)
- **OFF:** 17:00

Ambos horarios como variables al principio del script de control, no hardcodeados en
el medio de la lógica — se tienen que poder cambiar sin tocar el resto del código.

El OFF es idempotente: si el relé ya estaba apagado (porque el usuario lo cortó antes,
o porque nunca se activó ese día), no hace nada.

## Sincronización de reloj (sin RTC)

La placa no tiene RTC ni cliente NTP instalado hoy. Sin red la mayor parte del día, el
reloj del sistema puede driftear entre ventanas.

Plan:
1. Instalar `chrony`.
2. Configurarlo en modo sync puntual, no polling continuo (no tiene sentido con red
   intermitente).
3. Dentro del script de ON, después de habilitar el relé y esperar a que la interfaz
   de red tenga link/IP, disparar una sincronización one-shot (`chronyd -q` o
   equivalente).

Esto corrige el drift acumulado cada ventana, pero el propio disparo del cron a las
08:55 puede llegar corrido si el drift diario es grande — a confirmar en la práctica
cuánto driftea esta placa en 24 hs sin corrección.

## Riesgos identificados

| Riesgo | Mitigación |
|---|---|
| Starlink no queda usable al instante (boot + actualización de firmware) | Margen de 5 min antes de la hora "oficial"; el firmware update puede igual comerse parte de la ventana, sin mitigación total posible |
| Red Pitaya se cuelga/reinicia a mitad de ventana y el relé queda en un estado no controlado | Definir y probar el estado *fail-safe* del relé (recomendado: sin señal de control = Starlink apagado, para no drenar batería del sitio si algo falla) |
| Drift de reloj sin NTP entre ventanas | Sync forzado al levantar la red (ver arriba); medir drift real en campo |
| Asunción de IP pública resulta incorrecta (CGNAT) | Reconfirmar con Starlink activo en sitio antes de dar el diseño por cerrado |

## Pendientes / decisiones abiertas

- Modelo de relé y cableado físico: qué pin del conector de expansión de la Red
  Pitaya se usa, aislación, etc. — no definido todavía.
- Confirmar en banco/campo que 5 min de margen alcanzan para que el dish esté
  realmente utilizable.
- Confirmar el comportamiento fail-safe deseado del relé.
- Decidir si el script vive en `scripts_campo_comun/` (junto a `automount_usb.sh` y
  `relanzar_captura.sh`) dado que es infraestructura compartida, no captura en sí.

## Plan de implementación (borrador)

1. Instalar y configurar `chrony` en la Red Pitaya (sync one-shot, sin polling
   continuo).
2. Escribir script de control del relé con funciones ON/OFF sobre GPIO, horarios
   como variables editables al inicio.
3. Dos entradas de cron: 08:55 (ON) y 17:00 (OFF), llamando al script.
4. Dentro de ON: activar relé → esperar link de red → disparar sync NTP one-shot.
5. Probar en banco el ciclo completo (ON, verificar conectividad, sync, OFF) antes
   de llevarlo a campo.
6. Probar el caso de falla: cortar alimentación a la Red Pitaya a mitad de ventana
   y verificar en qué estado queda el relé al recuperarse.
