/* Signed siren commands (section 5.1 named shadow `siren`, desired.cmd) and their compact LoRa
 * form (section 5.3 SIREN_CMD_WRAPPED), byte for byte as backend/src/Pukaar/services/devices/protocol.py.
 *
 * Canonical string (fields in schema order, `|` separated, an empty or null string field -> "-",
 * integers in decimal, strings exactly as received; a string field is 1-96 visible ASCII
 * characters without '|'):
 *   "PKR1|"+id+"|"+device+"|"+action+"|"+pattern+"|"+clip+"|"+clip_sha256_16+"|"+level+"|"+
 *   (alert_id or "-")+"|"+cycles+"|"+repeat_every_s+"|"+repeat_cycles+"|"+cap_on_s+"|"+volume+"|"+
 *   iat+"|"+exp+"|"+ctr+"|"+src+"|"+kid
 * sig = base64url (no padding) of the first 16 bytes of HMAC-SHA256(K_dev, canonical). */
#ifndef PKR_COMMAND_H
#define PKR_COMMAND_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PKR_ID_MAX 40
#define PKR_DEVICE_MAX 40
#define PKR_CLIP_MAX 48
#define PKR_WORD_MAX 20
#define PKR_CANONICAL_MAX 512

typedef struct {
  /* strings exactly as they came over the wire (they are what was signed) */
  char id[PKR_ID_MAX];
  char device[PKR_DEVICE_MAX];
  char action[PKR_WORD_MAX];
  char pattern[PKR_WORD_MAX];
  char clip[PKR_CLIP_MAX];
  char clip_sha256_16[PKR_WORD_MAX + 4];
  char level[PKR_WORD_MAX];
  char alert_id[PKR_ID_MAX]; /* empty = null -> "-" in the canonical string (as every string field) */
  char src[PKR_WORD_MAX];
  uint32_t cycles, repeat_every_s, repeat_cycles, cap_on_s, volume, iat, exp, ctr, kid;
  uint8_t sig[16];
  uint8_t has_sig;
} pkr_cmd_t;

/* Builds the canonical string. Returns its length, or -1 if it does not fit or a field is not
 * 1-96 visible ASCII characters without '|' (a '|' would let two commands sign the same bytes). */
int pkr_cmd_canonical(const pkr_cmd_t *c, char *out, size_t cap);
/* Computes c->sig with key. Returns 0, or -1 if the canonical string cannot be built. */
int pkr_cmd_sign(pkr_cmd_t *c, const uint8_t *key, size_t key_len);
/* 1 if c->sig is the right MAC for key (constant-time), else 0. */
int pkr_cmd_verify(const pkr_cmd_t *c, const uint8_t *key, size_t key_len);
/* The sig as base64url without padding (22 chars + NUL). */
void pkr_cmd_sig_b64(const pkr_cmd_t *c, char out[24]);
/* Parses a base64url sig (padding optional) into c->sig. 0 or -1. */
int pkr_cmd_set_sig_b64(pkr_cmd_t *c, const char *b64);

/* Enum view of a command, checked against the schema. level is a PKR_CMDLEVEL_* (0 = "-"). */
typedef struct {
  int action, pattern, level, src;
} pkr_cmd_enums_t;
/* 0 if action, pattern and level (both may be "-" only for a stop) and src are known names. */
int pkr_cmd_enums(const pkr_cmd_t *c, pkr_cmd_enums_t *e);

/* ---- compact LoRa form, SIREN_CMD_WRAPPED payload (36 bytes, one frame) ----
 * cmd_id48 6 | action u8 | pattern u8 | cmd_level u8 | cycles u8 | cap_on_s u16 | exp u32 | ctr u32 | sig16 16
 * cmd_id48 = first 6 bytes of SHA-256(cmd.id).
 *   sig16 = first 16 bytes of HMAC-SHA256(K_siren, "PKR1C|" + device + "|" + payload[0..20))
 * The outer frame MAC is the forwarder's; this inner MAC is the siren's own key, so a box,
 * gauge or relay can carry the command but cannot forge or alter it. */
#define PKR_WRAPPED_SIGNED_LEN 20
typedef struct {
  uint8_t cmd_id48[6];
  uint8_t action, pattern, level, cycles;
  uint16_t cap_on_s;
  uint32_t exp, ctr;
  uint8_t sig16[16];
} pkr_wrapped_cmd_t;

void pkr_cmd_id48(const char *id, uint8_t out[6]);
void pkr_wrapped_encode(const pkr_wrapped_cmd_t *w, uint8_t out[36]);
void pkr_wrapped_decode(const uint8_t in[36], pkr_wrapped_cmd_t *w);
void pkr_wrapped_sign(pkr_wrapped_cmd_t *w, const char *device, const uint8_t *key, size_t key_len);
int pkr_wrapped_verify(const pkr_wrapped_cmd_t *w, const char *device, const uint8_t *key, size_t key_len);

#ifdef __cplusplus
}
#endif
#endif
