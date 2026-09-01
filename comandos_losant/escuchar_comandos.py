"""
Prueba minima de "Send Device Command" de Losant: se conecta a un Device y
muestra por pantalla cada comando que llega por MQTT, sin ejecutar ninguna
accion todavia. Sirve para entender el mecanismo antes de conectarlo de
verdad a scripts_campo/capturar_stream.py.

Usa un Device de prueba separado ("test_SC", ver losant_config_test.py) para
no competir por el mismo Device ID que panel_solar_ble/publicar_losant.py
usa en campo — dos conexiones MQTT con el mismo Device ID chocan (el Device
ID se usa como client id de MQTT).

Uso:
    .venv/bin/python3 escuchar_comandos.py
"""

from losantmqtt import Device

from losant_config_test import ACCESS_KEY, ACCESS_SECRET, DEVICE_ID


def _al_conectar(dispositivo):
    print("Conectado a Losant.")


def _al_recibir_comando(dispositivo, mensaje):
    print(f"Comando recibido: nombre={mensaje['name']!r} payload={mensaje.get('payload')} "
          f"time={mensaje.get('time')}")


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
