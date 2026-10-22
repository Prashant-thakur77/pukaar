// Pukaar village siren and loudspeaker node (spec 3.1, 6.2, 7.4): ESP32-S3 + SIM7670G (LilyGO
// T-SIM7670G-S3), E22-900T22S LoRa, DFPlayer Mini -> TPA3116 -> horns, a 12 V electronic siren,
// a strobe, three INA226 and an INMP441 microphone. firmware/README.md has the pin map.
//
// *** UNTESTED ON HARDWARE. *** It compiles for the ESP32-S3 (arduino-esp32 3.x); every decision
// it makes is in lib/pukaar_common/pkr_siren.cpp and tested on the host. Bench-test every pin,
// relay, current reading and the hardware max-on one-shots before a horn goes on a mast.
//
// Build -DPUKAAR_SIM=1 (env siren_node_sim) for Wokwi: no modem, no I2S, no INA226. MQTT, LoRa and
// SMS become lines on the serial port (see pukaar_hal.h), the tone is LEDC on the buzzer, and the
// amp current and the microphone are modelled from the relays. TEST ONLY keys are compiled in.
#include <Arduino.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <Wire.h>
#include <esp_task_wdt.h>

#include "pkr_box.h"
#include "pkr_codec.h"
#include "pkr_siren.h"
#include "pkr_wire.h"
#include "pukaar_hal.h"
#if PUKAAR_SIM
#include "pkr_test_keys.h"
#else
#include <ESP_I2S.h>
#endif

using namespace pkr;

// ---------------------------------------------------------------- pins (ESP32-S3 DevKitC bench kit;
// check them against the T-SIM7670G-S3's own pinout before use)
static const int PIN_MIC_SCK = 1, PIN_MIC_WS = 2, PIN_MIC_SD = 3;
static const int PIN_K2_HORNS = 4;   // K2: horns (on) or the 8 ohm dummy load (off)
static const int PIN_K1_AMP = 5;     // K1: 24 V boost + amp enable, through the hardware one-shot
static const int PIN_K3_SIREN = 6;   // K3: 12 V electronic siren, through the hardware one-shot
static const int PIN_K4_STROBE = 7;  // K4: strobe
static const int PIN_SDA = 8, PIN_SCL = 9;  // INA226 0x40 amp rail, 0x41 siren rail, 0x44 battery shunt
static const int PIN_MODEM_PWR = 10, PIN_MODEM_TX = 11, PIN_MODEM_RX = 12, PIN_MODEM_RST = 13;
static const int PIN_STATUS_LED = 14;
static const int PIN_TONE = 15;      // LEDC fallback tone -> RC low-pass -> amp IN (the buzzer in Wokwi)
static const int PIN_HOLD = 16;      // HOLD button to GND
static const int PIN_KEY_W = 17;     // key switch at W, to GND
static const int PIN_DOOR = 18;      // door switch: closed = GND, open = tamper
static const int PIN_KEY_C = 21;     // key switch at C, to GND
static const int PIN_E22_M0 = 38, PIN_E22_M1 = 39;
static const int PIN_ONESHOT_FEED = 40;  // pulse to re-trigger the 555 max-on timers of K1 and K3
static const int PIN_DF_TX = 41, PIN_DF_RX = 42;  // DFPlayer RX / TX
static const int PIN_TPL_DONE = 46;  // TPL5010 external watchdog DONE (a strapping pin: 10k pull-down)
static const int PIN_E22_TX = 47, PIN_E22_RX = 48;  // to E22 RXD / from E22 TXD

static const uint8_t RELAY_PIN[4] = {PIN_K1_AMP, PIN_K2_HORNS, PIN_K3_SIREN, PIN_K4_STROBE};

// ---------------------------------------------------------------- per-device settings
static const char* VILLAGE = "thunag";
static const char* IOT_ENDPOINT = "REPLACE-ats.iot.ap-south-1.amazonaws.com";  // make device-provision prints it
static const char* APN = "internet";
static const uint32_t HEARTBEAT_S = PKR_LIMIT_HEARTBEAT_S;

// ---------------------------------------------------------------- state
static NvsKv nvs;
static LittleFsFs flash;
static EspClock clk;
static Outbox outbox;
static EventLog evlog;
static KeyRing keys;
static DeviceConfig cfg;
static SirenSettings settings;
static FrameSigner signer;
static LoraLink lora;
static char device[48] = {0};
static SemaphoreHandle_t g_lock;
static uint32_t g_boot = 0;
#if PUKAAR_SIM
static SerialConsole console;
static SerialRadio radio;
static SerialLink cloud;
static SerialEventMirror mirror;
static bool sim_amp_open = false, sim_mic_dead = false;
static int sim_key = PKR_KEY_OFF, sim_hold = 0;
#else
static E22Radio radio;
static MqttLink cloud;
static HardwareSerial& DF = Serial2;
static HardwareSerial& E22 = Serial1;
static I2SClass mic;
#endif
static Uplink uplink;

// ---------------------------------------------------------------- the hardware behind SirenHal
#if !PUKAAR_SIM
static float ina_amps(uint8_t addr, float shunt_ohm) {
  Wire.beginTransmission(addr);
  Wire.write(0x01);  // shunt voltage, 2.5 uV per LSB
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom((int)addr, 2) != 2) return -1;
  int16_t raw = (int16_t)((Wire.read() << 8) | Wire.read());
  return (raw * 2.5e-6f) / shunt_ohm;
}

static void df_send(uint8_t cmd, uint16_t param) {
  uint8_t f[10];
  pkr_df_frame(cmd, param, 0, f);
  DF.write(f, sizeof f);
}

static bool df_alive() {  // query the number of files on the SD card; the reply proves the player works
  while (DF.available()) DF.read();
  uint8_t f[10];
  pkr_df_frame(PKR_DF_QUERY_FILES_SD, 0, 0, f);
  DF.write(f, sizeof f);
  uint8_t r[10];
  size_t n = 0;
  uint32_t t0 = millis();
  while (n < sizeof r && millis() - t0 < 300)
    if (DF.available()) r[n++] = (uint8_t)DF.read();
  uint8_t cmd;
  uint16_t param;
  return n == sizeof r && pkr_df_parse(r, &cmd, &param) == 0 && cmd == PKR_DF_QUERY_FILES_SD && param >= 11;
}
#endif

class NodeHal : public SirenHal {
 public:
  void relay(uint8_t k, bool on) override {
    digitalWrite(RELAY_PIN[k], on ? HIGH : LOW);
    rel[k] = on;
  }
  void tone(uint16_t hz, uint8_t vol, bool sweep) override {
    tone_on = hz != 0;
#if PUKAAR_SIM
    (void)sweep;
    (void)vol;
    if (hz) ledcWriteTone(PIN_TONE, hz);
    else ledcWriteTone(PIN_TONE, 0);
#else
    if (fallback || !hz) {
      ledcWriteTone(PIN_TONE, fallback ? hz : 0);
      if (!hz) df_send(PKR_DF_STOP, 0);
      return;
    }
    // DFPlayer folder 02: 001 = 650 Hz steady, 002 = the 500-1050 Hz sweep, 003 = 900 Hz, 004 = 1200 Hz
    uint16_t file = sweep ? 2 : hz == 900 ? 3 : hz == 1200 ? 4 : 1;
    if (file != playing) {
      df_send(PKR_DF_VOLUME, (uint16_t)(vol * 30 / 100));
      df_send(PKR_DF_PLAY_FOLDER_FILE, (uint16_t)(0x0200 | file));
      playing = file;
    }
#endif
  }
  void clip(uint8_t role, const char*, uint8_t vol) override {
    playing = 0;
#if PUKAAR_SIM
    Serial.printf("<CLIP %u\n", role);
    (void)vol;
#else
    // folder 01: 001 warning, 002 critical, 003 auto, 004 all-clear, 005 test, 006 drill, 007 drill end
    // (the village's own clips; the catalog's sha256 is checked by the silent test)
    df_send(PKR_DF_VOLUME, (uint16_t)(vol * 30 / 100));
    df_send(PKR_DF_PLAY_FOLDER_FILE, (uint16_t)(0x0100 | role));
#endif
  }
  void audio_off() override {
    tone_on = false;
    playing = 0;
    ledcWriteTone(PIN_TONE, 0);
#if !PUKAAR_SIM
    df_send(PKR_DF_STOP, 0);
#endif
  }
  void fallback_source(bool on) override { fallback = on; }
  void feed_oneshot() override {
    digitalWrite(PIN_ONESHOT_FEED, HIGH);
    delayMicroseconds(50);
    digitalWrite(PIN_ONESHOT_FEED, LOW);
  }
  float amp_a() override {
#if PUKAAR_SIM
    if (!rel[K1_AMP] || sim_amp_open) return 0.05f;
    return rel[K2_HORNS] ? 3.2f : 1.0f;  // full volume into the horns / 30 % into the dummy load
#else
    return ina_amps(0x40, 0.01f);
#endif
  }
  float siren_a() override {
#if PUKAAR_SIM
    return rel[K3_SIREN] ? 1.5f : 0.0f;
#else
    return ina_amps(0x41, 0.01f);
#endif
  }
  float mic_db() override {
#if PUKAAR_SIM
    return (rel[K1_AMP] && rel[K2_HORNS] && tone_on && !sim_amp_open) ? -14.0f : -40.0f;
#else
    int32_t buf[256];
    size_t n = mic.readBytes((char*)buf, sizeof buf) / sizeof buf[0];
    if (!n) return -120.0f;
    double sum = 0;
    for (size_t i = 0; i < n; i++) {
      double s = (double)(buf[i] >> 8) / 8388608.0;  // 24-bit sample in a 32-bit slot
      sum += s * s;
    }
    double rms = sqrt(sum / n);
    last_rms = rms;
    return rms > 0 ? (float)(20.0 * log10(rms)) : -120.0f;
#endif
  }
  bool mic_dead() override {
#if PUKAAR_SIM
    return sim_mic_dead;
#else
    return last_rms == 0.0;  // a stuck-at-zero I2S line: no noise floor at all
#endif
  }
  uint16_t selftest_faults() override {
    uint16_t f = 0;
#if PUKAAR_SIM
    if (!cloud.connected()) f |= FAULT_MODEM;
#else
    if (!df_alive()) f |= FAULT_DFPLAYER | FAULT_CATALOG;
    if (!cloud.connected()) f |= FAULT_MODEM;
    for (uint8_t a : {0x40, 0x41, 0x44}) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() != 0) f |= FAULT_INA226;
    }
#endif
    return f;
  }
  bool rel[4] = {false, false, false, false};
  bool tone_on = false, fallback = false;
  uint16_t playing = 0;
  double last_rms = 1.0;
};

static NodeHal hal;

class LoraPort : public FramePort {
 public:
  bool send(uint8_t type, uint16_t dst, const uint8_t* p, uint8_t len) override {
    return lora.send(type, dst, p, len, clk.unix_s(), clk.synced());
  }
};
static LoraPort lora_port;

class SmsOut : public SmsPort {
 public:
  void send(const char* to, const char* text) override {
    if (to) {
      cloud.sms(to, text);
      return;
    }
    // the officers' and the pradhan's numbers are provisioned in NVS (sms_to0..3), never in a shadow
    Preferences p;
    if (!p.begin("pkr-keys", true)) return;
    for (int i = 0; i < 4; i++) {
      char k[8];
      snprintf(k, sizeof k, "sms_to%d", i);
      String n = p.getString(k, "");
      if (n.length()) cloud.sms(n.c_str(), text);
    }
    p.end();
#if PUKAAR_SIM
    cloud.sms(nullptr, text);
#endif
  }
};
static SmsOut sms_out;

static SirenCore core(hal, clk, nvs, keys, evlog, &sms_out, &lora_port);

// ---------------------------------------------------------------- cloud messages
static char t_shadow_delta[128], t_shadow_get_acc[128], t_cfg_delta[128], t_cfg_get_acc[128];
static char t_shadow_update[128], t_jobs_notify[128];

static void report_state() {
  char body[400];
  snprintf(body, sizeof body,
           "{\"state\":{\"reported\":{\"cmd_id\":\"%s\",\"state\":\"%s\",\"since\":%lu,\"last_ctr\":%lu,\"kid\":%u,"
           "\"fw\":\"%s\",\"clips\":\"%s\",\"faults\":%u}}}",
           core.order().cmd_id, pkr_state_name(core.state()), (unsigned long)clk.unix_s(), (unsigned long)core.last_cmd_ctr(),
           keys.current_kid(), PUKAAR_FW, cfg.catalog, core.faults());
  cloud.publish(t_shadow_update, body, strlen(body));
}

static void on_message(const char* topic, const char* payload, size_t len) {
  xSemaphoreTake(g_lock, portMAX_DELAY);
  core.cloud_contact();
  if (!strcmp(topic, t_shadow_delta) || !strcmp(topic, t_shadow_get_acc)) {
    pkr_cmd_t c;
    if (parse_cmd_json(payload, len, &c) == 0) core.accept_command(c, PKR_VIA_MQTT);
    xSemaphoreGive(g_lock);
    report_state();
    return;
  }
  if (!strcmp(topic, t_cfg_delta) || !strcmp(topic, t_cfg_get_acc)) {
    if (parse_config_json(payload, len, &cfg) == 0) {
      core.configure(cfg, settings);
      File f = LittleFS.open("/config.json", "w");  // the last good config survives a reboot
      if (f) {
        f.write((const uint8_t*)payload, len);
        f.close();
      }
      Event e;
      e.type = PKR_EVT_CONFIG_APPLIED;
      e.at = clk.unix_s();
      evlog.emit(e);
    }
  }
  xSemaphoreGive(g_lock);
}

static void on_connect() {
  // never rely on queued QoS 1 messages: get both shadows and the next job on every connect
  char t[128];
  shadow_topic(t, sizeof t, device, "siren", "get");
  cloud.publish(t, "{}", 2);
  shadow_topic(t, sizeof t, device, "config", "get");
  cloud.publish(t, "{}", 2);
  snprintf(t, sizeof t, "$aws/things/%s/jobs/start-next", device);
  cloud.publish(t, "{}", 2);
  xSemaphoreTake(g_lock, portMAX_DELAY);
  core.set_cloud_link(true);
  xSemaphoreGive(g_lock);
#if !PUKAAR_SIM
  if (!clk.synced()) clk.sync_ntp(5000);
#endif
}

static void on_sms(const char* from, const char* text) {
  xSemaphoreTake(g_lock, portMAX_DELAY);
  core.on_sms(from, text, strlen(text));
  xSemaphoreGive(g_lock);
}

// ---------------------------------------------------------------- the alarm task (highest priority)
static void alarm_task(void*) {
  esp_task_wdt_add(nullptr);
  uint32_t last_tpl = 0;
  for (;;) {
    xSemaphoreTake(g_lock, portMAX_DELAY);
#if PUKAAR_SIM
    uint8_t key = (uint8_t)sim_key;
    bool hold = sim_hold || digitalRead(PIN_HOLD) == LOW;
    if (digitalRead(PIN_KEY_C) == LOW) key = PKR_KEY_CRITICAL;
    else if (digitalRead(PIN_KEY_W) == LOW) key = PKR_KEY_WARNING;
#else
    uint8_t key = digitalRead(PIN_KEY_C) == LOW ? PKR_KEY_CRITICAL : digitalRead(PIN_KEY_W) == LOW ? PKR_KEY_WARNING : PKR_KEY_OFF;
    bool hold = digitalRead(PIN_HOLD) == LOW;
#endif
    core.set_key(key);
    core.set_hold(hold);
    core.set_door(digitalRead(PIN_DOOR) == HIGH);
    core.tick();
    digitalWrite(PIN_STATUS_LED, (millis() / (core.order().active ? 150 : 1000)) % 2);
    xSemaphoreGive(g_lock);
    if (millis() - last_tpl > 10000) {  // TPL5010 DONE pulse: it resets the S3 if not fed for 60 s
      digitalWrite(PIN_TPL_DONE, HIGH);
      delayMicroseconds(100);
      digitalWrite(PIN_TPL_DONE, LOW);
      last_tpl = millis();
    }
    esp_task_wdt_reset();
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

// ---------------------------------------------------------------- setup and the comms loop
static void load_keys() {
#if PUKAAR_SIM
  // *** TEST ONLY KEYS *** (pkr_test_keys.h): the simulator is a public, labelled fake
  strcpy(device, PKR_SIM_SIREN);
  keys.set_identity(PKR_SIM_SIREN, PKR_SIM_SIREN_ADDR);
  uint8_t k[32];
  pkr_test_only_device_key(PKR_SIM_SIREN, 1, k);
  keys.set_self_key(1, k);
  keys.set_current_kid(1);
  const char* senders[2] = {PKR_SIM_GAUGE, PKR_SIM_BOX};
  const uint8_t roles[2] = {ROLE_GAUGE_STATUS | ROLE_GAUGE_ALARM | ROLE_RELAY_CMD,
                            ROLE_BUTTON | ROLE_HEARTBEAT | ROLE_RELAY_CMD};
  for (int i = 0; i < 2; i++) {
    Sender s;
    s.addr = pkr_sim_addr(senders[i]);
    strncpy(s.device, senders[i], sizeof s.device - 1);
    s.kid = 1;
    s.roles = roles[i];
    pkr_test_only_device_key(senders[i], 1, s.key);
    keys.add_sender(s);
  }
  strcpy(settings.sms_salt, PKR_SIM_SMS_SALT);
  pkr_sms_sender_hash(PKR_SIM_SMS_SALT, PKR_SIM_OFFICER_E164, cfg.sms_allow[0]);
  cfg.n_sms_allow = 1;
  settings.simulated = true;
#else
  load_provisioned_keys(keys, device, sizeof device);
  Preferences p;
  if (p.begin("pkr-keys", true)) {
    strncpy(settings.sms_salt, p.getString("sms_salt", "").c_str(), sizeof settings.sms_salt - 1);
    p.end();
  }
#endif
}

static void load_config() {
  File f = LittleFS.open("/config.json", "r");
  if (!f) return;
  String s = f.readString();
  f.close();
  parse_config_json(s.c_str(), s.length(), &cfg);
}

void setup() {
  for (int k = 0; k < 4; k++) {  // reset means silent: every relay input is pulled down too
    pinMode(RELAY_PIN[k], OUTPUT);
    digitalWrite(RELAY_PIN[k], LOW);
  }
  pinMode(PIN_ONESHOT_FEED, OUTPUT);
  pinMode(PIN_TPL_DONE, OUTPUT);
  pinMode(PIN_STATUS_LED, OUTPUT);
  pinMode(PIN_HOLD, INPUT_PULLUP);
  pinMode(PIN_KEY_W, INPUT_PULLUP);
  pinMode(PIN_KEY_C, INPUT_PULLUP);
  pinMode(PIN_DOOR, INPUT_PULLUP);
  ledcAttach(PIN_TONE, 1000, 8);
  Serial.begin(115200);

  esp_task_wdt_config_t wdt = {30000, 0, true};  // 30 s task watchdog, panic -> reset
  esp_task_wdt_reconfigure(&wdt);
  esp_task_wdt_add(nullptr);

  g_lock = xSemaphoreCreateMutex();
  nvs.begin("pukaar");
  g_boot = next_boot_number(nvs);
  flash.begin();
  outbox.begin(&flash);
  strcpy(settings.village, VILLAGE);
  load_keys();
  load_config();
#if PUKAAR_SIM
  evlog.begin(&outbox, g_boot, &mirror);
#else
  evlog.begin(&outbox, g_boot);
  Wire.begin(PIN_SDA, PIN_SCL);
  mic.setPins(PIN_MIC_SCK, PIN_MIC_WS, -1, PIN_MIC_SD);
  mic.begin(I2S_MODE_STD, 16000, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT);
  DF.begin(9600, SERIAL_8N1, PIN_DF_RX, PIN_DF_TX);
  radio.begin(E22, PIN_E22_RX, PIN_E22_TX, PIN_E22_M0, PIN_E22_M1, keys.addr(), cfg.lora_freq_hz);
#endif
  signer.begin(&keys, &nvs);
  lora.begin(&radio, &signer, PKR_DUTY_NODE_BUDGET_MS);
  core.configure(cfg, settings);
  core.begin();

  shadow_topic(t_shadow_delta, sizeof t_shadow_delta, device, "siren", "update/delta");
  shadow_topic(t_shadow_get_acc, sizeof t_shadow_get_acc, device, "siren", "get/accepted");
  shadow_topic(t_cfg_delta, sizeof t_cfg_delta, device, "config", "update/delta");
  shadow_topic(t_cfg_get_acc, sizeof t_cfg_get_acc, device, "config", "get/accepted");
  shadow_topic(t_shadow_update, sizeof t_shadow_update, device, "siren", "update");
  snprintf(t_jobs_notify, sizeof t_jobs_notify, "$aws/things/%s/jobs/notify-next", device);
  cloud.on_message(on_message);
  cloud.on_connect(on_connect);
  cloud.subscribe(t_shadow_delta);
  cloud.subscribe(t_shadow_get_acc);
  cloud.subscribe(t_cfg_delta);
  cloud.subscribe(t_cfg_get_acc);
  cloud.subscribe(t_jobs_notify);
#if !PUKAAR_SIM
  cloud.begin(device, IOT_ENDPOINT, APN, MqttLink::Pins{PIN_MODEM_TX, PIN_MODEM_RX, PIN_MODEM_RST, PIN_MODEM_PWR});
#endif
  uplink.begin(&outbox, &cloud, "siren", VILLAGE, device);
  xTaskCreatePinnedToCore(alarm_task, "alarm", 8192, nullptr, configMAX_PRIORITIES - 2, nullptr, 1);
#if PUKAAR_SIM
  Serial.println("READY");
#endif
}

#if PUKAAR_SIM
static void sim_line(const char* l) {
  if (!strncmp(l, ">CMD ", 5)) {
    pkr_cmd_t c;
    int r = parse_cmd_json(l + 5, strlen(l + 5), &c);
    xSemaphoreTake(g_lock, portMAX_DELAY);
    core.cloud_contact();
    if (r == 0) core.accept_command(c, PKR_VIA_MQTT);
    else Serial.println("<ERR bad_format");
    xSemaphoreGive(g_lock);
  } else if (!strncmp(l, ">CFG ", 5)) {
    on_message(t_cfg_delta, l + 5, strlen(l + 5));
  } else if (!strncmp(l, ">LORA ", 6)) {
    radio.inject(l + 6);
  } else if (!strncmp(l, ">SMS ", 5)) {
    const char* sp = strchr(l + 5, ' ');
    if (sp) {
      char from[24] = {0};
      strncpy(from, l + 5, (size_t)(sp - (l + 5)) < sizeof from - 1 ? (size_t)(sp - (l + 5)) : sizeof from - 1);
      on_sms(from, sp + 1);
    }
  } else if (!strncmp(l, ">TIME ", 6)) {
    clk.set((uint32_t)strtoul(l + 6, nullptr, 10));
  } else if (!strncmp(l, ">CLOUD ", 7)) {
    bool up = !strcmp(l + 7, "up");
    cloud.set_up(up);
    xSemaphoreTake(g_lock, portMAX_DELAY);
    core.set_cloud_link(up);
    xSemaphoreGive(g_lock);
  } else if (!strncmp(l, ">FAULT ", 7)) {
    sim_amp_open = !strcmp(l + 7, "amp_open");
    sim_mic_dead = !strcmp(l + 7, "mic_dead");
  } else if (!strcmp(l, ">TEST silent")) {
    xSemaphoreTake(g_lock, portMAX_DELAY);
    core.run_silent_test();
    xSemaphoreGive(g_lock);
  } else if (!strncmp(l, ">SOC ", 5)) {
    xSemaphoreTake(g_lock, portMAX_DELAY);
    core.set_soc((uint8_t)atoi(l + 5));
    xSemaphoreGive(g_lock);
  } else if (!strncmp(l, ">KEY ", 5)) {
    sim_key = l[5] == 'c' ? PKR_KEY_CRITICAL : l[5] == 'w' ? PKR_KEY_WARNING : PKR_KEY_OFF;
  } else if (!strncmp(l, ">HOLD ", 6)) {
    sim_hold = atoi(l + 6);
  }
}
#endif

void loop() {
  static uint32_t last_hb = 0;
#if PUKAAR_SIM
  if (const char* l = console.poll()) sim_line(l);
#endif
  uint8_t frame[PKR_FRAME_MAX_LEN];
  size_t n = radio.receive(frame, sizeof frame);
  if (n) {
    xSemaphoreTake(g_lock, portMAX_DELAY);
    core.on_lora(frame, n);
    xSemaphoreGive(g_lock);
  }
#if !PUKAAR_SIM
  static uint32_t last_soc = 0;
  if (millis() - last_soc > 60000 || !last_soc) {
    // SoC from the battery INA226's bus voltage (1.25 mV/LSB): a rough LiFePO4 rest-voltage map.
    // The spec wants coulomb counting on this shunt; voltage is the fallback it names. Bench item.
    last_soc = millis() | 1;
    Wire.beginTransmission(0x44);
    Wire.write(0x02);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom(0x44, 2) == 2) {
      float v = ((Wire.read() << 8) | Wire.read()) * 1.25e-3f;
      int soc = v >= 13.4f ? 100 : v <= 12.0f ? 0 : (int)((v - 12.0f) / 1.4f * 100.0f);
      xSemaphoreTake(g_lock, portMAX_DELAY);
      core.set_soc((uint8_t)soc);
      xSemaphoreGive(g_lock);
    }
  }
#endif
  cloud.loop();
  cloud.poll_sms(on_sms);
  uplink.loop(clk.unix_s());
  uint32_t hb = core.tier() >= PKR_TIER_NO_AUDIBLE_TESTS ? PKR_LIMIT_HEARTBEAT_LOW_SOC_S : HEARTBEAT_S;
  if (millis() - last_hb >= hb * 1000u || !last_hb) {
    last_hb = millis() | 1;
    Heartbeat h;
    h.at = clk.unix_s();
    h.boot = g_boot;
    h.state = core.state();
    h.fw = PUKAAR_FW;
    h.clips = cfg.catalog;
    h.faults = core.faults();
    h.outbox_depth = outbox.depth();
    h.uptime_s = millis() / 1000;
    h.rssi = cloud.rssi();
    h.simulated = settings.simulated;
    char body[512];
    size_t len = heartbeat_to_json(h, body, sizeof body);
    char topic[128];
    snprintf(topic, sizeof topic, "pukaar/siren/%s/%s/heartbeat", VILLAGE, device);
    if (len && cloud.connected()) cloud.publish(topic, body, len);
  }
  esp_task_wdt_reset();
  delay(5);
}
