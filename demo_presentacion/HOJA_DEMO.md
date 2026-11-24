# Hoja de pasos — demo del 10/12

Placa de **laboratorio** (`rp-f0fd8c`), sensor en **IN1**, cable directo a la
notebook, **sin internet**. La placa de campo no se toca.

---

## El día anterior (con la placa en el lab)

En la placa, como root:

```bash
bash /root/demo_presentacion/lab_demo.sh estado
```

Tiene que decir:
- `modo-evento: disabled / inactive` (modo clásico)
- `modo demo: APLICADO` (Starlink deshabilitado)
- `sysinfo.json: OK`

Si no:

```bash
bash /root/scripts_campo/cambiar_modo.sh clasico
bash /root/demo_presentacion/lab_demo.sh aplicar
```

Verificar también:
- [ ] La pantalla de inicio muestra **DFT, Oscilloscope, Arena, System, Development**.
- [ ] Arena da datos (unos 15 s después de abrirla) y el acumulado queda en 0 sin arena.
- [ ] Scope y DFT abren después de Arena (y Arena después de ellos).
- [ ] Ajustes del Oscilloscope y del DFT anotados en la sección de abajo.

Para llevar: placa + fuente, sensor con su cable a IN1, **cable de red**,
adaptador USB-Ethernet si la notebook no tiene puerto (mejor **sin hub**: el
adaptador con hub perdió el enlace el 20/11), arena para tirar.

---

## Armado en el lugar

1. Conectar el sensor a **IN1**.
2. Conectar el cable de red **entre la placa y la notebook**.
3. **Recién ahí prender la placa.** Si se prende antes de enchufar el cable,
   puede no haber enlace: apagar y volver a prender con el cable puesto.
4. Esperar ~45 s y abrir en el navegador: **`http://rp-f0fd8c.local/`**
   - Si no abre: probar la IP de la placa en ese cable
     (`192.168.137.225` con la PC de trabajo; con otra notebook, ver la
     sección *Si algo falla*).
5. Abrir **Arena**, esperar a que diga **en vivo** y tocar **Reiniciar** antes
   de empezar a mostrar.

No hace falta internet en ningún momento.

---

## Durante la demo

Se pasa de una app a otra **volviendo a la pantalla de inicio** (o abriendo
la otra). Cada cambio recarga el FPGA; el sistema ya se ocupa de parar lo que
haga falta antes.

| App | Qué muestra | Tarda en aparecer |
|---|---|---|
| **Oscilloscope** | la señal cruda del sensor | unos segundos |
| **DFT Spectrum Analyser** | el espectro (y el waterfall) | unos segundos |
| **Arena** | kurtosis, área y acumulado en vivo | **~15 s** ("iniciando la captura") |

**Ajustes preseleccionados** — *A COMPLETAR (paso 1 del plan, pendiente)*:
- Oscilloscope: canal ___, escala ___ V/div, base de tiempo ___
- DFT: span/decimación ___, ventana ___, waterfall ___

**Cómo tirar la arena en Arena** (ensayo 24/11):
- **Granos sueltos o golpes cortos**: la kurtosis pasa la línea roja y el
  acumulado sube.
- **Chorro continuo**: el área sube mucho (20–30) pero la kurtosis queda
  cerca de 3 y **el acumulado casi no se mueve**. Es lo esperado con esta
  definición (área − fondo solo cuando la kurtosis supera 3,4).

**Qué decir de cada número de Arena:**
- *Kurtosis*: cuán "picuda" es la señal en cada ventana de 50 ms. Sin arena
  es ~3; un impacto la hace subir. Línea roja = umbral 3,4 (el de campo).
- *Área*: cuánta energía tiene la señal en la ventana. Sin arena ~0,5 (el
  fondo, que se muestra debajo).
- *Acumulado*: suma del área por encima del fondo, solo en las ventanas que
  pasan el umbral de kurtosis. Arranca en 0 al abrir Arena o con **Reiniciar**.

---

## Si algo falla

- **La página no responde / la placa se colgó:** no tocar nada. El watchdog
  la reinicia sola en ~30 s y vuelve en ~45 s más, en modo clásico y lista
  para la demo. Recargar la pantalla de inicio.
- **Arena dice "sin datos" más de 45 s:** volver a la pantalla de inicio y
  abrir Arena de nuevo.
- **No hay enlace por el cable** (sin luz en el puerto): apagar la placa,
  revisar cable/adaptador, prender la placa con el cable ya puesto.
- **No abre `rp-f0fd8c.local`:** buscar la IP que la notebook le dio a la placa:
  - Linux: `ip neigh` (la placa empieza con MAC `00:26:32`).
  - Windows: *a completar cuando se sepa cuál es la notebook*.
- **Probar todo sin internet (notebook Linux):**
  `bash demo_presentacion/probar_sin_internet.sh`

---

## Después de la demo

La placa puede quedar así (modo clásico + demo). Para volver al estado de
pruebas del lab:

```bash
bash /root/demo_presentacion/lab_demo.sh revertir             # Starlink
bash /root/demo_presentacion/web/instalar_web_arena.sh quitar # app Arena (opcional)
bash /root/scripts_campo/cambiar_modo.sh evento               # solo si se va a medir
```

---

### Pendiente para completar esta hoja
- Ajustes del Oscilloscope y del DFT (paso 1 del plan).
- Notebook de la demo: SO, cómo se configura el cable compartido, y repetir
  `probar_sin_internet.sh` (o equivalente en Windows) en esa máquina.
