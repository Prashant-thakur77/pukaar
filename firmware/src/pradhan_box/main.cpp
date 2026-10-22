// Pukaar pradhan box (spec 3.3, 7.2): the pradhan's indoor receiver and guarded manual trigger.
// LilyGO T-SIM7670G-S3 (ESP32-S3 + SIM7670G), an E22-900T22S, a MAX98357A I2S amp and a 3 W speaker,
// four level LEDs and a link LED, buttons A (water rising), B (mil gaya), C (HOLD, with the key) and D
// (stop), and a two-position key switch (Warning / Critical).
//
// *** UNTESTED ON HARDWARE. *** It compiles for the ESP32-S3 (arduino-esp32 3.x). The decisions are in
// lib/pukaar_common/pkr_box.cpp (BoxCore: the 3 s hold, the LoRa ACK wait and retries, the SMS when
// both links fail, the rate limit, the shadow, the relay_cmd forwarding, the mesh batch) and tested on
// the host. Bench-check every pin, the speaker level and the LoRa ACK path against a real siren.
//
// What it does, always on:
//   - the box shadow `siren` (desired.level, alert_id, clip, relay_cmd): the level LEDs, the clip
//     indoors (a chime only at Watch), and each relay_cmd sent once on LoRa to its siren;
//   - key + C held 3 s: a LoRa BUTTON to the village's sirens, waiting 2 s for an ACK (3 tries), then the
//     manual_trigger event (lora_acked tells the cloud whether to command the sirens itself); with no
//     LoRa ACK and no cloud, an SMS to the officers ("PKR MANUAL C thunag 14:03");
//   - A: a `report` event; B: an `ack` event for the alert the box shows; D: a LoRa stop;
//   - every LoRa frame it hears goes to the cloud (pukaar/mesh/<village>/<box>/relay), where each inner
//     MAC is checked with the origin's key;
//   - events through the durable outbox, a heartbeat every 5 minutes.
#include <Arduino.h>
#include <ESP_I2S.h>
#include <LittleFS.h>
#include <esp_task_wdt.h>

#include "pkr_box.h"
#include "pkr_node.h"
#include "pkr_pattern.h"
#include "pukaar_hal.h"

using namespace pkr;

#ifndef PUKAAR_FW
#define PUKAAR_FW "pukaar-box-0.1.0"
#endif

// ---------------------------------------------------------------- pins (check against the T-SIM7670G-S3)
static const int PIN_I2S_BCLK = 1, PIN_I2S_LRC = 2, PIN_I2S_DOUT = 3;  // MAX98357A
static const int PIN_LED[4] = {4, 5, 6, 7};  // green (normal), yellow (watch), orange (warning), red (critical)
static const int PIN_KEY_W = 8, PIN_KEY_C = 9;  // key switch to GND
static const int PIN_MODEM_PWR = 10, PIN_MODEM_TX = 11, PIN_MODEM_RX = 12, PIN_MODEM_RST = 13;
static const int PIN_BTN_D = 14;                // stop
static const int PIN_LINK_R = 15, PIN_LINK_G = 16;  // bicolour link LED (both = amber)
static const int PIN_BTN_A = 17, PIN_BTN_B = 18, PIN_BTN_C = 21;  // water rising, mil gaya, HOLD
static const int PIN_E22_M0 = 38, PIN_E22_M1 = 39;
static const int PIN_E22_TX = 47, PIN_E22_RX = 48;
static const int BTN_PIN[4] = {PIN_BTN_A, PIN_BTN_B, PIN_BTN_C, PIN_BTN_D};  // BoxButton order

// ---------------------------------------------------------------- state
static NodeSettings settings;
static NvsKv nvs;
static LittleFsFs flash;
static EspClock clk;
static Outbox outbox;
static EventLog evlog;
static KeyRing keys;
static FrameSigner signer;
static FrameReceiver receiver;
static LoraLink lora;
static MeshBatch mesh;
static E22Radio radio;
static MqttLink cloud;
static Uplink uplink;
static HardwareSerial& E22 = Serial1;
static I2SClass i2s;
static QueueHandle_t audio_q;
static SemaphoreHandle_t g_lock;
static char device[48] = {0};
static uint32_t g_boot = 0;
static uint8_t g_link_colour = 3;
static char t_delta[128], t_get_acc[128], t_mesh[128];

// ---------------------------------------------------------------- audio (its own task: a clip never
// blocks the buttons)
struct AudioJob {
  uint8_t role;
  bool chime;
};

static void tone_ms(uint16_t hz, uint32_t ms, int16_t amp) {
  static int16_t buf[256];
  uint32_t total = 16000u * ms / 1000u, phase = 0;
  while (total) {
    size_t n = total < 256 ? total : 256;
    for (size_t i = 0; i < n; i++, phase++) buf[i] = ((phase * hz * 2 / 16000u) & 1) ? amp : (int16_t)-amp;
    i2s.write((const uint8_t*)buf, n * sizeof(int16_t));
    total -= n;
  }
}

// /clips/<role>.wav on LittleFS: 16 kHz, 16-bit mono PCM, the 44-byte header skipped (the village's
// Hindi clips, the same catalog as the siren's SD card)
static void play_wav(uint8_t role) {
  char path[24];
  snprintf(path, sizeof path, "/clips/%u.wav", role);
  File f = LittleFS.open(path, "r");
  if (!f) {  // no clip: three beeps so the pradhan still hears something
    for (int i = 0; i < 3; i++) {
      tone_ms(900, 300, 6000);
      tone_ms(0, 200, 0);
    }
    return;
  }
  f.seek(44);
  uint8_t buf[512];
  int n;
  while ((n = f.read(buf, sizeof buf)) > 0) i2s.write(buf, (size_t)n);
  f.close();
}

static void audio_task(void*) {
  AudioJob j;
  for (;;) {
    if (xQueueReceive(audio_q, &j, portMAX_DELAY) != pdTRUE) continue;
    if (j.chime) {  // Watch: a chime only, never the alarm voice
      tone_ms(880, 400, 5000);
      tone_ms(660, 600, 5000);
    } else {
      play_wav(j.role);
    }
  }
}

// ---------------------------------------------------------------- the box's port

class Port : public BoxPort {
 public:
  uint32_t lora_button(uint8_t button, uint8_t key_pos, uint16_t hold_ms) override {
    pkr_button_payload_t b{button, key_pos, hold_ms};
    uint8_t p[PKR_FT_BUTTON_LEN];
    pkr_button_payload_encode(&b, p);
    uint32_t ctr = 0;
    return lora.send(PKR_FT_BUTTON, PKR_FRAME_BROADCAST, p, sizeof p, clk.unix_s(), clk.synced(), &ctr) ? ctr : 0;
  }
  bool cloud_up() override { return cloud.connected(); }
  void sms_officers(const char* text) override {
    sms_numbers([](const char* to, void* t) { cloud.sms(to, (const char*)t); }, (void*)text);
  }
  void level_leds(uint8_t level) override {
    for (uint8_t i = 0; i < 4; i++) digitalWrite(PIN_LED[i], i == level ? HIGH : LOW);
  }
  void link_led(uint8_t colour) override { g_link_colour = colour; }
  void play(uint8_t role, bool chime_only) override {
    AudioJob j{role, chime_only};
    xQueueSend(audio_q, &j, 0);
  }
  bool lora_wrapped(uint16_t dst, const uint8_t* payload, uint8_t len) override {
    return lora.send(PKR_FT_SIREN_CMD_WRAPPED, dst, payload, len, clk.unix_s(), clk.synced());
  }
};
static Port port;

// The box task's events go through a queue to loop(), which alone touches the outbox (LittleFS).
static QueueHandle_t event_q;
class QueuedSink : public EventSink {
 public:
  void emit(const Event& e) override {
    if (xQueueSend(event_q, &e, pdMS_TO_TICKS(100)) != pdTRUE) evlog.lost++;
  }
};
static QueuedSink queued;
static BoxCore box(port, clk, queued);

static void link_led_out() {  // 1 green blinking: cloud; 2 amber: LoRa only; 3 red: no link
  bool blink = (millis() / 500) % 2;
  digitalWrite(PIN_LINK_G, (g_link_colour == 1 && blink) || g_link_colour == 2 ? HIGH : LOW);
  digitalWrite(PIN_LINK_R, g_link_colour == 2 || g_link_colour == 3 ? HIGH : LOW);
}

// ---------------------------------------------------------------- cloud

static void on_message(const char* topic, const char* payload, size_t len) {
  if (strcmp(topic, t_delta) && strcmp(topic, t_get_acc)) return;
  BoxShadow s;
  if (parse_box_shadow(payload, len, &s) != 0) return;
  xSemaphoreTake(g_lock, portMAX_DELAY);
  box.apply_shadow(s);
  xSemaphoreGive(g_lock);
}

static void on_connect() {
  char t[128];
  shadow_topic(t, sizeof t, device, "siren", "get");  // never rely on queued messages: get on every connect
  cloud.publish(t, "{}", 2);
}

// ---------------------------------------------------------------- setup and loop

static void box_task(void*);

void setup() {
  for (int pin : PIN_LED) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  pinMode(PIN_LINK_R, OUTPUT);
  pinMode(PIN_LINK_G, OUTPUT);
  for (int pin : BTN_PIN) pinMode(pin, INPUT_PULLUP);
  pinMode(PIN_KEY_W, INPUT_PULLUP);
  pinMode(PIN_KEY_C, INPUT_PULLUP);
  Serial.begin(115200);
  esp_task_wdt_config_t wdt = {30000, 0, true};
  esp_task_wdt_reconfigure(&wdt);
  esp_task_wdt_add(nullptr);

  g_lock = xSemaphoreCreateMutex();
  event_q = xQueueCreate(8, sizeof(Event));
  nvs.begin("pukaar");
  g_boot = next_boot_number(nvs);
  flash.begin();
  outbox.begin(&flash);
  evlog.begin(&outbox, g_boot);
  load_provisioned_keys(keys, device, sizeof device);  // its own key, and the village's sirens (role ack)
  load_node_settings(settings);
  box.configure(settings.village, false);

  i2s.setPins(PIN_I2S_BCLK, PIN_I2S_LRC, PIN_I2S_DOUT);
  i2s.begin(I2S_MODE_STD, 16000, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
  audio_q = xQueueCreate(4, sizeof(AudioJob));
  xTaskCreatePinnedToCore(audio_task, "audio", 4096, nullptr, 1, nullptr, 0);

  radio.begin(E22, PIN_E22_RX, PIN_E22_TX, PIN_E22_M0, PIN_E22_M1, keys.addr(), PKR_RADIO_FREQ_PRIMARY_HZ);
  signer.begin(&keys, &nvs);
  receiver.begin(&keys, &nvs);
  lora.begin(&radio, &signer, PKR_DUTY_NODE_BUDGET_MS);
  mesh.begin(keys.addr());

  shadow_topic(t_delta, sizeof t_delta, device, "siren", "update/delta");
  shadow_topic(t_get_acc, sizeof t_get_acc, device, "siren", "get/accepted");
  snprintf(t_mesh, sizeof t_mesh, "pukaar/mesh/%s/%s/relay", settings.village, device);
  cloud.on_message(on_message);
  cloud.on_connect(on_connect);
  cloud.subscribe(t_delta);
  cloud.subscribe(t_get_acc);
  if (settings.endpoint[0])
    cloud.begin(device, settings.endpoint, settings.apn,
                MqttLink::Pins{PIN_MODEM_TX, PIN_MODEM_RX, PIN_MODEM_RST, PIN_MODEM_PWR});
  uplink.begin(&outbox, &cloud, "box", settings.village, device);
  xTaskCreatePinnedToCore(box_task, "box", 8192, nullptr, configMAX_PRIORITIES - 2, nullptr, 1);
}

// The box's own logic in a task of its own: a blocking modem or MQTT call in loop() never delays the
// buttons, the 3 s hold or the 2 s ACK wait.
static void box_task(void*) {
  esp_task_wdt_add(nullptr);
  for (;;) {
    xSemaphoreTake(g_lock, portMAX_DELAY);
    for (uint8_t b = 0; b < 4; b++) box.set_button(b, digitalRead(BTN_PIN[b]) == LOW);
    box.set_key(digitalRead(PIN_KEY_C) == LOW ? PKR_KEY_CRITICAL : digitalRead(PIN_KEY_W) == LOW ? PKR_KEY_WARNING : PKR_KEY_OFF);
    box.tick();
    // LoRa: an ACK from a siren ends the wait; every well-formed frame goes to the mesh batch
    uint8_t buf[PKR_FRAME_MAX_LEN];
    size_t n = radio.receive(buf, sizeof buf);
    pkr_frame_t f;
    if (n && pkr_frame_parse(buf, n, &f) == PKR_FRAME_OK) {
      box.on_lora_heard();
      if (f.type == PKR_FT_ACK && f.dst == keys.addr()) {
        RxResult rx = receiver.receive(buf, n, clk.unix_s(), clk.synced());  // the siren's own MAC
        if (rx.reason == 0) {
          pkr_ack_payload_t a;
          pkr_ack_payload_decode(rx.frame.payload, &a);
          box.on_ack(a.acked_src, a.acked_ctr);
        }
      }
      mesh.add(buf, n, millis());
    }
    xSemaphoreGive(g_lock);
    link_led_out();
    esp_task_wdt_reset();
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

void loop() {
  Event e;
  while (xQueueReceive(event_q, &e, 0) == pdTRUE) evlog.emit(e);
  if (mesh.due(millis()) && cloud.connected()) {
    static char body[MeshBatch::MAX * 96 + 32];
    xSemaphoreTake(g_lock, portMAX_DELAY);
    size_t len = mesh.build(body, sizeof body);
    if (len) mesh.clear();  // at most once: a lost batch is only telemetry
    xSemaphoreGive(g_lock);
    if (len) cloud.publish(t_mesh, body, len);
  }
  static uint32_t last_ntp = 0;
  if (cloud.connected() && !clk.synced() && (!last_ntp || millis() - last_ntp > 600000u)) {
    last_ntp = millis() | 1;
    clk.sync_ntp(3000);
  }

  cloud.loop();
  uplink.loop(clk.unix_s());
  static uint32_t last_hb = 0;
  if (!last_hb || millis() - last_hb >= PKR_LIMIT_HEARTBEAT_S * 1000u) {
    last_hb = millis() | 1;
    Heartbeat h;
    h.at = clk.unix_s();
    h.boot = g_boot;
    h.state = PKR_STATE_IDLE;
    h.fw = PUKAAR_FW;
    h.outbox_depth = outbox.depth();
    h.uptime_s = millis() / 1000;
    h.rssi = cloud.rssi();
    char body[512], topic[128];
    size_t len = heartbeat_to_json(h, body, sizeof body);
    snprintf(topic, sizeof topic, "pukaar/box/%s/%s/heartbeat", settings.village, device);
    if (len && cloud.connected()) cloud.publish(topic, body, len);
  }
  esp_task_wdt_reset();
  delay(10);
}
