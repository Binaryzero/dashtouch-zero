// Brightness probe: does THIS unit's aura ring have any brightness control?
//
// By the book, no. The GROW R503 manual's AuraLedConfig (0x35) carries exactly
// four bytes -- control, speed, color index, count -- and the manual never
// mentions brightness or intensity. The seven colors are the on/off
// combinations of three LED channels, so there is no level to set. Clones
// vary, though, so this sketch tries the places a vendor might have hidden one
// and lets your eyes judge.
//
// Every attempt starts from a dark ring (1s gap) and is held for 4s. Compare
// each one against the two REFERENCE states at the top of the cycle (standard
// steady white and steady blue at full). The serial log mirrors the schedule
// and records the module's ACK for each packet:
//   ack=0x00  accepted        ack=0x01  bad packet        no reply  ignored
// A visibly dimmer ring on an ACCEPTED attempt is the only result that means
// anything. A different color, or no light at all, is not brightness.
//
//   phase 1  0x35 with a FIFTH byte appended (a hidden brightness field?)
//   phase 2  0x35 steady with the SPEED byte varied (unused in steady mode per
//            the manual -- does a clone read it as brightness?)
//   phase 3  0x35 steady with COLOR INDEX values above 7 (dimmer variants?)
//   phase 4  0x3C, the ZW-style LED command some clones speak, with high bits
//            set in its color bytes
//
// Reads only: ReadProdInfo (0x3C, no parameters) and ReadSysPara (0x0F) are
// dumped once at start so the module identifies itself. Nothing here writes a
// register or touches the template database.
//
// Flashing this replaces the Dashboard Touch firmware. Get it back with
// `.venv/bin/dashtouch pairing` (fresh key + reflash; enrolled fingers stay on
// the sensor).
#include <Arduino.h>

static const int FP_RX_PIN = 44;  // ESP32-S3-Zero pad labeled "RX" (GPIO44) -- our receive, sensor yellow/TXD
static const int FP_TX_PIN = 43;  // ESP32-S3-Zero pad labeled "TX" (GPIO43) -- our transmit, sensor brown/RXD
static const uint32_t UART_BAUD = 57600;
static const uint32_t HOLD_MS = 4000;
static const uint32_t GAP_MS = 1000;

HardwareSerial Finger(1);

// Sends one command packet and collects whatever comes back within timeoutMs.
size_t sendCmd(uint8_t instr, const uint8_t *params, size_t plen,
               uint8_t *buf, size_t maxLen, uint32_t timeoutMs) {
  while (Finger.available()) Finger.read();  // drain stale bytes
  uint8_t payload[24];
  payload[0] = instr;
  if (plen) memcpy(payload + 1, params, plen);
  size_t payloadLen = plen + 1;
  uint16_t length = payloadLen + 2;
  uint32_t sum = 0x01 + (length >> 8) + (length & 0xff);
  for (size_t i = 0; i < payloadLen; i++) sum += payload[i];

  uint8_t header[] = {0xef, 0x01, 0xff, 0xff, 0xff, 0xff, 0x01,
                      (uint8_t)(length >> 8), (uint8_t)(length & 0xff)};
  Finger.write(header, sizeof(header));
  Finger.write(payload, payloadLen);
  Finger.write((uint8_t)(sum >> 8));
  Finger.write((uint8_t)(sum & 0xff));
  Finger.flush();

  size_t n = 0;
  uint32_t deadline = millis() + timeoutMs;
  while (millis() < deadline && n < maxLen) {
    if (Finger.available()) buf[n++] = (uint8_t)Finger.read();
  }
  return n;
}

void printAscii(const uint8_t *p, size_t len) {
  for (size_t i = 0; i < len; i++) {
    char c = (char)p[i];
    Serial.print((c >= 32 && c < 127) ? c : '.');
  }
}

void describeAck(const uint8_t *buf, size_t n) {
  if (n == 0) { Serial.print("no reply"); return; }
  if (n >= 10 && buf[0] == 0xef && buf[1] == 0x01) {
    Serial.printf("ack=0x%02x%s", buf[9],
                  buf[9] == 0x00 ? " (accepted)" : buf[9] == 0x01 ? " (bad packet)" : "");
    return;
  }
  Serial.printf("%u unparsed bytes:", (unsigned)n);
  for (size_t i = 0; i < n && i < 16; i++) Serial.printf(" %02x", buf[i]);
}

void ringOff() {
  uint8_t buf[32];
  const uint8_t off[4] = {4, 0, 7, 0};
  sendCmd(0x35, off, sizeof(off), buf, sizeof(buf), 300);
}

// One probe: dark gap, send, log the ACK, hold so the ring can be judged.
void attempt(const char *label, uint8_t instr, const uint8_t *params, size_t plen) {
  ringOff();
  delay(GAP_MS);
  uint8_t buf[64];
  size_t n = sendCmd(instr, params, plen, buf, sizeof(buf), 400);
  Serial.printf("%-40s 0x%02x params=", label, instr);
  for (size_t i = 0; i < plen; i++) Serial.printf("%02x", params[i]);
  Serial.print("  -> ");
  describeAck(buf, n);
  Serial.println("   [watch the ring]");
  Serial.flush();
  delay(HOLD_MS);
}

void dumpProdInfo() {
  uint8_t buf[96];
  size_t n = sendCmd(0x3c, nullptr, 0, buf, sizeof(buf), 700);
  Serial.printf("ReadProdInfo (0x3c) -> %u bytes: ", (unsigned)n);
  for (size_t i = 0; i < n; i++) Serial.printf("%02x", buf[i]);
  Serial.println();
  if (n >= 10 + 46 && buf[0] == 0xef && buf[1] == 0x01 && buf[9] == 0x00) {
    const uint8_t *p = buf + 10;  // 46-byte product record per the R503 manual
    Serial.print("  module type : "); printAscii(p, 16); Serial.println();
    Serial.print("  batch       : "); printAscii(p + 16, 4); Serial.println();
    Serial.print("  serial      : "); printAscii(p + 20, 8); Serial.println();
    Serial.printf("  hw version  : %u.%u\n", p[28], p[29]);
    Serial.print("  sensor      : "); printAscii(p + 30, 8); Serial.println();
    Serial.printf("  image %ux%u  template %u bytes  capacity %u\n",
                  (p[38] << 8) | p[39], (p[40] << 8) | p[41],
                  (p[42] << 8) | p[43], (p[44] << 8) | p[45]);
  } else {
    Serial.println("  (no product record -- this unit does not answer 0x3c as ReadProdInfo)");
  }
}

void dumpSysPara() {
  uint8_t buf[64];
  size_t n = sendCmd(0x0f, nullptr, 0, buf, sizeof(buf), 700);
  Serial.printf("ReadSysPara (0x0f) -> %u bytes: ", (unsigned)n);
  for (size_t i = 0; i < n; i++) Serial.printf("%02x", buf[i]);
  Serial.println();
  if (n >= 10 + 16 && buf[0] == 0xef && buf[1] == 0x01 && buf[9] == 0x00) {
    const uint8_t *p = buf + 10;
    Serial.printf("  status 0x%04x  sysid 0x%04x  capacity %u  security %u  pktsize %u  baud %u (x9600)\n",
                  (p[0] << 8) | p[1], (p[2] << 8) | p[3], (p[4] << 8) | p[5],
                  (p[6] << 8) | p[7], (p[12] << 8) | p[13], (p[14] << 8) | p[15]);
  }
}

void setup() {
  Serial.begin(115200);
  delay(2500);
  Finger.begin(UART_BAUD, SERIAL_8N1, FP_RX_PIN, FP_TX_PIN);
  delay(300);
  Serial.println("=== aura brightness probe ===");
  Serial.println("Judge every attempt against the two REFERENCE states. Only an ACCEPTED");
  Serial.println("attempt that is clearly dimmer (same color, less light) counts.");
  dumpProdInfo();
  dumpSysPara();
  Serial.flush();
}

static char s_label[48];

void loop() {
  Serial.println("\n=== cycle start ===");
  Serial.flush();

  const uint8_t refWhite[4] = {3, 0, 7, 0};
  const uint8_t refBlue[4] = {3, 0, 2, 0};
  attempt("REFERENCE steady WHITE (4-byte)", 0x35, refWhite, 4);
  attempt("REFERENCE steady BLUE (4-byte)", 0x35, refBlue, 4);

  Serial.println("--- phase 1: 0x35 + a 5th byte ---");
  static const uint8_t fifth[] = {0x00, 0x10, 0x40, 0xff};
  for (size_t i = 0; i < sizeof(fifth); i++) {
    uint8_t p[5] = {3, 0, 7, 0, fifth[i]};
    snprintf(s_label, sizeof(s_label), "P1 white, 5th byte 0x%02x", fifth[i]);
    attempt(s_label, 0x35, p, sizeof(p));
  }

  Serial.println("--- phase 2: 0x35 steady white, speed byte varied ---");
  static const uint8_t speeds[] = {0x00, 0x20, 0x80, 0xff};
  for (size_t i = 0; i < sizeof(speeds); i++) {
    uint8_t p[4] = {3, speeds[i], 7, 0};
    snprintf(s_label, sizeof(s_label), "P2 white, speed 0x%02x", speeds[i]);
    attempt(s_label, 0x35, p, sizeof(p));
  }

  Serial.println("--- phase 3: 0x35 steady, color index beyond 7 ---");
  static const uint8_t colors[] = {0x00, 0x08, 0x0f, 0x17, 0x27, 0x47, 0x87, 0xff};
  for (size_t i = 0; i < sizeof(colors); i++) {
    uint8_t p[4] = {3, 0, colors[i], 0};
    snprintf(s_label, sizeof(s_label), "P3 color index 0x%02x", colors[i]);
    attempt(s_label, 0x35, p, sizeof(p));
  }

  Serial.println("--- phase 4: 0x3c ZW-style LED command, high color bits ---");
  static const uint8_t zw[] = {0x07, 0x17, 0x87};
  for (size_t i = 0; i < sizeof(zw); i++) {
    uint8_t p[4] = {3, zw[i], zw[i], 0};
    snprintf(s_label, sizeof(s_label), "P4 0x3c on, color 0x%02x", zw[i]);
    attempt(s_label, 0x3c, p, sizeof(p));
  }

  ringOff();
  Serial.println("=== cycle done, 5s dark, repeating ===");
  Serial.flush();
  delay(5000);
}
