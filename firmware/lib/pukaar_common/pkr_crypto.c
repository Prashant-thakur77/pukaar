#include "pkr_crypto.h"

#include <stdio.h>
#include <string.h>

static const uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void block(pkr_sha256_ctx *c, const uint8_t *p) {
  uint32_t w[64];
  for (int i = 0; i < 16; i++)
    w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
  for (int i = 16; i < 64; i++) {
    uint32_t s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3);
    uint32_t s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
    w[i] = w[i - 16] + s0 + w[i - 7] + s1;
  }
  uint32_t a = c->h[0], b = c->h[1], cc = c->h[2], d = c->h[3], e = c->h[4], f = c->h[5], g = c->h[6], h = c->h[7];
  for (int i = 0; i < 64; i++) {
    uint32_t t1 = h + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
    uint32_t t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & cc) ^ (b & cc));
    h = g; g = f; f = e; e = d + t1; d = cc; cc = b; b = a; a = t1 + t2;
  }
  c->h[0] += a; c->h[1] += b; c->h[2] += cc; c->h[3] += d;
  c->h[4] += e; c->h[5] += f; c->h[6] += g; c->h[7] += h;
}

void pkr_sha256_init(pkr_sha256_ctx *c) {
  static const uint32_t H0[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  memcpy(c->h, H0, sizeof H0);
  c->total = 0;
  c->used = 0;
}

void pkr_sha256_update(pkr_sha256_ctx *c, const void *data, size_t len) {
  const uint8_t *p = (const uint8_t *)data;
  c->total += len;
  while (len) {
    size_t n = 64 - c->used;
    if (n > len) n = len;
    memcpy(c->buf + c->used, p, n);
    c->used += n; p += n; len -= n;
    if (c->used == 64) { block(c, c->buf); c->used = 0; }
  }
}

void pkr_sha256_final(pkr_sha256_ctx *c, uint8_t out[PKR_SHA256_LEN]) {
  uint64_t bits = c->total * 8;
  uint8_t pad = 0x80;
  pkr_sha256_update(c, &pad, 1);
  pad = 0;
  while (c->used != 56) pkr_sha256_update(c, &pad, 1);
  uint8_t len[8];
  for (int i = 0; i < 8; i++) len[i] = (uint8_t)(bits >> (56 - 8 * i));
  pkr_sha256_update(c, len, 8);
  for (int i = 0; i < 8; i++) {
    out[4 * i] = (uint8_t)(c->h[i] >> 24); out[4 * i + 1] = (uint8_t)(c->h[i] >> 16);
    out[4 * i + 2] = (uint8_t)(c->h[i] >> 8); out[4 * i + 3] = (uint8_t)c->h[i];
  }
}

void pkr_sha256(const void *data, size_t len, uint8_t out[PKR_SHA256_LEN]) {
  pkr_sha256_ctx c;
  pkr_sha256_init(&c);
  pkr_sha256_update(&c, data, len);
  pkr_sha256_final(&c, out);
}

void pkr_hmac_init(pkr_hmac_ctx *c, const uint8_t *key, size_t key_len) {
  uint8_t k[64] = {0}, pad[64];
  if (key_len > 64) pkr_sha256(key, key_len, k);
  else memcpy(k, key, key_len);
  for (int i = 0; i < 64; i++) pad[i] = k[i] ^ 0x36;
  pkr_sha256_init(&c->inner);
  pkr_sha256_update(&c->inner, pad, 64);
  for (int i = 0; i < 64; i++) pad[i] = k[i] ^ 0x5c;
  pkr_sha256_init(&c->outer);
  pkr_sha256_update(&c->outer, pad, 64);
  memset(k, 0, sizeof k);
}

void pkr_hmac_update(pkr_hmac_ctx *c, const void *data, size_t len) { pkr_sha256_update(&c->inner, data, len); }

void pkr_hmac_final(pkr_hmac_ctx *c, uint8_t out[PKR_SHA256_LEN]) {
  uint8_t ih[PKR_SHA256_LEN];
  pkr_sha256_final(&c->inner, ih);
  pkr_sha256_update(&c->outer, ih, sizeof ih);
  pkr_sha256_final(&c->outer, out);
}

void pkr_hmac_sha256(const uint8_t *key, size_t key_len, const void *data, size_t len, uint8_t out[PKR_SHA256_LEN]) {
  pkr_hmac_ctx c;
  pkr_hmac_init(&c, key, key_len);
  pkr_hmac_update(&c, data, len);
  pkr_hmac_final(&c, out);
}

int pkr_ct_equal(const uint8_t *a, const uint8_t *b, size_t n) {
  uint8_t d = 0;
  for (size_t i = 0; i < n; i++) d |= a[i] ^ b[i];
  return d == 0;
}

void pkr_hkdf_sha256(const uint8_t *salt, size_t salt_len, const uint8_t *ikm, size_t ikm_len, const uint8_t *info,
                     size_t info_len, uint8_t *out, size_t out_len) {
  uint8_t prk[PKR_SHA256_LEN], block[PKR_SHA256_LEN];
  pkr_hmac_sha256(salt, salt_len, ikm, ikm_len, prk);  /* extract */
  size_t done = 0, prev = 0;
  for (uint8_t i = 1; done < out_len; i++) {           /* expand */
    pkr_hmac_ctx h;
    pkr_hmac_init(&h, prk, sizeof prk);
    pkr_hmac_update(&h, block, prev);
    pkr_hmac_update(&h, info, info_len);
    pkr_hmac_update(&h, &i, 1);
    pkr_hmac_final(&h, block);
    prev = sizeof block;
    size_t n = out_len - done < sizeof block ? out_len - done : sizeof block;
    memcpy(out + done, block, n);
    done += n;
  }
  memset(prk, 0, sizeof prk);
  memset(block, 0, sizeof block);
}

void pkr_derive_device_key(const uint8_t *root, size_t root_len, const char *device_id, unsigned kid,
                           uint8_t out[PKR_SHA256_LEN]) {
  char info[96];
  int n = snprintf(info, sizeof info, "pukaar-dev|%s|%u", device_id, kid);
  if (n < 0 || n >= (int)sizeof info) n = (int)sizeof info - 1;
  pkr_hkdf_sha256((const uint8_t *)PKR_HKDF_SALT, strlen(PKR_HKDF_SALT), root, root_len, (const uint8_t *)info,
                  (size_t)n, out, PKR_SHA256_LEN);
}

uint32_t pkr_crc32(uint32_t crc, const void *data, size_t len) {
  const uint8_t *p = (const uint8_t *)data;
  crc = ~crc;
  while (len--) {
    crc ^= *p++;
    for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
  }
  return ~crc;
}
