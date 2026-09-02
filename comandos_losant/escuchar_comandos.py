"""
Prueba de "Send Device Command" de Losant: se conecta a un Device y
reacciona a los comandos que llegan por MQTT. El comando "capturar" lanza
simular_captura.sh (dummy) en vez de la cadena real de captura — es a
proposito, para probar el disparo/guard sin hardware ni tocar
publicar_losant.py de produccion. Cuando esto se integre de verdad, el
mismo patron de _capturar() va a llamar a
scripts_campo_comun/repetir_captura.sh en vez del dummy.

Usa un Device de prueba separado ("test_SC", ver losant_config_test.py) para
no competir por el mismo Device ID que panel_solar_ble/publicar_losant.py
usa en campo — dos conexiones MQTT con el mismo Device ID chocan (el Device
ID se usa como client id de MQTT).

Uso:
    .venv/bin/python3 escuchar_comandos.py
"""

import subprocess

from losantmqtt import Device

from losant_config_test import ACCESS_KEY, ACCESS_SECRET, DEVICE_ID

# Dummy de prueba. La cadena real (ver COMANDOS.md) es:
#   bash scripts_campo_comun/repetir_captura.sh <repeticiones> <minutos> \
#     scripts_campo_comun/relanzar_captura.sh scripts_campo/capturar_stream.py \
#     --condicion <condicion> --pad <pad> --pozo <pozo> \
#     --duracion_chunk <duracion_chunk> --canales <canales> --decimacion <decimacion>
SCRIPT_CAPTURA = "./simular_captura.sh"

# Defaults = la invocacion que mas se repite en campo (ver COMANDOS.md), para
# que un comando sin payload (o con payload parcial) siga siendo util. Todo
# override por payload es opcional.
DEFAULTS_CAPTURA = {
    "repeticiones": 20,
    "minutos": 0.5,
    "condicion": "reposo",
    "pad": "42",
    "pozo": "1",
    "duracion_chunk": 0.5,
    "canales": 2,
    "decimacion": 64,
}

# Popen de la captura en curso, o None si no hay ninguna corriendo. Un solo
# proceso a la vez: el hardware de streaming de la Red Pitaya no soporta dos
# sesiones en simultaneo.
_proceso_captura = None


def _al_conectar(dispositivo):
    print("Conectado a Losant.")


def _capturar(payload):
    global _proceso_captura
    if _proceso_captura is not None and _proceso_captura.poll() is None:
        print("Comando 'capturar' ignorado: ya hay una captura en curso.")
        return

    parametros = {**DEFAULTS_CAPTURA, **payload}
    argv = [
        SCRIPT_CAPTURA,
        str(parametros["repeticiones"]),
        str(parametros["minutos"]),
        "--condicion", str(parametros["condicion"]),
        "--pad", str(parametros["pad"]),
        "--pozo", str(parametros["pozo"]),
        "--duracion_chunk", str(parametros["duracion_chunk"]),
        "--canales", str(parametros["canales"]),
        "--decimacion", str(parametros["decimacion"]),
    ]
    print(f"Lanzando captura: {argv}")
    _proceso_captura = subprocess.Popen(argv)


def _al_recibir_comando(dispositivo, comando):
    nombre = comando["name"].lower()
    payload = comando.get("payload") or {}
    if nombre == "test":
        print(f"Comando 'test' recibido, mensaje: {payload.get('mensaje')}")
    elif nombre == "capturar":
        _capturar(payload)
    else:
        print(f"Comando recibido: nombre={nombre!r} payload={payload} time={comando.get('time')}")


def main():
    dispositivo = Device(DEVICE_ID, ACCESS_KEY, ACCESS_SECRET)
    dispositivo.add_event_observer("connect", _al_conectar)
    dispositivo.add_event_observer("reconnect", _al_conectar)
    dispositivo.add_event_observer("command", _al_recibir_comando)

    print("Conectando a Losant... Ctrl+C para salir")
    dispositivo.connect(blocking=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCortado por el usuario.")
