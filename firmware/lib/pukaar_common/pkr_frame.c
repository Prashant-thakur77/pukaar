#include "pkr_frame.h"

#include <string.h>

#include "pkr_codec.h"
#include "pkr_crypto.h"

static void header(const pkr_frame_t *f, uint8_t *out) {
  out[0] = f->ver;
  out[1] = f->type;
  pkr_put_u16(out + 2, f->src);
  pkr_put_u16(out + 4, f->dst);
  pkr_put_u32(out + 6, f->ctr);
  pkr_put_u32(out + 10, f->ts);
  out[14] = f->len;
}

int pkr_frame_encode(pkr_frame_t *f, const uint8_t *key, size_t key_len, uint8_t *out, size_t cap) {
  if (f->len > PKR_FRAME_MAX_PAYLOAD) return PKR_FRAME_E_LEN;
  int want = pkr_frame_payload_len(f->type);
  if (want >= 0 && want != f->len) return PKR_FRAME_E_TYPE_LEN;
  size_t total = PKR_FRAME_HEADER_LEN + f->len + PKR_FRAME_MAC_LEN;
  if (cap < total) return PKR_FRAME_E_CAP;
  header(f, out);
  memcpy(out + PKR_FRAME_HEADER_LEN, f->payload, f->len);
  uint8_t mac[PKR_SHA256_LEN];
  pkr_hmac_sha256(key, key_len, out, PKR_FRAME_HEADER_LEN + f->len, mac);
  memcpy(f->mac, mac, PKR_FRAME_MAC_LEN);
  memcpy(out + PKR_FRAME_HEADER_LEN + f->len, mac, PKR_FRAME_MAC_LEN);
  return (int)total;
}

int pkr_frame_type_len_ok(uint8_t type, uint8_t len) {
  int want = pkr_frame_payload_len(type);
  if (want < 0) return PKR_FRAME_E_TYPE;
  return want == len ? PKR_FRAME_OK : PKR_FRAME_E_TYPE_LEN;
}

int pkr_frame_parse(const uint8_t *buf, size_t n, pkr_frame_t *f) {
  if (n > PKR_FRAME_MAX_LEN) return PKR_FRAME_E_LEN;
  if (n < PKR_FRAME_HEADER_LEN + PKR_FRAME_MAC_LEN) return PKR_FRAME_E_SHORT;
  if (buf[0] != PKR_FRAME_VERSION) return PKR_FRAME_E_VERSION;
  uint8_t len = buf[14];
  if (len > PKR_FRAME_MAX_PAYLOAD || n != (size_t)PKR_FRAME_HEADER_LEN + len + PKR_FRAME_MAC_LEN) return PKR_FRAME_E_LEN;
  f->ver = buf[0];
  f->type = buf[1];
  f->src = pkr_get_u16(buf + 2);
  f->dst = pkr_get_u16(buf + 4);
  f->ctr = pkr_get_u32(buf + 6);
  f->ts = pkr_get_u32(buf + 10);
  f->len = len;
  memcpy(f->payload, buf + PKR_FRAME_HEADER_LEN, len);
  memcpy(f->mac, buf + PKR_FRAME_HEADER_LEN + len, PKR_FRAME_MAC_LEN);
  return PKR_FRAME_OK;
}

int pkr_frame_mac_ok(const uint8_t *buf, size_t n, const uint8_t *key, size_t key_len) {
  if (n < PKR_FRAME_HEADER_LEN + PKR_FRAME_MAC_LEN) return 0;
  uint8_t mac[PKR_SHA256_LEN];
  pkr_hmac_sha256(key, key_len, buf, n - PKR_FRAME_MAC_LEN, mac);
  return pkr_ct_equal(mac, buf + n - PKR_FRAME_MAC_LEN, PKR_FRAME_MAC_LEN);
}

void pkr_gauge_payload_encode(const pkr_gauge_payload_t *g, uint8_t out[PKR_FT_GAUGE_STATUS_LEN]) {
  out[0] = g->level;
  pkr_put_u16(out + 1, (uint16_t)g->stage_cm);
  pkr_put_u16(out + 3, (uint16_t)g->rise_10min_cm);
  out[5] = g->quality;
  out[6] = g->cloud_ok;
  pkr_put_u16(out + 7, g->rain_15min_tenths_mm);
}

void pkr_gauge_payload_decode(const uint8_t in[PKR_FT_GAUGE_STATUS_LEN], pkr_gauge_payload_t *g) {
  g->level = in[0];
  g->stage_cm = (int16_t)pkr_get_u16(in + 1);
  g->rise_10min_cm = (int16_t)pkr_get_u16(in + 3);
  g->quality = in[5];
  g->cloud_ok = in[6];
  g->rain_15min_tenths_mm = pkr_get_u16(in + 7);
}

void pkr_button_payload_encode(const pkr_button_payload_t *b, uint8_t out[PKR_FT_BUTTON_LEN]) {
  out[0] = b->button;
  out[1] = b->key_pos;
  pkr_put_u16(out + 2, b->hold_ms);
}

void pkr_button_payload_decode(const uint8_t in[PKR_FT_BUTTON_LEN], pkr_button_payload_t *b) {
  b->button = in[0];
  b->key_pos = in[1];
  b->hold_ms = pkr_get_u16(in + 2);
}

void pkr_ack_payload_encode(const pkr_ack_payload_t *a, uint8_t out[PKR_FT_ACK_LEN]) {
  pkr_put_u16(out, a->acked_src);
  pkr_put_u32(out + 2, a->acked_ctr);
}

void pkr_ack_payload_decode(const uint8_t in[PKR_FT_ACK_LEN], pkr_ack_payload_t *a) {
  a->acked_src = pkr_get_u16(in);
  a->acked_ctr = pkr_get_u32(in + 2);
}

void pkr_heartbeat_payload_encode(const pkr_heartbeat_payload_t *h, uint8_t out[PKR_FT_HEARTBEAT_LEN]) {
  out[0] = h->state;
  out[1] = h->soc;
  pkr_put_u16(out + 2, h->batt_dv);
  pkr_put_u16(out + 4, h->faults);
  pkr_put_u16(out + 6, h->outbox);
}

void pkr_heartbeat_payload_decode(const uint8_t in[PKR_FT_HEARTBEAT_LEN], pkr_heartbeat_payload_t *h) {
  h->state = in[0];
  h->soc = in[1];
  h->batt_dv = pkr_get_u16(in + 2);
  h->faults = pkr_get_u16(in + 4);
  h->outbox = pkr_get_u16(in + 6);
}

void pkr_beacon_payload_encode(const pkr_beacon_payload_t *b, uint8_t out[PKR_FT_RELAY_BEACON_LEN]) {
  pkr_put_u16(out, b->bus_dv);
  pkr_put_u16(out + 2, b->bus_ma);
  out[4] = b->soc;
  out[5] = (uint8_t)b->noise_dbm;
}

void pkr_beacon_payload_decode(const uint8_t in[PKR_FT_RELAY_BEACON_LEN], pkr_beacon_payload_t *b) {
  b->bus_dv = pkr_get_u16(in);
  b->bus_ma = pkr_get_u16(in + 2);
  b->soc = in[4];
  b->noise_dbm = (int8_t)in[5];
}

void pkr_siren_event_payload_encode(const pkr_siren_event_payload_t *e, uint8_t out[PKR_FT_SIREN_EVENT_LEN]) {
  out[0] = e->type;
  memcpy(out + 1, e->cmd_id48, 6);
  out[7] = e->verified;
  out[8] = e->amp_a_x10;
  out[9] = e->spl_rise;
}

void pkr_siren_event_payload_decode(const uint8_t in[PKR_FT_SIREN_EVENT_LEN], pkr_siren_event_payload_t *e) {
  e->type = in[0];
  memcpy(e->cmd_id48, in + 1, 6);
  e->verified = in[7];
  e->amp_a_x10 = in[8];
  e->spl_rise = in[9];
}

uint32_t pkr_lora_airtime_ms(unsigned payload_len, unsigned sf, uint32_t bw_hz, unsigned cr_denom,
                             unsigned preamble, int explicit_header, int crc_on) {
  /* T_sym = 2^SF / BW; low data rate optimisation when T_sym > 16 ms (SF11/12 at 125 kHz). */
  double tsym_ms = (double)(1u << sf) * 1000.0 / (double)bw_hz;
  int de = tsym_ms > 16.0 ? 1 : 0;
  int ih = explicit_header ? 0 : 1;
  int cr = (int)cr_denom - 4; /* 4/5 -> 1 ... 4/8 -> 4 */
  double t_pre = ((double)preamble + 4.25) * tsym_ms;
  int num = 8 * (int)payload_len - 4 * (int)sf + 28 + 16 * (crc_on ? 1 : 0) - 20 * ih;
  int den = 4 * ((int)sf - 2 * de);
  int ceil_v = num > 0 ? (num + den - 1) / den : 0;
  int n_payload = 8 + ceil_v * (cr + 4);
  double total = t_pre + (double)n_payload * tsym_ms;
  return (uint32_t)(total + 0.999);
}
