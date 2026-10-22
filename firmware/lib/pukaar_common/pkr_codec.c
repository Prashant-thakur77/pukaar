#include "pkr_codec.h"

#include <string.h>

static const char HEX[] = "0123456789abcdef";

void pkr_hex_encode(const uint8_t *in, size_t n, char *out) {
  for (size_t i = 0; i < n; i++) {
    out[2 * i] = HEX[in[i] >> 4];
    out[2 * i + 1] = HEX[in[i] & 15];
  }
  out[2 * n] = 0;
}

static int hexval(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

int pkr_hex_decode(const char *in, uint8_t *out, size_t cap) {
  size_t n = strlen(in);
  if (n % 2 || n / 2 > cap) return -1;
  for (size_t i = 0; i < n / 2; i++) {
    int hi = hexval(in[2 * i]), lo = hexval(in[2 * i + 1]);
    if (hi < 0 || lo < 0) return -1;
    out[i] = (uint8_t)(hi << 4 | lo);
  }
  return (int)(n / 2);
}

static const char B64URL[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
static const char B64STD[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static size_t b64_encode(const char *alpha, int pad, const uint8_t *in, size_t n, char *out, size_t cap) {
  size_t o = 0;
  for (size_t i = 0; i < n; i += 3) {
    uint32_t v = (uint32_t)in[i] << 16;
    size_t rem = n - i;
    if (rem > 1) v |= (uint32_t)in[i + 1] << 8;
    if (rem > 2) v |= in[i + 2];
    char q[4] = {alpha[(v >> 18) & 63], alpha[(v >> 12) & 63], alpha[(v >> 6) & 63], alpha[v & 63]};
    size_t take = rem >= 3 ? 4 : rem + 1;
    for (size_t k = 0; k < 4; k++) {
      if (k >= take && !pad) break;
      if (o + 1 >= cap) { out[o] = 0; return o; }
      out[o++] = k < take ? q[k] : '=';
    }
  }
  if (o < cap) out[o] = 0;
  return o;
}

size_t pkr_b64url_encode(const uint8_t *in, size_t n, char *out, size_t cap) { return b64_encode(B64URL, 0, in, n, out, cap); }
size_t pkr_b64_encode(const uint8_t *in, size_t n, char *out, size_t cap) { return b64_encode(B64STD, 1, in, n, out, cap); }

static int b64val(char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '-' || c == '+') return 62;
  if (c == '_' || c == '/') return 63;
  return -1;
}

int pkr_b64url_decode(const char *in, size_t len, uint8_t *out, size_t cap) {
  while (len && in[len - 1] == '=') len--;
  if (len % 4 == 1) return -1;
  uint32_t acc = 0;
  int bits = 0;
  size_t o = 0;
  for (size_t i = 0; i < len; i++) {
    int v = b64val(in[i]);
    if (v < 0) return -1;
    acc = (acc << 6) | (uint32_t)v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      if (o >= cap) return -1;
      out[o++] = (uint8_t)(acc >> bits);
    }
  }
  if (bits && (acc & ((1u << bits) - 1))) return -1; /* non-canonical trailing bits */
  return (int)o;
}

static const char B32C[] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

size_t pkr_b32c_encode(const uint8_t *in, size_t n, char *out, size_t cap) {
  uint32_t acc = 0;
  int bits = 0;
  size_t o = 0;
  for (size_t i = 0; i < n; i++) {
    acc = (acc << 8) | in[i];
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      if (o + 1 >= cap) { out[o] = 0; return o; }
      out[o++] = B32C[(acc >> bits) & 31];
    }
  }
  if (bits) {
    if (o + 1 < cap) out[o++] = B32C[(acc << (5 - bits)) & 31];
  }
  if (o < cap) out[o] = 0;
  return o;
}

static int b32cval(char c) {
  if (c >= 'a' && c <= 'z') c = (char)(c - 32);
  if (c == 'O') return 0;
  if (c == 'I' || c == 'L') return 1;
  for (int i = 0; i < 32; i++) if (B32C[i] == c) return i;
  return -1;
}

int pkr_b32c_decode(const char *in, size_t len, uint8_t *out, size_t cap) {
  uint32_t acc = 0;
  int bits = 0;
  size_t o = 0;
  for (size_t i = 0; i < len; i++) {
    if (in[i] == '-') continue;
    int v = b32cval(in[i]);
    if (v < 0) return -1;
    acc = (acc << 5) | (uint32_t)v;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      if (o >= cap) return -1;
      out[o++] = (uint8_t)(acc >> bits);
    }
  }
  if (bits && (acc & ((1u << bits) - 1))) return -1;
  return (int)o;
}

size_t pkr_b36_encode(uint32_t v, char *out, size_t cap) {
  char tmp[8];
  size_t n = 0;
  do {
    uint32_t d = v % 36;
    tmp[n++] = (char)(d < 10 ? '0' + d : 'A' + d - 10);
    v /= 36;
  } while (v);
  if (n + 1 > cap) { if (cap) out[0] = 0; return 0; }
  for (size_t i = 0; i < n; i++) out[i] = tmp[n - 1 - i];
  out[n] = 0;
  return n;
}

int pkr_b36_decode(const char *in, size_t len, uint32_t *out) {
  if (!len || len > 7) return -1;
  uint64_t v = 0;
  for (size_t i = 0; i < len; i++) {
    char c = in[i];
    int d;
    if (c >= '0' && c <= '9') d = c - '0';
    else if (c >= 'A' && c <= 'Z') d = c - 'A' + 10;
    else if (c >= 'a' && c <= 'z') d = c - 'a' + 10;
    else return -1;
    v = v * 36 + (uint64_t)d;
  }
  if (v > 0xFFFFFFFFull) return -1;
  *out = (uint32_t)v;
  return 0;
}
