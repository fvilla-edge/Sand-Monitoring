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

### Workflow (lo arma el usuario; DECIDIDO 2026-10-16: dentro del "test sc")

Ramas nuevas que salen del **mismo** disparador Device: State del "test sc",
en paralelo a las de `modo_starlink`. Sumar `me_canales` y `me_in2_modo` a
"Allowed Attributes" del disparador (lección 3 de `plan_modos_starlink.md`:
el filtro no frena otros informes, pero así queda explícito).

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

- Comentario de `ventana_espera_losant_s` (`ventana_starlink.sh` y su
  descripción en `plan_modos_starlink.md`; el config es JSON, sin
  comentarios): ahora sirve también para el comando `canales`. HECHO 2026-10-16.
- `COMANDOS.md`: que en ventana se use el tag, no el comando a mano. HECHO 2026-10-16.

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

## Decidido (2026-10-16)

- Tags `canales` / `in2_modo` (esos nombres).
- Dentro del workflow "test sc" (son de prueba; no tener varios workflows).

## Bitácora de pruebas (lab `rp-f0fd8c`, `test_SC`, placa conectada)

- 2026-10-16: nodos agregados al "test sc". Ojo: hasta apretar **Save** el
  workflow no corre (primer intento sin comando por eso).
- 2026-10-16 12:46 UTC — tags `2` / `asociado`, lab dual independiente:
  **1** comando `canales` `2 asociado` (12:46:03), `ok 2 asociado` 12:46:35;
  resumen `me_in2_modo` asociado; 0 comandos más hasta 12:51 (4 resúmenes).
  Confirma que el tag texto `'2'` contra `me_canales` número `2` funciona.
- 2026-10-16 12:53 UTC — tag `canales` `1` (in2_modo asociado), lab dual
  asociado: **1** comando `canales` `1` (12:53:03), `ok 1` 12:53:34; resumen
  `me_canales` 1, `me_dec` 32, sin `me_in2_modo` ni `_in2`; 0 comandos más
  hasta 12:57. El config conserva `in2_modo` asociado (no se usa en mono).
- 2026-10-16 13:03 UTC — tags `2` / `independiente`, lab mono: **1** comando
  `canales` `2 independiente` (13:03:04), `ok 2 independiente` 13:03:36;
  `me_in2_modo` independiente, `_in2` de vuelta; 0 comandos más hasta 13:07.
  La ventana de 13:05 (abrió 1,5 min después del cambio) cerró `fin=normal`,
  subidos 4/4, 139 s.
- 2026-10-16 ~13:10 UTC — tag `canales` `Dos` (verificado por API), lab dual
  independiente, conectado, resúmenes cada minuto: 0 comandos en 3,5 min.
- 2026-10-16 ~13:17 UTC — sin tags `canales`/`in2_modo` (borrados con "−";
  Losant no acepta valor vacío), verificado por API: 0 comandos en 3,5 min.
  **Tabla del paso 2 completa: 7/7.**
- Hallazgo: en el lab la placa está conectada a Losant también **entre**
  ventanas (internet por LAN), así que el paso 3 tal cual no reproduce
  "tag cambiado con la placa desconectada".
- 2026-10-16 13:21-13:24 UTC — **paso 3 en lab, desconexión simulada**
  (`systemctl stop panel-solar-informe` fuera de ventana; Losant
  `connected: 0`): tag `in2_modo` → `asociado` con la placa desconectada,
  0 cambios en 1 min. `systemctl start` 13:23:04 → `Conectado a Losant`
  13:23:08 → **1** comando `2 asociado` 13:23:19 → `ok 2 asociado`
  13:23:50 (**42 s** desde que conecta, contra 120 s de espera de la
  ventana). Falta la ventana real con Starlink: anotada en
  `actualizar_placa_campo.md` 7.4.
- 2026-10-16 13:32 UTC — tag `in2_modo` → `independiente` por la **API REST**
  (PATCH de la lista completa de tags, mismo método que
  `comandos_losant/modo_starlink.py`): comando 13:33:03, `ok 2 independiente`
  13:33:36. Cambiar el tag por API también dispara el workflow. Lab queda
  dual independiente.
