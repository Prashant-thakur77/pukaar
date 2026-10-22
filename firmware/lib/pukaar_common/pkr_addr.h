// LoRa address of a device id. The registry may set `lora_addr` explicitly; by default both
// ends compute it the same way: the first two bytes (little-endian) of SHA-256(device id),
// skipping 0x0000 and 0xFFFF (broadcast). Check for collisions within a district at provisioning.
#pragma once

#include <stdint.h>
#include <string.h>

#include "pkr_crypto.h"

static inline uint16_t pkr_lora_addr(const char* device) {
  uint8_t h[PKR_SHA256_LEN];
  pkr_sha256(device, strlen(device), h);
  uint16_t a = (uint16_t)(h[0] | (h[1] << 8));
  if (a == 0x0000 || a == 0xFFFF) a = (uint16_t)(((h[2] | (h[3] << 8)) & 0x7FFF) | 1);
  return a;
}
