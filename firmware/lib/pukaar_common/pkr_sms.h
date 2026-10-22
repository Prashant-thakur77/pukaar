/* Signed SMS fallback (section 5.4), as backend/src/Pukaar/services/devices/protocol.py. GSM-7 text,
 * at most 160 characters:
 *   PKR1 <device> <A><L> <ctr> <exp_unix_b36> <sig_b32_16>
 *   A: S sound, X stop, T test.  L: W, C, A, T or D.
 *   sig = Crockford base32 of the first 10 bytes of HMAC-SHA256(K_dev, "PKR1|device|A|L|ctr|exp")
 * In the signed string ctr and exp are plain decimal (no zero padding); in the SMS ctr is
 * zero-padded to 6 digits and exp is base36. Example:
 *   PKR1 siren-thunag-01 SC 000413 T4IZO5 0D841TW51HEEJDPN   (a golden vector)
 * The prefix, the codes and the encodings are read in any case (a phone may capitalise); the
 * device id is exact. Six words separated by single spaces; leading and trailing whitespace (a
 * modem's CR LF) is ignored; anything non-ASCII or over 160 characters is refused. */
#ifndef PKR_SMS_H
#define PKR_SMS_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  char device[65];
  char action; /* 'S' 'X' 'T' (upper case after parsing) */
  char level;  /* 'W' 'C' 'A' 'T' 'D' */
  uint32_t ctr;
  uint32_t exp;
  char sig[17];  /* 16 Crockford characters, upper case; decoded and checked by pkr_sms_verify */
} pkr_sms_t;

enum {
  PKR_SMS_OK = 0,
  PKR_SMS_E_EMPTY = -1,
  PKR_SMS_E_TOO_LONG = -2,
  PKR_SMS_E_NON_ASCII = -3,  /* Unicode (UCS-2 SMS) or control characters */
  PKR_SMS_E_PREFIX = -4,
  PKR_SMS_E_FIELDS = -5,
  PKR_SMS_E_DEVICE = -6,
  PKR_SMS_E_ACTION = -7,
  PKR_SMS_E_CTR = -8,
  PKR_SMS_E_EXP = -9,
  PKR_SMS_E_SIG = -10,
};

/* text need not be NUL-terminated. */
int pkr_sms_parse(const char *text, size_t len, pkr_sms_t *out);
/* Builds the signed string "PKR1|device|A|L|ctr|exp". Returns its length or -1. */
int pkr_sms_signed_string(const pkr_sms_t *s, char *out, size_t cap);
void pkr_sms_sign(pkr_sms_t *s, const uint8_t *key, size_t key_len);
int pkr_sms_verify(const pkr_sms_t *s, const uint8_t *key, size_t key_len);
/* Formats the SMS text (signs it first). Returns its length or -1. */
int pkr_sms_format(pkr_sms_t *s, const uint8_t *key, size_t key_len, char *out, size_t cap);

/* sha256(salt + E164) as the config shadow's `sms_allow_sha256` holds it (lower-case hex). */
void pkr_sms_sender_hash(const char *salt, const char *e164, char out_hex[65]);

/* Pattern letter <-> pattern id (schema), action letter <-> action id. -1 if unknown. */
int pkr_sms_pattern_from_letter(char l);
char pkr_sms_letter_from_pattern(int pattern);
int pkr_sms_action_from_letter(char a);
char pkr_sms_letter_from_action(int action);

#ifdef __cplusplus
}
#endif
#endif
