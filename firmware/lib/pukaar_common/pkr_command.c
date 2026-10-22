#include "pkr_command.h"

#include <stdio.h>
#include <string.h>

#include "pkr_codec.h"
#include "pkr_crypto.h"
#include "schema.h"

/* A string field as it is signed: empty -> "-"; otherwise 1-96 visible ASCII characters (0x21-0x7e)
 * without '|'. NULL if the field cannot be signed (the backend raises ProtocolError there). */
static const char *field(const char *s) {
  size_t n = strlen(s);
  if (n == 0) return "-";
  if (n > 96) return NULL;
  for (size_t i = 0; i < n; i++)
    if ((unsigned char)s[i] < 0x21 || (unsigned char)s[i] > 0x7e || s[i] == '|') return NULL;
  return s;
}

int pkr_cmd_canonical(const pkr_cmd_t *c, char *out, size_t cap) {
  const char *f[] = {field(c->id),   field(c->device),         field(c->action), field(c->pattern), field(c->clip),
                     field(c->clip_sha256_16), field(c->level), field(c->alert_id), field(c->src)};
  for (size_t i = 0; i < sizeof f / sizeof f[0]; i++)
    if (!f[i]) return -1;
  int n = snprintf(out, cap,
                   PKR_PROTOCOL "|%s|%s|%s|%s|%s|%s|%s|%s|%lu|%lu|%lu|%lu|%lu|%lu|%lu|%lu|%s|%lu",
                   f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], (unsigned long)c->cycles, (unsigned long)c->repeat_every_s,
                   (unsigned long)c->repeat_cycles, (unsigned long)c->cap_on_s, (unsigned long)c->volume,
                   (unsigned long)c->iat, (unsigned long)c->exp, (unsigned long)c->ctr, f[8], (unsigned long)c->kid);
  if (n < 0 || (size_t)n >= cap) return -1;
  return n;
}

static int mac16(const pkr_cmd_t *c, const uint8_t *key, size_t key_len, uint8_t out[16]) {
  char buf[PKR_CANONICAL_MAX];
  int n = pkr_cmd_canonical(c, buf, sizeof buf);
  if (n < 0) return -1;
  uint8_t full[PKR_SHA256_LEN];
  pkr_hmac_sha256(key, key_len, buf, (size_t)n, full);
  memcpy(out, full, 16);
  return 0;
}

int pkr_cmd_sign(pkr_cmd_t *c, const uint8_t *key, size_t key_len) {
  if (mac16(c, key, key_len, c->sig) < 0) return -1;
  c->has_sig = 1;
  return 0;
}

int pkr_cmd_verify(const pkr_cmd_t *c, const uint8_t *key, size_t key_len) {
  uint8_t want[16];
  if (!c->has_sig || mac16(c, key, key_len, want) < 0) return 0;
  return pkr_ct_equal(want, c->sig, 16);
}

void pkr_cmd_sig_b64(const pkr_cmd_t *c, char out[24]) { pkr_b64url_encode(c->sig, 16, out, 24); }

int pkr_cmd_set_sig_b64(pkr_cmd_t *c, const char *b64) {
  uint8_t tmp[18];
  int n = pkr_b64url_decode(b64, strlen(b64), tmp, sizeof tmp);
  if (n != 16) return -1;
  memcpy(c->sig, tmp, 16);
  c->has_sig = 1;
  return 0;
}

static int empty(const char *s) { return !s[0] || (s[0] == '-' && !s[1]); }

int pkr_cmd_enums(const pkr_cmd_t *c, pkr_cmd_enums_t *e) {
  e->action = pkr_action_from_name(c->action);
  e->pattern = empty(c->pattern) ? PKR_PATTERN_NONE : pkr_pattern_from_name(c->pattern);
  e->level = empty(c->level) ? 0 : pkr_cmd_level_from_name(c->level);
  e->src = pkr_src_from_name(c->src);
  if (e->action < 0 || e->pattern < 0 || e->src < 0 || e->level < 0) return -1;
  if (e->level == 0 && e->action != PKR_ACTION_STOP) return -1;
  if (e->pattern == PKR_PATTERN_NONE && e->action != PKR_ACTION_STOP) return -1;
  if (e->pattern == PKR_PATTERN_B1) return -1; /* the bridge beacon is never a siren command */
  return 0;
}

void pkr_cmd_id48(const char *id, uint8_t out[6]) {
  uint8_t h[PKR_SHA256_LEN];
  pkr_sha256(id, strlen(id), h);
  memcpy(out, h, 6);
}

void pkr_wrapped_encode(const pkr_wrapped_cmd_t *w, uint8_t out[36]) {
  memcpy(out, w->cmd_id48, 6);
  out[6] = w->action;
  out[7] = w->pattern;
  out[8] = w->level;
  out[9] = w->cycles;
  pkr_put_u16(out + 10, w->cap_on_s);
  pkr_put_u32(out + 12, w->exp);
  pkr_put_u32(out + 16, w->ctr);
  memcpy(out + 20, w->sig16, 16);
}

void pkr_wrapped_decode(const uint8_t in[36], pkr_wrapped_cmd_t *w) {
  memcpy(w->cmd_id48, in, 6);
  w->action = in[6];
  w->pattern = in[7];
  w->level = in[8];
  w->cycles = in[9];
  w->cap_on_s = pkr_get_u16(in + 10);
  w->exp = pkr_get_u32(in + 12);
  w->ctr = pkr_get_u32(in + 16);
  memcpy(w->sig16, in + 20, 16);
}

static void wrapped_mac(const pkr_wrapped_cmd_t *w, const char *device, const uint8_t *key, size_t key_len, uint8_t out[16]) {
  uint8_t body[36], full[PKR_SHA256_LEN];
  pkr_wrapped_encode(w, body);
  pkr_hmac_ctx h;
  pkr_hmac_init(&h, key, key_len);
  pkr_hmac_update(&h, "PKR1C|", 6);
  pkr_hmac_update(&h, device, strlen(device));
  pkr_hmac_update(&h, "|", 1);
  pkr_hmac_update(&h, body, PKR_WRAPPED_SIGNED_LEN);
  pkr_hmac_final(&h, full);
  memcpy(out, full, 16);
}

void pkr_wrapped_sign(pkr_wrapped_cmd_t *w, const char *device, const uint8_t *key, size_t key_len) {
  wrapped_mac(w, device, key, key_len, w->sig16);
}

int pkr_wrapped_verify(const pkr_wrapped_cmd_t *w, const char *device, const uint8_t *key, size_t key_len) {
  uint8_t want[16];
  wrapped_mac(w, device, key, key_len, want);
  return pkr_ct_equal(want, w->sig16, 16);
}
