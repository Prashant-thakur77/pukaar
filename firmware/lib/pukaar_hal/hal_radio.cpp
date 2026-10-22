// The E22 UART LoRa module and the serial simulator's line protocol. UNTESTED ON HARDWARE.
#include "pkr_codec.h"
#include "pkr_wire.h"
#include "pukaar_hal.h"

namespace pkr {

bool E22Radio::begin(HardwareSerial& port, int rx, int tx, int m0, int m1, uint16_t addr, uint32_t freq_hz,
                     bool configure) {
  port_ = &port;
  m0_ = m0;
  m1_ = m1;
  pinMode(m0, OUTPUT);
  pinMode(m1, OUTPUT);
  if (!configure) {  // transparent mode with the saved registers
    digitalWrite(m0, LOW);
    digitalWrite(m1, LOW);
    port.begin(9600, SERIAL_8N1, rx, tx);
    delay(30);
    return true;
  }
  // configuration mode (M0=0, M1=1) at 9600 8N1
  digitalWrite(m0, LOW);
  digitalWrite(m1, HIGH);
  delay(50);
  port.begin(9600, SERIAL_8N1, rx, tx);
  int ch = pkr_e22_channel_for(freq_hz);  // 865.4025 MHz is not on the E22 raster: CH 15 = 865.125 MHz
  if (ch < 0) ch = 15;
  uint8_t cfg[12];
  pkr_e22_config(addr, 0, (uint8_t)ch, 2 /* 2.4 kbps air rate */, 0 /* 22 dBm */, cfg);
  while (port.available()) port.read();
  port.write(cfg, sizeof cfg);
  uint8_t echo[12];
  size_t n = 0;
  uint32_t t0 = millis();
  while (n < sizeof echo && millis() - t0 < 500)
    if (port.available()) echo[n++] = (uint8_t)port.read();
  bool ok = n == sizeof echo && echo[0] == 0xC1;  // the module answers C1 + the registers
  // transparent mode (M0=0, M1=0)
  digitalWrite(m1, LOW);
  delay(50);
  return ok;
}

void E22Radio::sleep() {
  if (m0_ < 0) return;
  if (port_) port_->flush();
  digitalWrite(m0_, HIGH);
  digitalWrite(m1_, HIGH);
}

bool E22Radio::transmit(const uint8_t* buf, size_t n) {
  if (!port_) return false;
  return port_->write(buf, n) == n;
}

size_t E22Radio::receive(uint8_t* buf, size_t cap) {
  if (!port_) return 0;
  while (port_->available()) {
    int c = port_->read();
    if (c < 0) break;
    if (n_ < sizeof rx_) rx_[n_++] = (uint8_t)c;
    last_byte_ms_ = millis();
  }
  if (n_ == 0 || millis() - last_byte_ms_ < 20) return 0;
  // the last byte is the RSSI the configuration asked for (REG3 bit 7)
  size_t n = n_ > 1 ? n_ - 1 : 0;
  rssi_ = -(256 - rx_[n_ - 1]);
  if (n > cap) n = 0;
  memcpy(buf, rx_, n);
  n_ = 0;
  return n;
}

const char* SerialConsole::poll() {
  while (Serial.available()) {
    int c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      line_[n_] = 0;
      n_ = 0;
      return line_;
    }
    if (n_ < sizeof line_ - 1) line_[n_++] = (char)c;
  }
  return nullptr;
}

bool SerialRadio::transmit(const uint8_t* buf, size_t n) {
  char b64[2 * PKR_FRAME_MAX_LEN];
  pkr_b64_encode(buf, n, b64, sizeof b64);
  Serial.printf("<LORA %s\n", b64);
  return true;
}

void SerialRadio::inject(const char* b64) {
  if (count_ == 4) return;
  uint8_t slot = (uint8_t)((head_ + count_) % 4);
  int n = pkr_b64url_decode(b64, strlen(b64), q_[slot], sizeof q_[slot]);  // accepts the standard alphabet too
  if (n <= 0) return;
  qn_[slot] = (size_t)n;
  count_++;
}

size_t SerialRadio::receive(uint8_t* buf, size_t cap) {
  if (!count_) return 0;
  size_t n = qn_[head_] <= cap ? qn_[head_] : 0;
  memcpy(buf, q_[head_], n);
  head_ = (uint8_t)((head_ + 1) % 4);
  count_--;
  return n;
}

void SerialEventMirror::emit(const Event& e) {
  char buf[PKR_OUTBOX_MAX_PAYLOAD];
  if (event_to_json(e, 0, 0, buf, sizeof buf)) Serial.printf("<EVT %s\n", buf);
}

}  // namespace pkr
