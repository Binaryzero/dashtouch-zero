// UART loopback test -- proves whether the ESP32-S3-Zero's UART1 on GPIO43/44
// works AT ALL, with no sensor involved.
//
// Disconnect the sensor, then wire a single jumper from the pad labeled TX
// (GPIO43) to the pad labeled RX (GPIO44). Nothing else. Whatever the board
// transmits should come straight back into its own receiver.
//
// Bytes come back  -> the board's UART and both pads are fine, and the fault
//                     is downstream (sensor or sensor wiring).
// Silence          -> the fault is ON THE BOARD SIDE, and every "dead sensor"
//                     diagnosis made through this path is unsafe.
#include <Arduino.h>

static const int PIN_TX = 43;  // pad labeled "TX" (GPIO43)
static const int PIN_RX = 44;  // pad labeled "RX" (GPIO44)

HardwareSerial Port(1);

void runTest(uint32_t baud, int rxPin, int txPin, const char *label) {
  Port.end();
  delay(60);
  Port.begin(baud, SERIAL_8N1, rxPin, txPin);
  delay(200);
  while (Port.available()) Port.read();

  const uint8_t probe[] = {0xEF, 0x01, 0xA5, 0x5A, 0x00, 0xFF, 0x42, 0x7E};
  Port.write(probe, sizeof(probe));
  Port.flush();
  delay(250);

  int got = Port.available();
  Serial.printf("baud=%-7lu %s sent=%u received=%d",
                (unsigned long)baud, label, (unsigned)sizeof(probe), got);
  if (got > 0) {
    Serial.print(" bytes=");
    for (int i = 0; i < got && i < 32; i++) Serial.printf("%02x", Port.read());
  }
  Serial.println();
  Serial.flush();
}

void setup() {
  Serial.begin(115200);
  delay(2500);
}

void loop() {
  Serial.println("=== loopback test start ===");
  Serial.println("sensor disconnected: jumper the pad labeled TX (GPIO43) to the pad labeled RX (GPIO44), nothing else");
  Serial.flush();

  runTest(57600, PIN_RX, PIN_TX, "rx=44 tx=43");
  runTest(9600, PIN_RX, PIN_TX, "rx=44 tx=43");
  runTest(115200, PIN_RX, PIN_TX, "rx=44 tx=43");
  runTest(57600, PIN_TX, PIN_RX, "rx=43 tx=44");

  Serial.println("=== loopback test complete ===");
  Serial.println("received=8 on any line means the UART and both pads work");
  Serial.flush();
  delay(3000);
}
