// SHA-256 (FIPS 180-4 examples), HMAC-SHA256 (RFC 4231), CRC-32 and the text encodings.
#include <string.h>
#include <unity.h>

#include <string>

#include "pkr_codec.h"
#include "pkr_crypto.h"

void setUp() {}
void tearDown() {}

static std::string hex(const uint8_t* b, size_t n) {
  char out[129];
  pkr_hex_encode(b, n, out);
  return out;
}

static std::string sha(const std::string& s) {
  uint8_t h[32];
  pkr_sha256(s.data(), s.size(), h);
  return hex(h, 32);
}

static std::string hmac(const std::string& k, const std::string& m) {
  uint8_t h[32];
  pkr_hmac_sha256((const uint8_t*)k.data(), k.size(), m.data(), m.size(), h);
  return hex(h, 32);
}

static void test_sha256_fips_examples() {
  TEST_ASSERT_EQUAL_STRING("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", sha("").c_str());
  TEST_ASSERT_EQUAL_STRING("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", sha("abc").c_str());
  TEST_ASSERT_EQUAL_STRING("248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
                           sha("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq").c_str());
  // a million 'a', fed in uneven pieces to exercise the block buffer
  pkr_sha256_ctx c;
  pkr_sha256_init(&c);
  std::string chunk(997, 'a');
  size_t left = 1000000;
  while (left) {
    size_t n = left < chunk.size() ? left : chunk.size();
    pkr_sha256_update(&c, chunk.data(), n);
    left -= n;
  }
  uint8_t h[32];
  pkr_sha256_final(&c, h);
  TEST_ASSERT_EQUAL_STRING("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0", hex(h, 32).c_str());
}

static void test_hmac_rfc4231() {
  // case 1
  TEST_ASSERT_EQUAL_STRING("b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7",
                           hmac(std::string(20, '\x0b'), "Hi There").c_str());
  // case 2
  TEST_ASSERT_EQUAL_STRING("5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843",
                           hmac("Jefe", "what do ya want for nothing?").c_str());
  // case 3
  TEST_ASSERT_EQUAL_STRING("773ea91e36800e46854db8ebd09181a72959098b3ef8c122d9635514ced565fe",
                           hmac(std::string(20, '\xaa'), std::string(50, '\xdd')).c_str());
  // case 6: a key longer than the block is hashed first
  TEST_ASSERT_EQUAL_STRING("60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54",
                           hmac(std::string(131, '\xaa'), "Test Using Larger Than Block-Size Key - Hash Key First").c_str());
  // case 7
  TEST_ASSERT_EQUAL_STRING(
      "9b09ffa71b942fcb27635fbcd5b0e944bfdc63644f0713938a7f51535c3a35e2",
      hmac(std::string(131, '\xaa'),
           "This is a test using a larger than block-size key and a larger than block-size data. The key needs to be "
           "hashed before being used by the HMAC algorithm.")
          .c_str());
}

static void test_ct_equal_and_crc32() {
  uint8_t a[4] = {1, 2, 3, 4}, b[4] = {1, 2, 3, 5};
  TEST_ASSERT_TRUE(pkr_ct_equal(a, a, 4));
  TEST_ASSERT_FALSE(pkr_ct_equal(a, b, 4));
  TEST_ASSERT_EQUAL_HEX32(0xCBF43926u, pkr_crc32(0, "123456789", 9));
  // incremental equals one-shot
  uint32_t c = pkr_crc32(0, "1234", 4);
  TEST_ASSERT_EQUAL_HEX32(0xCBF43926u, pkr_crc32(c, "56789", 5));
}

static void test_hkdf_rfc5869_and_device_keys() {
  // RFC 5869 test case 1
  uint8_t ikm[22], salt[13], info[10], okm[42];
  memset(ikm, 0x0b, sizeof ikm);
  for (int i = 0; i < 13; i++) salt[i] = (uint8_t)i;
  for (int i = 0; i < 10; i++) info[i] = (uint8_t)(0xf0 + i);
  pkr_hkdf_sha256(salt, sizeof salt, ikm, sizeof ikm, info, sizeof info, okm, sizeof okm);
  TEST_ASSERT_EQUAL_STRING("3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865",
                           hex(okm, 42).c_str());
  // the device key as the cloud derives it (the golden vectors' TEST ONLY root 0x00..0x1f)
  uint8_t root[32], k1[32], k2[32];
  for (int i = 0; i < 32; i++) root[i] = (uint8_t)i;
  pkr_derive_device_key(root, 32, "siren-thunag-01", 1, k1);
  TEST_ASSERT_EQUAL_STRING("3cb168a61a49dcd3df007c72427c577f45ac98ed6c615b9d1865a4a1521c0c62", hex(k1, 32).c_str());
  pkr_derive_device_key(root, 32, "siren-thunag-01", 2, k2);
  TEST_ASSERT_FALSE(pkr_ct_equal(k1, k2, 32));  // a kid bump is a new key
}

static void test_base64url_round_trip_and_padding() {
  for (size_t n = 0; n <= 40; n++) {
    uint8_t in[40], back[42];
    for (size_t i = 0; i < n; i++) in[i] = (uint8_t)(i * 37 + 11);
    char enc[80];
    size_t m = pkr_b64url_encode(in, n, enc, sizeof enc);
    TEST_ASSERT_NULL(strchr(enc, '='));
    TEST_ASSERT_NULL(strchr(enc, '+'));
    TEST_ASSERT_NULL(strchr(enc, '/'));
    TEST_ASSERT_EQUAL_INT((int)n, pkr_b64url_decode(enc, m, back, sizeof back));
    if (n) TEST_ASSERT_EQUAL_MEMORY(in, back, n);
  }
  uint8_t out[8];
  TEST_ASSERT_EQUAL_INT(2, pkr_b64url_decode("_-8=", 4, out, sizeof out));  // padding tolerated
  TEST_ASSERT_EQUAL_INT(-1, pkr_b64url_decode("a*b=", 4, out, sizeof out));
  TEST_ASSERT_EQUAL_INT(-1, pkr_b64url_decode("_-9", 3, out, sizeof out));  // non-zero trailing bits
  char std64[16];
  const uint8_t three[] = {0xfb, 0xff};
  pkr_b64_encode(three, 2, std64, sizeof std64);
  TEST_ASSERT_EQUAL_STRING("+/8=", std64);
}

static void test_crockford_base32() {
  uint8_t ten[10] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9}, back[12];
  char enc[20];
  TEST_ASSERT_EQUAL_UINT(16, pkr_b32c_encode(ten, 10, enc, sizeof enc));
  TEST_ASSERT_EQUAL_STRING("000G40R40M30E209", enc);
  TEST_ASSERT_EQUAL_INT(10, pkr_b32c_decode(enc, 16, back, sizeof back));
  TEST_ASSERT_EQUAL_MEMORY(ten, back, 10);
  // case-insensitive, I/L read as 1 and O as 0 (what a person retyping it gets wrong)
  TEST_ASSERT_EQUAL_INT(10, pkr_b32c_decode("ooog40r40m30e2o9", 16, back, sizeof back));
  TEST_ASSERT_EQUAL_MEMORY(ten, back, 10);
  TEST_ASSERT_EQUAL_INT(-1, pkr_b32c_decode("000G40R40M30E20U", 16, back, sizeof back));  // U is not in the alphabet
  // the spec's example signature is valid Crockford base32 (it is not RFC 4648: it has 1, 8, 9)
  TEST_ASSERT_EQUAL_INT(10, pkr_b32c_decode("7K2QM9XA4D1F8HTP", 16, back, sizeof back));
}

static void test_base36() {
  char out[10];
  uint32_t v;
  pkr_b36_encode(0, out, sizeof out);
  TEST_ASSERT_EQUAL_STRING("0", out);
  pkr_b36_encode(1761123600u, out, sizeof out);
  TEST_ASSERT_EQUAL_INT(0, pkr_b36_decode(out, strlen(out), &v));
  TEST_ASSERT_EQUAL_UINT32(1761123600u, v);
  TEST_ASSERT_EQUAL_INT(0, pkr_b36_decode("tj8k2q", 6, &v));  // lower case accepted
  uint32_t w;
  TEST_ASSERT_EQUAL_INT(0, pkr_b36_decode("TJ8K2Q", 6, &w));
  TEST_ASSERT_EQUAL_UINT32(v, w);
  pkr_b36_encode(0xFFFFFFFFu, out, sizeof out);
  TEST_ASSERT_EQUAL_STRING("1Z141Z3", out);
  TEST_ASSERT_EQUAL_INT(-1, pkr_b36_decode("1Z141Z4", 7, &v));  // overflow
  TEST_ASSERT_EQUAL_INT(-1, pkr_b36_decode("AB-C", 4, &v));
  TEST_ASSERT_EQUAL_INT(-1, pkr_b36_decode("", 0, &v));
}

static void test_hex() {
  uint8_t b[4];
  TEST_ASSERT_EQUAL_INT(4, pkr_hex_decode("DEADbeef", b, 4));
  TEST_ASSERT_EQUAL_HEX8(0xEF, b[3]);
  TEST_ASSERT_EQUAL_INT(-1, pkr_hex_decode("abc", b, 4));
  TEST_ASSERT_EQUAL_INT(-1, pkr_hex_decode("zz", b, 4));
  TEST_ASSERT_EQUAL_INT(-1, pkr_hex_decode("0011223344", b, 4));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_sha256_fips_examples);
  RUN_TEST(test_hmac_rfc4231);
  RUN_TEST(test_ct_equal_and_crc32);
  RUN_TEST(test_hkdf_rfc5869_and_device_keys);
  RUN_TEST(test_base64url_round_trip_and_padding);
  RUN_TEST(test_crockford_base32);
  RUN_TEST(test_base36);
  RUN_TEST(test_hex);
  return UNITY_END();
}
