// Escaneo BLE minimo: filtra por Company ID 0x02E1 (Victron Energy) y
// vuelca la manufacturer data cruda (sin desencriptar) por Serial USB.
// Paso previo a portar el desencriptado AES-CTR de victron_scanner.py.
#include <NimBLEDevice.h>

static const uint16_t VICTRON_COMPANY_ID = 0x02E1;

class ScanCallbacks : public NimBLEScanCallbacks {
    void onResult(const NimBLEAdvertisedDevice* dev) override {
        if (!dev->haveManufacturerData()) return;

        std::string md = dev->getManufacturerData();
        if (md.size() < 2) return;

        uint16_t companyId = (uint8_t)md[0] | ((uint8_t)md[1] << 8);
        if (companyId != VICTRON_COMPANY_ID) return;

        // Igual que victron-ble/bleak: el payload util arranca con 0x10
        // (Instant Readout cifrado) despues de sacar los 2 bytes de Company
        // ID. Victron tambien manda otros anuncios (p.ej. 0x02) que no son
        // el dato cifrado que nos importa.
        if (md.size() < 3 || (uint8_t)md[2] != 0x10) return;

        Serial.printf("MAC=%s RSSI=%d LEN=%u DATA=",
                       dev->getAddress().toString().c_str(),
                       dev->getRSSI(),
                       (unsigned)md.size());
        for (size_t i = 0; i < md.size(); i++) {
            Serial.printf("%02X", (uint8_t)md[i]);
        }
        Serial.println();
    }
} scanCallbacks;

void setup() {
    Serial.begin(115200);
    delay(2000);
    Serial.println("Iniciando escaneo BLE (Victron, Company ID 0x02E1)...");

    NimBLEDevice::init("");
    NimBLEScan* scan = NimBLEDevice::getScan();
    // wantDuplicates=true: sin esto, NimBLE filtra por MAC y solo avisa la
    // PRIMERA vez que ve cada dispositivo, aunque el contenido del anuncio
    // cambie despues (que es exactamente lo que necesitamos: el SmartSolar
    // manda datos nuevos cifrados en cada anuncio, con la misma MAC).
    scan->setScanCallbacks(&scanCallbacks, true);
    scan->setActiveScan(false); // Instant Readout va en advertisements pasivos
    scan->setInterval(100);
    scan->setWindow(99);
    scan->start(0, false); // 0 = escanear indefinidamente
}

void loop() {
    delay(1000);
}
