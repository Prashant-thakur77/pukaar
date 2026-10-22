#include "pkr_sms.h"

#include <stdio.h>
#include <string.h>

#include "pkr_codec.h"
#include "pkr_crypto.h"
#include "schema.h"

int pkr_sms_pattern_from_letter(char l) {
  switch (l) {
    case PKR_SMS_PATTERN_W1: return PKR_PATTERN_W1;
    case PKR_SMS_PATTERN_C1: return PKR_PATTERN_C1;
    case PKR_SMS_PATTERN_A1: return PKR_PATTERN_A1;
    case PKR_SMS_PATTERN_T1: return PKR_PATTERN_T1;
    case PKR_SMS_PATTERN_D1: return PKR_PATTERN_D1;
    default: return -1;
  }
}

char pkr_sms_letter_from_pattern(int pattern) {
  switch (pattern) {
    case PKR_PATTERN_W1: return PKR_SMS_PATTERN_W1;
    case PKR_PATTERN_C1: return PKR_SMS_PATTERN_C1;
    case PKR_PATTERN_A1: return PKR_SMS_PATTERN_A1;
    case PKR_PATTERN_T1: return PKR_SMS_PATTERN_T1;
    case PKR_PATTERN_D1: return PKR_SMS_PATTERN_D1;
    default: return 0;
  }
}

int pkr_sms_action_from_letter(char a) {
  switch (a) {
    case PKR_SMS_ACTION_SOUND: return PKR_ACTION_SOUND;
    case PKR_SMS_ACTION_STOP: return PKR_ACTION_STOP;
    case PKR_SMS_ACTION_TEST: return PKR_ACTION_TEST;
    default: return -1;
  }
}

char pkr_sms_letter_from_action(int action) {
  switch (action) {
    case PKR_ACTION_SOUND: return PKR_SMS_ACTION_SOUND;
    case PKR_ACTION_STOP: return PKR_SMS_ACTION_STOP;
    case PKR_ACTION_TEST: return PKR_SMS_ACTION_TEST;
    default: return 0;
  }
}

static char upper(char c) { return (c >= 'a' && c <= 'z') ? (char)(c - 32) : c; }
static int is_space(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f'; }

int pkr_sms_parse(const char *text, size_t len, pkr_sms_t *out) {
  memset(out, 0, sizeof *out);
  if (!text) return PKR_SMS_E_EMPTY;
  if (len > PKR_SMS_MAX_LEN) return PKR_SMS_E_TOO_LONG;
  for (size_t i = 0; i < len; i++)
    if ((unsigned char)text[i] >= 0x80) return PKR_SMS_E_NON_ASCII;
  while (len && is_space(text[len - 1])) len--;  /* a modem's trailing CR LF */
  while (len && is_space(*text)) {
    text++;
    len--;
  }
  if (!len) return PKR_SMS_E_EMPTY;
  /* exactly six words separated by single spaces */
  const char *f[6];
  size_t fl[6];
  int nf = 0;
  size_t s = 0;
  for (size_t i = 0; i <= len; i++) {
    if (i == len || text[i] == ' ') {
      if (nf == 6) return PKR_SMS_E_FIELDS;
      f[nf] = text + s;
      fl[nf++] = i - s;
      s = i + 1;
    }
  }
  if (nf != 6) return PKR_SMS_E_FIELDS;
  if (fl[0] != 4 || upper(f[0][0]) != 'P' || upper(f[0][1]) != 'K' || upper(f[0][2]) != 'R' || f[0][3] != '1')
    return PKR_SMS_E_PREFIX;
  /* the device id exactly as sent: 3-64 of A-Z a-z 0-9 _ . - */
  if (fl[1] < 3 || fl[1] > 64) return PKR_SMS_E_DEVICE;
  for (size_t k = 0; k < fl[1]; k++) {
    char c = f[1][k];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.'))
      return PKR_SMS_E_DEVICE;
  }
  memcpy(out->device, f[1], fl[1]);
  out->device[fl[1]] = 0;
  if (fl[2] != 2) return PKR_SMS_E_ACTION;
  out->action = upper(f[2][0]);
  out->level = upper(f[2][1]);
  if (pkr_sms_action_from_letter(out->action) < 0 || pkr_sms_pattern_from_letter(out->level) < 0) return PKR_SMS_E_ACTION;
  if (fl[3] == 0 || fl[3] > 10) return PKR_SMS_E_CTR;
  uint64_t ctr = 0;
  for (size_t k = 0; k < fl[3]; k++) {
    if (f[3][k] < '0' || f[3][k] > '9') return PKR_SMS_E_CTR;
    ctr = ctr * 10 + (uint64_t)(f[3][k] - '0');
  }
  if (ctr > 0xFFFFFFFFull) return PKR_SMS_E_CTR;
  out->ctr = (uint32_t)ctr;
  if (pkr_b36_decode(f[4], fl[4], &out->exp) < 0) return PKR_SMS_E_EXP;
  /* 16 characters of 0-9 A-Z (any case); whether they are valid Crockford is the signature check's job */
  if (fl[5] != PKR_SMS_SIG_CHARS) return PKR_SMS_E_SIG;
  for (size_t k = 0; k < fl[5]; k++) {
    char c = upper(f[5][k]);
    if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z'))) return PKR_SMS_E_SIG;
    out->sig[k] = c;
  }
  out->sig[fl[5]] = 0;
  return PKR_SMS_OK;
}

int pkr_sms_signed_string(const pkr_sms_t *s, char *out, size_t cap) {
  int n = snprintf(out, cap, PKR_PROTOCOL "|%s|%c|%c|%lu|%lu", s->device, s->action, s->level,
                   (unsigned long)s->ctr, (unsigned long)s->exp);
  return (n < 0 || (size_t)n >= cap) ? -1 : n;
}

static void sms_mac(const pkr_sms_t *s, const uint8_t *key, size_t key_len, uint8_t out[10]) {
  char buf[128];
  int n = pkr_sms_signed_string(s, buf, sizeof buf);
  uint8_t full[PKR_SHA256_LEN];
  pkr_hmac_sha256(key, key_len, buf, n < 0 ? 0 : (size_t)n, full);
  memcpy(out, full, 10);
}

void pkr_sms_sign(pkr_sms_t *s, const uint8_t *key, size_t key_len) {
  uint8_t mac[10];
  sms_mac(s, key, key_len, mac);
  pkr_b32c_encode(mac, sizeof mac, s->sig, sizeof s->sig);
}

int pkr_sms_verify(const pkr_sms_t *s, const uint8_t *key, size_t key_len) {
  uint8_t want[10], got[12];
  if (pkr_b32c_decode(s->sig, strlen(s->sig), got, sizeof got) != 10) return 0;
  sms_mac(s, key, key_len, want);
  return pkr_ct_equal(want, got, 10);
}

int pkr_sms_format(pkr_sms_t *s, const uint8_t *key, size_t key_len, char *out, size_t cap) {
  pkr_sms_sign(s, key, key_len);
  char exp36[8];
  pkr_b36_encode(s->exp, exp36, sizeof exp36);
  int n = snprintf(out, cap, PKR_PROTOCOL " %s %c%c %06lu %s %s", s->device, s->action, s->level,
                   (unsigned long)s->ctr, exp36, s->sig);
  if (n < 0 || (size_t)n >= cap || n > PKR_SMS_MAX_LEN) return -1;
  return n;
}

void pkr_sms_sender_hash(const char *salt, const char *e164, char out_hex[65]) {
  pkr_sha256_ctx c;
  uint8_t h[PKR_SHA256_LEN];
  pkr_sha256_init(&c);
  pkr_sha256_update(&c, salt, strlen(salt));
  pkr_sha256_update(&c, e164, strlen(e164));
  pkr_sha256_final(&c, h);
  pkr_hex_encode(h, sizeof h, out_hex);
}
