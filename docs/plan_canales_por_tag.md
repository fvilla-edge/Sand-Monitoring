# Plan: mono/dual y modo del IN2 por tag de Losant

Estado: **plan, sin código** (2026-10-15). Rama `canales-por-tag` (sale de
`integracion-campo` a24c03d).

## Problema

En modo **ventana** (`docs/plan_modos_starlink.md`) la placa está conectada a
Losant unos minutos cada 2 h. Losant **no encola** comandos: un comando
`canales` mandado con la placa desconectada se pierde sin error. Mandarlo a
mano justo durante la ventana no es práctico.

## Idea

Mismo patrón que `modo_starlink` (Fase 4 de ese plan, workflow "test sc" que
ya funciona): el **estado deseado vive en tags del Device** y un **workflow**
lo compara con lo que la placa informa que está midiendo; solo si difieren
manda el comando `canales`. Cambiar el tag con la placa apagada no se pierde:
se aplica en la próxima conexión (próxima ventana).

## Qué ya existe (verificado en el código, 2026-10-15)

- La placa informa lo que **mide**, no lo pedido
  (`scripts_campo/resumen_modo_evento.py:414-423`):
  - `me_canales` = 1 | 2 (dual con bitstream sin IN2 informa 1).
  - `me_in2_modo` = `independiente` | `asociado`, **solo** cuando `me_canales` = 2.
  - Sin `me_canales` si modo-evento no está activo o está reiniciando
    (el supervisor borra `/run/modo-evento/medicion` al parar,
    `supervisor_eventos.sh:112`).
- `publicar_losant.py` manda el último resumen (evento.json, se pisa cada
  minuto) apenas conecta y después cada minuto: el workflow tiene el dato a
  los pocos segundos de conectar.
- Comando `canales` `{"canales": 1}` / `{"canales": 2, "in2": "independiente"|"asociado"}`
  (`publicar_losant.py:_cambiar_canales` → `scripts_campo/cambiar_canales.sh`).
- La ventana espera `starlink.ventana_espera_losant_s` = 120 s desde que hay
  internet antes de apagar (`ventana_starlink.sh`). Un cambio de canales tarda
  ~30 s (28-29 s medidos en `plan_cambio_canales_remoto.md`).
- El cambio queda en `config_campo.json`: sobrevive reinicios y cortes.

## Verificación de `cambiar_canales.sh` frente a comandos repetidos

El workflow puede mandar el mismo comando más de una vez (un resumen por
minuto). Leído del código:

| Situación | Qué hace `cambiar_canales.sh` | ¿Problema? |
|---|---|---|
| Pedido igual a lo que ya mide (modo-evento activo y `/run/modo-evento/medicion` coincide) | `ok ... (ya estaba)`, **no reinicia** | No |
| Llega otro comando mientras un cambio está en curso | `systemd-run --unit=cambiar-canales` falla (unidad ya existe) → "rechazado: ya hay un cambio en curso"; **no pisa** `cambio_canales_estado` | No |
| Durante el reinicio de modo-evento | No hay `me_canales` en el resumen → el workflow no dispara | No |
| Entre escribir el config y el `systemctl restart` (segundos) | Puede salir un resumen con el valor viejo → otro comando → rechazado (cambio en curso) | No |
| Dual con bitstream **sin** IN2 | La placa informa `me_canales` = 1 aunque pidió 2 → el workflow manda `canales 2` cada minuto → `ya estaba` cada vez | Ruido, no daño. En campo el paquete trae el bitstream IN2 |
| Cambio que falla (4 min + vuelta ≈ 8,5 min con el lock del relé) y cae en el cierre de la ventana | `control_starlink.sh off` espera el lock solo 180 s y se rinde: Starlink queda prendida hasta el reconciliador (~10 min más) | **Ya aceptado** por el usuario 2026-10-07 (`plan_cambio_canales_remoto.md`) |

Conclusión: **es idempotente**, no hace falta código en la placa para esto.

## Diseño propuesto

### Tags del Device (los crea el usuario)

- `canales`: `1` | `2`
- `in2_modo`: `independiente` | `asociado` (solo cuenta si `canales` = `2`)

Sin tag o con un valor mal escrito: el workflow no hace nada (igual que
`modo_starlink`). O sea: sin tags la placa sigue con lo que tenga su config.

### Workflow (lo arma el usuario; se puede sumar al "test sc" o uno aparte)

```
Device: State ──> Cond A ──true──> Cond B (quiere mono) ──true──> Command canales {"canales": 1}
                    │ false           │ false
                  (nada)            Cond C (quiere dual) ──true──> Command canales {"canales": 2, "in2": "<tag>"}
                                      │ false
                                    (nada)
```

- **Cond A** (el informe trae lo que mide):
  `{{data.me_canales}} == 1 || {{data.me_canales}} == 2`
- **Cond B** (tag pide mono y mide dual):
  `{{deviceTags.canales.[0]}} == '1' && {{data.me_canales}} == 2`
- **Cond C** (tag pide dual y no coincide):
  `{{deviceTags.canales.[0]}} == '2' && ({{deviceTags.in2_modo.[0]}} == 'independiente' || {{deviceTags.in2_modo.[0]}} == 'asociado') && ({{data.me_canales}} == 1 || {{deviceTags.in2_modo.[0]}} != {{data.me_in2_modo}})`
- **Command B:** nombre `canales`, payload `{"canales": 1}`
- **Command C:** nombre `canales`, payload `{"canales": 2, "in2": "{{deviceTags.in2_modo.[0]}}"}`

A probar (no está verificado): el tag es texto (`'1'`) y `me_canales` es
número (`1`); con lo aprendido en `modo_starlink` (plantillas insertadas como
JSON) debería andar así, pero es lo primero que hay que confirmar. Si
`me_in2_modo` no viene (mono), en Cond C manda el `me_canales == 1`.

### Placa

**Nada que codear** según lo verificado arriba. Solo documentación:

- Comentario de `ventana_espera_losant_s` (config y `ventana_starlink.sh`):
  ahora sirve también para el comando `canales`.
- `COMANDOS.md`: que en ventana se use el tag, no el comando a mano.

## Pasos

0. **Usuario:** crear tags `canales` e `in2_modo` en `test_SC` con los valores
   que tiene hoy el lab (dual / independiente → no debe mandar nada).
1. **Usuario:** armar el workflow (expresiones de arriba). Yo miro el
   journal del lab (`journalctl -u panel-solar-informe`) y `cambiar_canales.log`.
2. **Pruebas en lab con la placa conectada** (cada una: ¿llega el comando?,
   ¿cuántas veces?, `me_cambio`):

   | Tags | Lab mide | Esperado |
   |---|---|---|
   | 2 / independiente | dual independiente | nada |
   | 2 / asociado | dual independiente | 1 comando `2 asociado`, después nada |
   | 1 / (cualquiera) | dual | 1 comando `1`, después nada |
   | 1 | mono | nada |
   | 2 / independiente | mono | 1 comando `2 independiente` |
   | `Dos` (mal escrito) | lo que sea | nada |
   | sin tags | lo que sea | nada |

3. **Prueba en ventana real:** cambiar el tag con la placa apagada (entre
   ventanas) y ver en la ventana siguiente: cambio aplicado, `fin=normal` en
   `ventanas_starlink.log`, rele apagado al cerrar.
4. Documentación (los 2 puntos de "Placa") y anotar en
   `scripts_campo/plan_campo/actualizar_placa_campo.md` (tags + workflow a
   crear en el Device de campo).

## Para decidir el usuario

- Tags `canales` / `in2_modo` (nombres) — ¿van esos?
- ¿Workflow aparte o dentro del "test sc"? (Aparte es más fácil de probar y
  de apagar sin tocar `modo_starlink`.)
