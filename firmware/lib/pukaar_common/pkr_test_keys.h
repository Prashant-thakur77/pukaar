// *** TEST ONLY KEYS. NEVER FLASH THESE TO A REAL DEVICE. ***
//
// The host tests and the Wokwi simulator builds (*_sim envs) derive device keys from a public,
// made-up root: the bytes 0x00..0x1f, the same TEST ONLY root as the golden vectors in
// test/vectors/protocol_vectors.json. They derive exactly as the cloud does from its real root
// (HKDF-SHA256, pkr_derive_device_key). Anyone can read this file, so anything signed with these
// keys proves nothing. A real device is provisioned with its own K_dev and the sender keys it
// trusts; it never sees a root key, test or real.
#pragma once

#include <stdint.h>
#include <string.h>

#include "pkr_addr.h"
#include "pkr_crypto.h"

static inline void pkr_test_only_root(uint8_t root[32]) {
  for (int i = 0; i < 32; i++) root[i] = (uint8_t)i;
}

static inline void pkr_test_only_device_key(const char* device, unsigned kid, uint8_t out[32]) {
  uint8_t root[32];
  pkr_test_only_root(root);
  pkr_derive_device_key(root, sizeof root, device, kid, out);
}

// The simulated devices, as seeded in data/villages.json (siren and box) and the vectors' layout.
#define PKR_SIM_VILLAGE "thunag"
#define PKR_SIM_SIREN "siren-thunag-sim"
#define PKR_SIM_GAUGE "gauge-janjehli-sim"
#define PKR_SIM_BOX "box-thunag-sim"
#define PKR_SIM_RELAY "relay-thunag-sim"
#define PKR_SIM_SIREN_ADDR 0x0101
#define PKR_SIM_BOX_ADDR 0x0102
#define PKR_SIM_GAUGE_ADDR 0x0201
#define PKR_SIM_RELAY_ADDR 0x0301
#define PKR_SIM_SMS_SALT "TEST-ONLY-SALT"
#define PKR_SIM_OFFICER_E164 "+910000000001"  // not a real number

// LoRa address of a simulated device (the registry's lora_addr), else the hash default.
static inline uint16_t pkr_sim_addr(const char* device) {
  if (!strcmp(device, PKR_SIM_SIREN)) return PKR_SIM_SIREN_ADDR;
  if (!strcmp(device, PKR_SIM_BOX)) return PKR_SIM_BOX_ADDR;
  if (!strcmp(device, PKR_SIM_GAUGE)) return PKR_SIM_GAUGE_ADDR;
  if (!strcmp(device, PKR_SIM_RELAY)) return PKR_SIM_RELAY_ADDR;
  return pkr_lora_addr(device);
}
