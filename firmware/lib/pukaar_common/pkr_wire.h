/* Byte-level codecs for the peripherals, kept apart from the UART drivers so they can be tested:
 *  - DFRobot SEN0676 radar: Modbus RTU (clean-room from the public register map; the third-party
 *    library has no licence, so nothing is copied from it). CRC-16/MODBUS, low byte first.
 *  - DFPlayer Mini: the 10-byte serial frame, written from the published protocol (the DFRobot
 *    library is not used).
 *  - Ebyte E22-900T22S: the configuration register write. */
#ifndef PKR_WIRE_H
#define PKR_WIRE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- Modbus RTU / SEN0676 ---- */
#define PKR_SEN0676_ADDR 0x01
#define PKR_SEN0676_REG_EMPTY_HEIGHT_MM 0x0001  /* distance from the face to the water */
#define PKR_SEN0676_REG_LEVEL_MM 0x0003
#define PKR_SEN0676_REG_INSTALL_HEIGHT_CM 0x0005  /* R/W, written to NVM: read before writing */
#define PKR_SEN0676_REG_ADDRESS 0x03F4
#define PKR_SEN0676_REG_BAUD_DIV100 0x03F6
#define PKR_SEN0676_REG_RANGE_M 0x07D4

uint16_t pkr_modbus_crc(const uint8_t *b, size_t n);
/* 8-byte request: addr, fc, reg hi/lo, value-or-count hi/lo, crc lo/hi. */
void pkr_modbus_request(uint8_t addr, uint8_t fc, uint16_t reg, uint16_t value, uint8_t out[8]);

enum {
  PKR_MB_OK = 0,
  PKR_MB_E_SHORT = -1,
  PKR_MB_E_CRC = -2,
  PKR_MB_E_ADDR = -3,
  PKR_MB_E_FC = -4,
  PKR_MB_E_COUNT = -5,
  PKR_MB_E_EXCEPTION = -6, /* fc | 0x80 (0x83, 0x86): *exception holds the code */
  PKR_MB_E_ECHO = -7,      /* a 0x06 write echo that differs from the request */
};

/* Parses a 0x03 reply for `count` registers into regs[]. n is the byte count received.
 * Exception replies are 5 bytes: addr, fc|0x80, code, crc. */
int pkr_modbus_parse_read(const uint8_t *b, size_t n, uint8_t addr, uint16_t count, uint16_t *regs, uint8_t *exception);
/* Checks a 0x06 write echo (the sensor echoes the 8-byte request once it has committed). */
int pkr_modbus_parse_write(const uint8_t *b, size_t n, const uint8_t request[8], uint8_t *exception);

/* ---- DFPlayer Mini ---- */
#define PKR_DF_PLAY_FOLDER_FILE 0x0F  /* param hi = folder 01-99, lo = file 001-255 */
#define PKR_DF_VOLUME 0x06            /* 0-30 */
#define PKR_DF_STOP 0x16
#define PKR_DF_RESET 0x0C
#define PKR_DF_QUERY_STATUS 0x42
#define PKR_DF_QUERY_FILES_SD 0x48
#define PKR_DF_EVT_FINISHED_SD 0x3D
#define PKR_DF_EVT_ERROR 0x40
#define PKR_DF_EVT_ACK 0x41

/* 7E FF 06 cmd fb p_hi p_lo chk_hi chk_lo EF; chk = 0 - (FF + 06 + cmd + fb + p_hi + p_lo) */
void pkr_df_frame(uint8_t cmd, uint16_t param, int feedback, uint8_t out[10]);
/* 0 and *cmd, *param for a well-formed frame; -1 otherwise. */
int pkr_df_parse(const uint8_t in[10], uint8_t *cmd, uint16_t *param);

/* ---- Ebyte E22-900T22S (UART LoRa module) ----
 * Channel raster: f = 850.125 MHz + CH x 1 MHz. The spec's 865.4025 and 865.985 MHz are NOT on
 * this raster; CH 15 (865.125 MHz) is the nearest channel inside 865-867 MHz. The module also
 * hides SF/BW behind an "air data rate" table. See firmware/README.md (radio notes). */
#define PKR_E22_BASE_KHZ 850125u
int pkr_e22_channel_for(uint32_t freq_hz);   /* nearest channel, -1 if outside 850-930 MHz */
uint32_t pkr_e22_channel_hz(int ch);
/* C0 00 09 ADDH ADDL NETID REG0 REG1 REG2(CH) REG3 CRYPT_H CRYPT_L: write 9 registers to RAM+flash.
 * air_rate_code 0..7 (0.3k .. 62.5k, 2 = 2.4k default), power_code 0 = 22 dBm .. 3 = 10 dBm.
 * REG3 enables RSSI byte output and fixed-point transmission off (transparent). */
void pkr_e22_config(uint16_t addr, uint8_t netid, uint8_t channel, uint8_t air_rate_code, uint8_t power_code,
                    uint8_t out[12]);

#ifdef __cplusplus
}
#endif
#endif
