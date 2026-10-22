/* Text encodings used on the wire: hex, base64url (shadow sig), Crockford base32 (SMS sig),
 * base36 (SMS expiry), and little-endian helpers (LoRa frame). */
#ifndef PKR_CODEC_H
#define PKR_CODEC_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Writes 2*n hex chars and a NUL (lowercase). out must hold 2*n+1. */
void pkr_hex_encode(const uint8_t *in, size_t n, char *out);
/* Decodes up to cap bytes; returns the byte count or -1 on an odd length / bad digit / overflow. */
int pkr_hex_decode(const char *in, uint8_t *out, size_t cap);

/* base64url (RFC 4648 section 5) without padding. Returns chars written (NUL added). */
size_t pkr_b64url_encode(const uint8_t *in, size_t n, char *out, size_t cap);
/* Accepts with or without '=' padding, and the standard alphabet's '+' '/'. -1 on error. */
int pkr_b64url_decode(const char *in, size_t len, uint8_t *out, size_t cap);
/* Standard base64 with padding (LoRa frames in `>LORA <b64>` and the mesh relay topic). */
size_t pkr_b64_encode(const uint8_t *in, size_t n, char *out, size_t cap);

/* Crockford base32 (0-9 A-Z without I L O U), most significant bit first, no padding.
 * 10 bytes -> 16 characters. Upper case on output. */
size_t pkr_b32c_encode(const uint8_t *in, size_t n, char *out, size_t cap);
/* Case-insensitive; I and L read as 1, O as 0 (Crockford's decoding rules); hyphens ignored.
 * Returns bytes written or -1. Trailing bits that do not fill a byte must be zero. */
int pkr_b32c_decode(const char *in, size_t len, uint8_t *out, size_t cap);

/* base36 of an unsigned 32-bit value, upper case, no leading zeros ("0" for zero). */
size_t pkr_b36_encode(uint32_t v, char *out, size_t cap);
/* Case-insensitive. Returns 0 on success, -1 on a bad digit, empty input or overflow. */
int pkr_b36_decode(const char *in, size_t len, uint32_t *out);

static inline void pkr_put_u16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static inline void pkr_put_u32(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static inline uint16_t pkr_get_u16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static inline uint32_t pkr_get_u32(const uint8_t *p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

#ifdef __cplusplus
}
#endif
#endif
