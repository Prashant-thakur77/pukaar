/* SHA-256 and HMAC-SHA256 (FIPS 180-4, RFC 2104), portable C99.
 *
 * The same code runs on the host tests and on the ESP32, so the bytes the tests check are the
 * bytes a device computes. (The spec suggests mbedTLS on the device; it would work too, but one
 * implementation everywhere is one less thing to bench-verify.) Written fresh for Pukaar. */
#ifndef PKR_CRYPTO_H
#define PKR_CRYPTO_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PKR_SHA256_LEN 32

typedef struct {
  uint32_t h[8];
  uint64_t total;
  uint8_t buf[64];
  size_t used;
} pkr_sha256_ctx;

void pkr_sha256_init(pkr_sha256_ctx *c);
void pkr_sha256_update(pkr_sha256_ctx *c, const void *data, size_t len);
void pkr_sha256_final(pkr_sha256_ctx *c, uint8_t out[PKR_SHA256_LEN]);
void pkr_sha256(const void *data, size_t len, uint8_t out[PKR_SHA256_LEN]);

typedef struct {
  pkr_sha256_ctx inner;
  pkr_sha256_ctx outer;
} pkr_hmac_ctx;

void pkr_hmac_init(pkr_hmac_ctx *c, const uint8_t *key, size_t key_len);
void pkr_hmac_update(pkr_hmac_ctx *c, const void *data, size_t len);
void pkr_hmac_final(pkr_hmac_ctx *c, uint8_t out[PKR_SHA256_LEN]);
void pkr_hmac_sha256(const uint8_t *key, size_t key_len, const void *data, size_t len,
                     uint8_t out[PKR_SHA256_LEN]);

/* Constant-time compare of n bytes: 1 if equal. */
int pkr_ct_equal(const uint8_t *a, const uint8_t *b, size_t n);

/* RFC 5869 HKDF-SHA256 (extract then expand). */
void pkr_hkdf_sha256(const uint8_t *salt, size_t salt_len, const uint8_t *ikm, size_t ikm_len, const uint8_t *info,
                     size_t info_len, uint8_t *out, size_t out_len);

/* Device key as the cloud derives it (backend services/devices/protocol.py, DESIGN-S):
 *   K_dev,kid = HKDF-SHA256(ikm=root, salt="pukaar-device-root-v1", info="pukaar-dev|<device>|<kid>", L=32)
 * (The spec's KMS GenerateMac form is the documented production upgrade.) Only the tests and the
 * TEST ONLY simulator builds use this: a real device never holds the root, it is flashed its
 * own K_dev and the sender keys it trusts. */
#define PKR_HKDF_SALT "pukaar-device-root-v1"
void pkr_derive_device_key(const uint8_t *root, size_t root_len, const char *device_id, unsigned kid,
                           uint8_t out[PKR_SHA256_LEN]);

/* CRC-32 (IEEE 802.3, reflected 0xEDB88320), for outbox records. */
uint32_t pkr_crc32(uint32_t crc, const void *data, size_t len);

#ifdef __cplusplus
}
#endif
#endif
