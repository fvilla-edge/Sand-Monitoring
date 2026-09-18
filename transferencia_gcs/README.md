# Transferencia vía Google Cloud Storage

Plan para traer archivos crudos puntuales (`.bin`) desde la placa de campo
cuando el `scp` directo a la PC es demasiado lento por el enlace Starlink.

## Por qué

La subida directa placa→PC por `scp` mide ~0.90MB/s. Subir desde la placa a
GCS (la placa inicia la conexión, en vez de que la PC la pida por SSH) mide
1.83-2.26MB/s — 2-2.5x más rápido en el tramo que realmente cuesta (el
enlace de la placa). La bajada de ahí a la PC después no depende de
Starlink para nada, es ancho de banda normal de internet.

Pensado para el caso puntual en que un archivo cruza el umbral de arena
(kurtosis, ver `analisis/revisar.py`) y hace falta el `.bin` completo, no
solo el paquete liviano.

## Recursos

- Bucket: `vista-sandvision-scout-files`
- Cuenta de servicio: `sandscout@vista-sandvision-prod.iam.gserviceaccount.com`
- Proyecto GCP: `vista-sandvision-prod`

## Credenciales

La clave de la cuenta de servicio (`credenciales.json`) **no está en este
repo** — nunca debe commitearse, está en `.gitignore` a propósito. Guardala
fuera de git (gestor de contraseñas, o donde el equipo guarde secretos) y
poné una copia local en la raíz del repo cuando haga falta usarla; si se
pierde, se puede generar una clave nueva desde la consola de GCP (IAM →
Cuentas de servicio → esa cuenta → Claves).

## Cómo se prueba hoy (sin script todavía)

1. Generar un access token de corta duración (1h) localmente, firmando un
   JWT con la clave de la cuenta de servicio (`openssl dgst -sign`) — la
   clave privada nunca sale de la máquina que la genera.
2. Copiar solo ese token (no la clave) a la placa.
3. Desde la placa, `curl` sube/baja directo contra la API de GCS
   (`storage.googleapis.com`), sin instalar nada nuevo (usa `curl`/`openssl`
   ya presentes).

## Pendiente

- Decidir si los archivos se borran de GCS después de confirmar que ya
  bajaron a la PC, o se dejan como respaldo fuera de la placa.
- Una vez decidido eso, armar un script reutilizable acá mismo con los tres
  pasos de arriba.
