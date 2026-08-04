"""
Dispositivos Victron BLE y sus claves de encriptación de Instant Readout.

Cómo conseguir la clave para un dispositivo nuevo:
  1. Abrí VictronConnect y conectate al dispositivo.
  2. Ícono de ajustes (engranaje) de ESE dispositivo -> "Product info".
  3. Sección "Instant readout via Bluetooth" -> botón "Show" junto a la clave.
  4. Copiá la clave hex (32 caracteres) y la dirección MAC del dispositivo.
"""

DEVICES = {
    # MAC del SmartSolar Charger MPPT 75/15 rev2 (HQ2248DRUEV)
    "CB:EA:5B:96:33:6C": "3a6c815c4caef6a8f86deaca119665fd",
}
