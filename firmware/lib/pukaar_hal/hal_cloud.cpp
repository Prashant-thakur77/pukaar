// PPP + TLS + MQTT to AWS IoT Core, the serial stand-in, and the outbox drain. UNTESTED ON HARDWARE.
#include <LittleFS.h>
#include <MQTT.h>  // 256dpi/arduino-mqtt (MIT)
#include <NetworkClientSecure.h>
#include <PPP.h>

#include "pukaar_hal.h"

namespace pkr {

static NetworkClientSecure g_net;
static MQTTClient g_mqtt(4096, 4096);
static String g_ca, g_cert, g_key;
static MqttLink* g_link = nullptr;

static String read_file(const char* path) {
  File f = LittleFS.open(path, "r");
  if (!f) return String();
  String s = f.readString();
  f.close();
  return s;
}

void shadow_topic(char* out, size_t cap, const char* thing, const char* shadow, const char* suffix) {
  snprintf(out, cap, "$aws/things/%s/shadow/name/%s/%s", thing, shadow, suffix);
}

static void on_mqtt(MQTTClient*, char topic[], char bytes[], int length) { MqttLink::dispatch(topic, bytes, length); }

void MqttLink::dispatch(const char* topic, const char* payload, int len) {
  if (g_link && g_link->msg_) g_link->msg_(topic, payload, (size_t)len);
}

bool MqttLink::begin(const char* thing, const char* endpoint, const char* apn, Pins pins) {
  g_link = this;
  pins_ = pins;
  strncpy(thing_, thing, sizeof thing_ - 1);
  strncpy(endpoint_, endpoint, sizeof endpoint_ - 1);
  g_ca = read_file("/certs/ca.pem");
  g_cert = read_file("/certs/device.pem");
  g_key = read_file("/certs/key.pem");
  if (pins.pwr >= 0) {
    pinMode(pins.pwr, OUTPUT);
    digitalWrite(pins.pwr, HIGH);
  }
  PPP.setApn(apn);
  PPP.setResetPin(pins.rst, false, 200);
  PPP.setPins(pins.tx, pins.rx);
  bool ok = PPP.begin(PPP_MODEM_SIM7600);  // the A76xx / SIM7670 speak the SIM7600 AT set
  if (ok) {
    PPP.cmd("AT+CMGF=1", 1000);  // SMS in text mode
  }
  g_net.setCACert(g_ca.c_str());
  g_net.setCertificate(g_cert.c_str());
  g_net.setPrivateKey(g_key.c_str());
  g_mqtt.begin(endpoint_, 8883, g_net);
  g_mqtt.setOptions(60, true, 10000);
  g_mqtt.onMessageAdvanced(on_mqtt);
  return ok && g_cert.length() && g_key.length();
}

bool MqttLink::bring_up() {
  if (!PPP.attached()) return false;
  if (!PPP.connected()) {
    PPP.mode(ESP_MODEM_MODE_CMUX);  // data and AT commands (SMS) on one UART
    return false;
  }
  if (!g_mqtt.connect(thing_)) return false;  // client id = thing name (IoT policy)
  for (uint8_t i = 0; i < n_subs_; i++) g_mqtt.subscribe(subs_[i], 1);
  if (conn_) conn_();
  return true;
}

void MqttLink::loop() {
  if (g_mqtt.connected()) {
    g_mqtt.loop();
    return;
  }
  uint32_t now = millis();
  if ((int32_t)(now - next_try_ms_) < 0) return;
  if (bring_up()) {
    fails_ = 0;
    return;
  }
  fails_++;
  uint32_t ceiling = backoff_s(fails_ < 8 ? fails_ : 8, esp_random());
  next_try_ms_ = now + 1000u * (ceiling ? ceiling : 1);
}

bool MqttLink::connected() { return g_mqtt.connected(); }

void MqttLink::end() {
  g_mqtt.disconnect();
  g_net.stop();
  PPP.end();
  if (pins_.pwr >= 0) digitalWrite(pins_.pwr, LOW);
}

bool MqttLink::publish(const char* topic, const char* payload, size_t len) {
  if (!g_mqtt.connected()) return false;
  return g_mqtt.publish(topic, payload, (int)len, false, 1);  // returns after the PUBACK
}

void MqttLink::subscribe(const char* topic) {
  if (n_subs_ < 8) {
    strncpy(subs_[n_subs_], topic, sizeof subs_[0] - 1);
    subs_[n_subs_][sizeof subs_[0] - 1] = 0;
    n_subs_++;
  }
  if (g_mqtt.connected()) g_mqtt.subscribe(topic, 1);
}

bool MqttLink::sms(const char* to, const char* text) { return PPP.sms(to, text); }

// Polls the modem's unread SMS (AT+CMGL="REC UNREAD", text mode) every 20 s and deletes what it
// read. A URC (+CMTI) path would be faster but needs the CMUX AT channel's URC handler.
void MqttLink::poll_sms(SmsFn fn) {
  uint32_t now = millis();
  if (now - last_sms_poll_ms_ < 20000u || !PPP.attached()) return;
  last_sms_poll_ms_ = now;
  String r = PPP.cmd("AT+CMGL=\"REC UNREAD\"", 3000);
  int at = 0;
  while ((at = r.indexOf("+CMGL:", at)) >= 0) {
    int eol = r.indexOf('\n', at);
    if (eol < 0) break;
    String head = r.substring(at, eol);
    int next = r.indexOf("+CMGL:", eol);
    String body = r.substring(eol + 1, next < 0 ? r.length() : next);
    body.trim();
    if (body.endsWith("OK")) {
      body = body.substring(0, body.length() - 2);
      body.trim();
    }
    // +CMGL: <idx>,"REC UNREAD","<from>",...
    int idx = head.substring(7, head.indexOf(',')).toInt();
    int q1 = head.indexOf("\",\"");
    int q2 = q1 >= 0 ? head.indexOf('"', q1 + 3) : -1;
    String from = q1 >= 0 && q2 > q1 ? head.substring(q1 + 3, q2) : String();
    if (fn && from.length()) fn(from.c_str(), body.c_str());
    PPP.cmd(String("AT+CMGD=") + idx, 2000);
    at = eol;
  }
}

int MqttLink::rssi() { return PPP.RSSI(); }

bool SerialLink::publish(const char* topic, const char*, size_t len) {
  if (!up_) return false;
  Serial.printf("<PUB %s %u\n", topic, (unsigned)len);
  return true;
}

bool SerialLink::sms(const char* to, const char* text) {
  Serial.printf("<SMS %s %s\n", to ? to : "<officers>", text);
  return true;
}

void SerialLink::set_up(bool up) {
  bool was = up_;
  up_ = up;
  if (up && !was && conn_) conn_();
}

void Uplink::begin(Outbox* ob, CloudLink* link, const char* kind, const char* village, const char* device,
                   const char* live, const char* key) {
  ob_ = ob;
  link_ = link;
  snprintf(t_event_, sizeof t_event_, "pukaar/%s/%s/%s/%s", kind, village, device, live);
  snprintf(t_backfill_, sizeof t_backfill_, "pukaar/%s/%s/%s/backfill", kind, village, device);
  snprintf(key_, sizeof key_, "%s", key);
}

void Uplink::loop(uint32_t now_s) {
  if (!link_->connected() || !ob_->depth()) return;
  if ((int32_t)(now_s - next_at_) < 0 || !breaker_.allow(now_s)) return;
  static OutRecord recs[PKR_OUTBOX_BACKFILL_BATCH];
  // the MQTT client's 4096-byte write buffer holds the topic and this body: a bigger batch shrinks
  // below (a body that never fits would trip the breaker on every try)
  static char body[3800];
  bool alarm = false;
  size_t n = ob_->peek(recs, PKR_OUTBOX_BACKFILL_BATCH, &alarm);
  if (!n) return;
  bool ok;
  size_t used = n;
  if (n == 1) {
    ok = link_->publish(t_event_, recs[0].payload.c_str(), recs[0].payload.size());
  } else {
    size_t len = 0;
    while (used > 1 && !(len = build_backfill(recs, used, body, sizeof body, key_))) used--;
    ok = len ? link_->publish(t_backfill_, body, len) : link_->publish(t_event_, recs[0].payload.c_str(), recs[0].payload.size());
    if (!len) used = 1;
  }
  if (ok && ob_->ack(alarm, used)) {
    breaker_.success();
    attempt_ = 0;
    next_at_ = 0;
  } else {
    breaker_.failure(now_s);
    next_at_ = now_s + backoff_s(++attempt_, esp_random());
  }
}

}  // namespace pkr
