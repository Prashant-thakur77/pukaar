/* LoRa P2P frame (section 5.3), binary little-endian, at most 64 bytes:
 *   0 ver(1)=1 | 1 type(1) | 2 src(2) | 4 dst(2, 0xFFFF broadcast) | 6 ctr(4) | 10 ts(4, unix s, 0 unsynced)
 *   14 len(1) | 15 payload(len <= 40) | 15+len mac(8) = first 8 bytes of HMAC-SHA256(K_src, bytes[0 .. 15+len)) */
#ifndef PKR_FRAME_H
#define PKR_FRAME_H

#include <stddef.h>
#include <stdint.h>

#include "schema.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  uint8_t ver, type;
  uint16_t src, dst;
  uint32_t ctr, ts;
  uint8_t len;
  uint8_t payload[PKR_FRAME_MAX_PAYLOAD];
  uint8_t mac[PKR_FRAME_MAC_LEN];
} pkr_frame_t;

enum {
  PKR_FRAME_OK = 0,
  PKR_FRAME_E_SHORT = -1,     /* fewer than header + mac bytes */
  PKR_FRAME_E_VERSION = -2,   /* ver != 1 */
  PKR_FRAME_E_LEN = -3,       /* len > 40, or the byte count does not match len */
  PKR_FRAME_E_TYPE_LEN = -4,  /* a known type with the wrong payload length */
  PKR_FRAME_E_TYPE = -5,      /* unknown type */
  PKR_FRAME_E_CAP = -6,       /* output buffer too small */
};

/* Writes header, payload and MAC (computed with key). Returns the total length or an error. */
int pkr_frame_encode(pkr_frame_t *f, const uint8_t *key, size_t key_len, uint8_t *out, size_t cap);
/* Structural parse only, as protocol.decode_frame: size (<= 64), version, len (<= 40) and the byte
 * count. No MAC check (the receiver needs src to pick the key) and no type check (an unknown type
 * is refused by the receiver's role check). */
int pkr_frame_parse(const uint8_t *buf, size_t n, pkr_frame_t *f);
/* PKR_FRAME_OK if `len` is the payload length of a known `type`. */
int pkr_frame_type_len_ok(uint8_t type, uint8_t len);
/* 1 if the trailing MAC matches key over bytes[0 .. n-8). Constant-time. */
int pkr_frame_mac_ok(const uint8_t *buf, size_t n, const uint8_t *key, size_t key_len);

/* ---- payloads ---- */
typedef struct {
  uint8_t level;
  int16_t stage_cm;
  int16_t rise_10min_cm;
  uint8_t quality;
  uint8_t cloud_ok;
  uint16_t rain_15min_tenths_mm;
} pkr_gauge_payload_t;
void pkr_gauge_payload_encode(const pkr_gauge_payload_t *g, uint8_t out[PKR_FT_GAUGE_STATUS_LEN]);
void pkr_gauge_payload_decode(const uint8_t in[PKR_FT_GAUGE_STATUS_LEN], pkr_gauge_payload_t *g);

typedef struct {
  uint8_t button, key_pos;
  uint16_t hold_ms;
} pkr_button_payload_t;
void pkr_button_payload_encode(const pkr_button_payload_t *b, uint8_t out[PKR_FT_BUTTON_LEN]);
void pkr_button_payload_decode(const uint8_t in[PKR_FT_BUTTON_LEN], pkr_button_payload_t *b);

typedef struct {
  uint16_t acked_src;
  uint32_t acked_ctr;
} pkr_ack_payload_t;
void pkr_ack_payload_encode(const pkr_ack_payload_t *a, uint8_t out[PKR_FT_ACK_LEN]);
void pkr_ack_payload_decode(const uint8_t in[PKR_FT_ACK_LEN], pkr_ack_payload_t *a);

typedef struct {
  uint8_t state, soc;
  uint16_t batt_dv, faults, outbox;
} pkr_heartbeat_payload_t;
void pkr_heartbeat_payload_encode(const pkr_heartbeat_payload_t *h, uint8_t out[PKR_FT_HEARTBEAT_LEN]);
void pkr_heartbeat_payload_decode(const uint8_t in[PKR_FT_HEARTBEAT_LEN], pkr_heartbeat_payload_t *h);

typedef struct {
  uint16_t bus_dv, bus_ma;
  uint8_t soc;
  int8_t noise_dbm;
} pkr_beacon_payload_t;
void pkr_beacon_payload_encode(const pkr_beacon_payload_t *b, uint8_t out[PKR_FT_RELAY_BEACON_LEN]);
void pkr_beacon_payload_decode(const uint8_t in[PKR_FT_RELAY_BEACON_LEN], pkr_beacon_payload_t *b);

typedef struct {
  uint8_t type;
  uint8_t cmd_id48[6];
  uint8_t verified, amp_a_x10, spl_rise;
} pkr_siren_event_payload_t;
void pkr_siren_event_payload_encode(const pkr_siren_event_payload_t *e, uint8_t out[PKR_FT_SIREN_EVENT_LEN]);
void pkr_siren_event_payload_decode(const uint8_t in[PKR_FT_SIREN_EVENT_LEN], pkr_siren_event_payload_t *e);

/* LoRa time on air (Semtech AN1200.13 formula), in ms, for the duty-cycle governor. */
uint32_t pkr_lora_airtime_ms(unsigned payload_len, unsigned sf, uint32_t bw_hz, unsigned cr_denom,
                             unsigned preamble, int explicit_header, int crc_on);

#ifdef __cplusplus
}
#endif
#endif
