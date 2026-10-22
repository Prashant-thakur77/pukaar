#include "pkr_wire.h"

#include <string.h>

uint16_t pkr_modbus_crc(const uint8_t *b, size_t n) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < n; i++) {
    crc ^= b[i];
    for (int k = 0; k < 8; k++) crc = (crc & 1) ? (uint16_t)((crc >> 1) ^ 0xA001) : (uint16_t)(crc >> 1);
  }
  return crc;
}

void pkr_modbus_request(uint8_t addr, uint8_t fc, uint16_t reg, uint16_t value, uint8_t out[8]) {
  out[0] = addr;
  out[1] = fc;
  out[2] = (uint8_t)(reg >> 8);
  out[3] = (uint8_t)reg;
  out[4] = (uint8_t)(value >> 8);
  out[5] = (uint8_t)value;
  uint16_t c = pkr_modbus_crc(out, 6);
  out[6] = (uint8_t)c;
  out[7] = (uint8_t)(c >> 8);
}

static int crc_ok(const uint8_t *b, size_t n) {
  uint16_t c = pkr_modbus_crc(b, n - 2);
  return b[n - 2] == (uint8_t)c && b[n - 1] == (uint8_t)(c >> 8);
}

static int exception_reply(const uint8_t *b, size_t n, uint8_t addr, uint8_t fc, uint8_t *exception) {
  if (n >= 5 && b[0] == addr && b[1] == (uint8_t)(fc | 0x80)) {
    if (!crc_ok(b, 5)) return PKR_MB_E_CRC;
    if (exception) *exception = b[2];
    return PKR_MB_E_EXCEPTION;
  }
  return 0;
}

int pkr_modbus_parse_read(const uint8_t *b, size_t n, uint8_t addr, uint16_t count, uint16_t *regs, uint8_t *exception) {
  int ex = exception_reply(b, n, addr, 0x03, exception);
  if (ex) return ex;
  if (n < 5) return PKR_MB_E_SHORT;
  if (b[0] != addr) return PKR_MB_E_ADDR;
  if (b[1] != 0x03) return PKR_MB_E_FC;
  if (b[2] != count * 2) return PKR_MB_E_COUNT;
  size_t want = 3u + (size_t)count * 2u + 2u;
  if (n < want) return PKR_MB_E_SHORT;
  if (!crc_ok(b, want)) return PKR_MB_E_CRC;
  for (uint16_t i = 0; i < count; i++) regs[i] = (uint16_t)(b[3 + 2 * i] << 8 | b[4 + 2 * i]);
  return PKR_MB_OK;
}

int pkr_modbus_parse_write(const uint8_t *b, size_t n, const uint8_t request[8], uint8_t *exception) {
  int ex = exception_reply(b, n, request[0], 0x06, exception);
  if (ex) return ex;
  if (n < 8) return PKR_MB_E_SHORT;
  if (!crc_ok(b, 8)) return PKR_MB_E_CRC;
  return memcmp(b, request, 8) == 0 ? PKR_MB_OK : PKR_MB_E_ECHO;
}

void pkr_df_frame(uint8_t cmd, uint16_t param, int feedback, uint8_t out[10]) {
  out[0] = 0x7E;
  out[1] = 0xFF;
  out[2] = 0x06;
  out[3] = cmd;
  out[4] = feedback ? 1 : 0;
  out[5] = (uint8_t)(param >> 8);
  out[6] = (uint8_t)param;
  uint16_t sum = 0;
  for (int i = 1; i < 7; i++) sum = (uint16_t)(sum + out[i]);
  uint16_t chk = (uint16_t)(0 - sum);
  out[7] = (uint8_t)(chk >> 8);
  out[8] = (uint8_t)chk;
  out[9] = 0xEF;
}

int pkr_df_parse(const uint8_t in[10], uint8_t *cmd, uint16_t *param) {
  if (in[0] != 0x7E || in[1] != 0xFF || in[2] != 0x06 || in[9] != 0xEF) return -1;
  uint16_t sum = 0;
  for (int i = 1; i < 7; i++) sum = (uint16_t)(sum + in[i]);
  uint16_t chk = (uint16_t)(in[7] << 8 | in[8]);
  if ((uint16_t)(sum + chk) != 0) return -1;
  *cmd = in[3];
  *param = (uint16_t)(in[5] << 8 | in[6]);
  return 0;
}

int pkr_e22_channel_for(uint32_t freq_hz) {
  uint32_t khz = freq_hz / 1000u;
  if (khz < PKR_E22_BASE_KHZ || khz > PKR_E22_BASE_KHZ + 80000u) return -1;
  return (int)((khz - PKR_E22_BASE_KHZ + 500u) / 1000u);
}

uint32_t pkr_e22_channel_hz(int ch) { return (PKR_E22_BASE_KHZ + (uint32_t)ch * 1000u) * 1000u; }

void pkr_e22_config(uint16_t addr, uint8_t netid, uint8_t channel, uint8_t air_rate_code, uint8_t power_code,
                    uint8_t out[12]) {
  out[0] = 0xC0;           /* write, saved to flash */
  out[1] = 0x00;           /* start register */
  out[2] = 0x09;           /* length */
  out[3] = (uint8_t)(addr >> 8);
  out[4] = (uint8_t)addr;
  out[5] = netid;
  out[6] = (uint8_t)(0x60 | (air_rate_code & 7));  /* REG0: 9600 8N1 UART, air rate */
  out[7] = (uint8_t)(0x00 | (power_code & 3));     /* REG1: 240-byte sub-packet, RSSI noise off, power */
  out[8] = channel;                                 /* REG2 */
  out[9] = 0x80;                                    /* REG3: RSSI byte appended, transparent mode, LBT off */
  out[10] = 0x00;                                   /* CRYPT_H: module-level crypt off (frames carry their own MAC) */
  out[11] = 0x00;
}
