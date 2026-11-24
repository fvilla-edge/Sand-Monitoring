// arena.js — panel "Arena" de la demo (rama demo-presentacion, no va a campo).
//
// Lee cada 250 ms ventanas.json (lo escribe capturar_eventos_demo --en-vivo cada
// ~200 ms en /run/arena; nginx lo sirve con un alias, ver arena/nginx.conf):
//   {"t_ms": <hora de la placa al escribir>, "dec": 32, "fs_hz": ...,
//    "ventanas": [[wc, t_ms, area, kurt, area2, kurt2], ...]}   (ultimos 30 s)
// Sin librerias externas: la demo va por cable directo, sin internet.
// El acumulado (M2, ver sumarNuevas) vive solo en esta pestaña: arranca en 0 al abrir/recargar.
'use strict';

const URL_DATOS = 'ventanas.json';
const PERIODO_MS = 250;
const UMBRAL_KURT = 3.4;       // el mismo de captura en campo (05/10)
const VENTANA_GRAF_S = 30;     // eje x de los tres graficos
const SIN_DATOS_MS = 2000;     // si el archivo no cambia en este tiempo: captura parada
// Backends a descargar de nginx antes de cargar nuestro bitstream: Scope, DFT,
// la pantalla de inicio (main_menu) y los que el listado de apps de la pantalla
// de inicio deja cargados sin abrirlos (la_pro, streaming_manager; visto 24/11).
const APPS_RP = ['scopegenpro', 'spectrumpro', 'main_menu', 'la_pro', 'streaming_manager'];
const ARRANQUE_MS = 45000;     // hasta aca, "sin datos" se muestra como "iniciando"

const $ = (id) => document.getElementById(id);
const graf = { kurt: $('g-kurt'), area: $('g-area'), acum: $('g-acum') };

let ultimoWc = null;           // ultima ventana ya sumada al acumulado
let acumulado = 0;
let fondo = null;              // area de fondo (ruido), ver actualizarFondo
let serieAcum = [];            // [t_ms, acumulado] por ventana
let ultimoTms = null;          // t_ms del archivo la ultima vez que cambio
let vistoCambio = 0;           // performance.now() de ese cambio
let ventanas = [];
let pidiendo = false;
let enCampo = false;           // /arena_iniciar respondio CAMPO: no se lee nada
let arrancando = null;         // performance.now() del pedido de arranque; null = ya hay datos

$('v-umbral').textContent = UMBRAL_KURT.toString().replace('.', ',');

function fmt(v) {
  if (v == null || !isFinite(v)) return '–';
  const a = Math.abs(v);
  const d = a >= 100 ? 0 : a >= 10 ? 1 : 2;
  return v.toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d });
}

function horaLocal(d) {
  return d.toLocaleTimeString('es-AR', { hour12: false });
}

function reiniciar() {
  acumulado = 0;
  serieAcum = [];
  if (ventanas.length) ultimoWc = ventanas[ventanas.length - 1][0];
  $('v-desde').textContent = 'desde ' + horaLocal(new Date());
  pintar();
}
$('reiniciar').addEventListener('click', reiniciar);
$('v-desde').textContent = 'desde ' + horaLocal(new Date());

// Fondo = percentil 20 del area de los ultimos 30 s (como el estudio arena vs
// kg), SIN mirar la kurtosis: con arena en chorro la kurtosis queda ~3 y esas
// ventanas no son fondo (ensayo 24/11: con el criterio de kurtosis llego a 4,1
// contra 0,52 real). Solo se acepta un valor nuevo si es menor que 2x el actual:
// un chorro largo no lo arrastra hacia arriba, y si se abrio la pagina en medio
// de un chorro puede bajar despues.
function actualizarFondo(vs) {
  const a = vs.filter((v) => Number.isFinite(v[2])).map((v) => v[2]).sort((x, y) => x - y);
  if (!a.length) return;
  const p20 = a[Math.floor(0.2 * (a.length - 1))];
  if (fondo === null || p20 < 2 * fondo) fondo = p20;
}

// Acumulado = M2 del estudio arena vs kg (docs/estudio_arena_vs_kg.md):
// suma de (area - fondo) solo en las ventanas con kurtosis > umbral; el ruido
// no suma. Negativos a 0 para que nunca baje. Cada ventana se cuenta una sola
// vez (por numero de ventana, no por tiempo) aunque aparezca en varias lecturas.
function sumarNuevas(vs) {
  if (!vs.length) return;
  actualizarFondo(vs);
  const ultima = vs[vs.length - 1][0];
  if (ultimoWc === null) { ultimoWc = ultima; return; }        // arranca desde ahora
  const avance = (ultima - ultimoWc) >>> 0;
  if (avance === 0) return;
  if (avance > 0x7fffffff) { ultimoWc = ultima; return; }      // la captura se reinicio
  for (const v of vs) {
    const d = (v[0] - ultimoWc) >>> 0;
    if (d === 0 || d > 0x7fffffff) continue;
    if (fondo !== null && Number.isFinite(v[2]) && Number.isFinite(v[3]) && v[3] > UMBRAL_KURT)
      acumulado += Math.max(0, v[2] - fondo);
    serieAcum.push([v[1], acumulado]);
  }
  ultimoWc = ultima;
  const corte = vs[vs.length - 1][1] - VENTANA_GRAF_S * 1000;
  while (serieAcum.length && serieAcum[0][0] < corte) serieAcum.shift();
}

function ponerEstado(clase, texto) {
  const e = $('estado');
  e.className = clase;
  e.textContent = texto;
}

function sinDatos(texto) {
  if (arrancando !== null && performance.now() - arrancando < ARRANQUE_MS)
    ponerEstado('', 'iniciando la captura (~15 s)…');
  else
    ponerEstado('parado', texto);
  $('atraso').textContent = '';
}

// Al abrir la pagina: descargar los backends de Oscilloscope/DFT (leen el FPGA
// y quedan cargados en nginx aunque se cierre su pestaña) y recien despues
// arrancar la captura, que carga nuestro bitstream. Si ya corre, no hace nada.
async function iniciar() {
  arrancando = performance.now();
  ponerEstado('', 'iniciando la captura (~15 s)…');
  for (const a of APPS_RP) {
    try { await fetch('/bazaar?stop=' + a, { cache: 'no-store' }); } catch (e) { /* no estaba cargado */ }
  }
  try {
    const r = await fetch('/arena_iniciar', { cache: 'no-store' });
    if ((await r.text()).trim() === 'CAMPO') {
      // equipo en modo campo: el modo evento esta midiendo y no se lo interrumpe
      enCampo = true;
      ponerEstado('parado', 'equipo en modo campo: Arena no disponible');
      return;
    }
  } catch (e) { /* se ve como "sin datos" */ }
  leer();
  setInterval(leer, PERIODO_MS);
}

async function leer() {
  if (pidiendo) return;
  pidiendo = true;
  try {
    const r = await fetch(URL_DATOS, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const j = await r.json();
    const ahora = performance.now();
    // vivo = el archivo cambio con la pagina abierta (la 1ra lectura puede ser
    // el archivo viejo de una captura anterior: no cuenta como cambio)
    if (j.t_ms !== ultimoTms) { vistoCambio = ultimoTms === null ? -Infinity : ahora; ultimoTms = j.t_ms; }
    ventanas = Array.isArray(j.ventanas) ? j.ventanas : [];
    if (ahora - vistoCambio > SIN_DATOS_MS) {
      sinDatos('sin datos nuevos (¿captura parada?)');
    } else {
      arrancando = null;
      sumarNuevas(ventanas);
      ponerEstado('vivo', 'en vivo');
      const u = ventanas[ventanas.length - 1];
      $('atraso').textContent = u ? 'atraso ' + Math.max(0, j.t_ms - u[1]) + ' ms' : '';
    }
  } catch (e) {
    sinDatos('sin datos: la captura está parada');
  } finally {
    pidiendo = false;
  }
  pintar();
}

// ---------- graficos (canvas, sin librerias) ----------

function pasoLindo(rango, n) {
  const crudo = rango / n;
  const p = Math.pow(10, Math.floor(Math.log10(crudo)));
  const m = crudo / p;
  return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
}

// puntos: [[t_ms, valor], ...]; tFin = t_ms del borde derecho
function dibujar(canvas, puntos, tFin, color, opc) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
  }
  const c = canvas.getContext('2d');
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, W, H);
  const css = getComputedStyle(document.documentElement);
  const cGrilla = css.getPropertyValue('--grilla'), cTenue = css.getPropertyValue('--tenue');
  const izq = 54, der = 10, arr = 8, abj = 20;
  const ancho = W - izq - der, alto = H - arr - abj;

  const vals = puntos.map((p) => p[1]).filter((v) => v != null && isFinite(v));
  let yMin = vals.length ? Math.min(...vals) : 0, yMax = vals.length ? Math.max(...vals) : 1;
  if (opc.yMinMax != null) yMin = Math.min(yMin, opc.yMinMax);
  if (opc.yMaxMin != null) yMax = Math.max(yMax, opc.yMaxMin);
  if (opc.desdeCero) yMin = Math.min(0, yMin);
  if (yMax - yMin < 1e-9) yMax = yMin + 1;
  const marg = (yMax - yMin) * 0.06;
  yMax += marg; if (!opc.desdeCero) yMin -= marg;
  const paso = pasoLindo(yMax - yMin, 4);
  yMin = Math.floor(yMin / paso) * paso; yMax = Math.ceil(yMax / paso) * paso;

  const tIni = tFin - VENTANA_GRAF_S * 1000;
  const X = (t) => izq + ((t - tIni) / (tFin - tIni)) * ancho;
  const Y = (v) => arr + (1 - (v - yMin) / (yMax - yMin)) * alto;

  c.font = '11px system-ui, sans-serif';
  c.lineWidth = 1;
  c.strokeStyle = cGrilla; c.fillStyle = cTenue;
  c.textAlign = 'right'; c.textBaseline = 'middle';
  const dec = paso >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(paso)));
  for (let v = yMin; v <= yMax + paso / 2; v += paso) {
    const y = Math.round(Y(v)) + 0.5;
    c.beginPath(); c.moveTo(izq, y); c.lineTo(W - der, y); c.stroke();
    c.fillText(v.toLocaleString('es-AR', { minimumFractionDigits: dec, maximumFractionDigits: dec }), izq - 6, y);
  }
  c.textAlign = 'center'; c.textBaseline = 'top';
  for (let s = -VENTANA_GRAF_S; s <= 0; s += 5) {
    const x = Math.round(X(tFin + s * 1000)) + 0.5;
    c.beginPath(); c.moveTo(x, arr); c.lineTo(x, arr + alto); c.stroke();
    c.fillText(s === 0 ? 'ahora' : s + ' s', Math.min(Math.max(x, izq + 10), W - der - 14), arr + alto + 4);
  }

  if (opc.umbral != null && opc.umbral >= yMin && opc.umbral <= yMax) {
    c.save();
    c.strokeStyle = css.getPropertyValue('--umbral'); c.setLineDash([6, 4]); c.lineWidth = 1.5;
    const y = Y(opc.umbral);
    c.beginPath(); c.moveTo(izq, y); c.lineTo(W - der, y); c.stroke();
    c.restore();
  }

  c.save();
  c.beginPath(); c.rect(izq, arr, ancho, alto); c.clip();
  c.strokeStyle = color; c.lineWidth = 1.6; c.lineJoin = 'round';
  c.beginPath();
  let abierto = false;
  for (const [t, v] of puntos) {
    if (v == null || !isFinite(v)) { abierto = false; continue; }
    if (abierto) c.lineTo(X(t), Y(v)); else { c.moveTo(X(t), Y(v)); abierto = true; }
  }
  c.stroke();
  c.restore();
}

function pintar() {
  const css = getComputedStyle(document.documentElement);
  const u = ventanas[ventanas.length - 1];
  $('v-kurt').textContent = u ? fmt(u[3]) : '–';
  $('v-area').textContent = u ? fmt(u[2]) : '–';
  $('v-acum').textContent = fmt(acumulado);
  $('v-fondo').textContent = fondo === null ? '–' : fmt(fondo);
  const tFin = u ? u[1] : Date.now();
  dibujar(graf.kurt, ventanas.map((v) => [v[1], v[3]]), tFin, css.getPropertyValue('--kurt'),
          { umbral: UMBRAL_KURT, yMinMax: 2.5, yMaxMin: UMBRAL_KURT + 1 });
  dibujar(graf.area, ventanas.map((v) => [v[1], v[2]]), tFin, css.getPropertyValue('--area'),
          { desdeCero: true });
  dibujar(graf.acum, serieAcum, tFin, css.getPropertyValue('--acum'), { desdeCero: true });
}

window.addEventListener('resize', pintar);
iniciar();
