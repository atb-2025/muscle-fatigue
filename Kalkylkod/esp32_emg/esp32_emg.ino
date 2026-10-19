// Arduino IDE: install "esp32 by Espressif Systems". Read README_ESP32.md.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

// 0 = Wi-Fi TCP, 1 = USB serial, 2 = Bluetooth Classic SPP (original ESP32 only)
#define TRANSPORT 0
// REQUIRED: enter an exposed ADC1 GPIO from your board's pinout.
// Examples only: original ESP32 GPIO34; ESP32-S3 GPIO4; ESP32-C3 GPIO4.
#define EMG_ADC_PIN 1
#if EMG_ADC_PIN < 0
#error Set EMG_ADC_PIN to a verified ADC1 GPIO for your exact board before uploading.
#endif
#if TRANSPORT == 2
#include <BluetoothSerial.h>
#if !defined(CONFIG_BT_SPP_ENABLED)
#error Bluetooth Classic SPP requires the original ESP32. Use Wi-Fi on C3/S3.
#endif
BluetoothSerial SerialBT;
#elif TRANSPORT != 0 && TRANSPORT != 1
#error TRANSPORT must be 0, 1 or 2.
#endif

constexpr uint32_t SAMPLE_HZ = 2000;
constexpr uint32_t USB_BAUD = 921600;
constexpr uint16_t TCP_PORT = 5000;
const char *AP_NAME = "ESP32-EMG";
const char *AP_PASSWORD = "emgsetup2026"; // Change before uploading; at least 8 characters.
// false: computer joins the ESP32's own Wi-Fi. true: both join your router.
constexpr bool USE_ROUTER = false;
const char *ROUTER_SSID = "YOUR_WIFI_NAME";
const char *ROUTER_PASSWORD = "YOUR_WIFI_PASSWORD";

WiFiServer server(TCP_PORT);
WiFiClient client;
struct Sample { int64_t time_us; uint32_t mv; };
QueueHandle_t samples;
esp_timer_handle_t sample_timer;
bool sampling = false;
TaskHandle_t sampler_task;

// Runs in esp_timer's TASK context, never in an ISR. No network I/O here.
void sampleTick(void *) {
  xTaskNotifyGive(sampler_task);
}
void sampleTask(void *) {
  for (;;) {
    // Clear overdue notifications; never fabricate evenly spaced catch-up readings.
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    Sample s;
    s.time_us = esp_timer_get_time();
    s.mv = analogReadMilliVolts(EMG_ADC_PIN); // pin mV, bias INCLUDED
    xQueueSend(samples, &s, 0); // Overflow leaves a visible timestamp gap.
  }
}

void startSampling() {
  xQueueReset(samples);
  ESP_ERROR_CHECK(esp_timer_start_periodic(sample_timer, 1000000 / SAMPLE_HZ));
  sampling = true;
}
void stopSampling() {
  if (sampling) ESP_ERROR_CHECK(esp_timer_stop(sample_timer));
  sampling = false;
}

void setup() {
  Serial.begin(USB_BAUD);
  analogReadResolution(12);
  analogSetPinAttenuation(EMG_ADC_PIN, ADC_11db);
  analogReadMilliVolts(EMG_ADC_PIN); // initialize/calibrate before starting the timer
  samples = xQueueCreate(4096, sizeof(Sample));
  if (!samples) { Serial.println("#ERROR queue allocation"); while (true) delay(1000); }
  if (xTaskCreate(sampleTask, "emg_sample", 4096, nullptr, 3, &sampler_task) != pdPASS) {
    Serial.println("#ERROR sampler task allocation"); while (true) delay(1000);
  }
  esp_timer_create_args_t args = {};
  args.callback = &sampleTick;
  args.dispatch_method = ESP_TIMER_TASK;
  args.name = "emg_adc";
  args.skip_unhandled_events = true;
  ESP_ERROR_CHECK(esp_timer_create(&args, &sample_timer));
#if TRANSPORT == 0
  if (USE_ROUTER) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(ROUTER_SSID, ROUTER_PASSWORD);
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) delay(100);
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("#ERROR router connection failed; check credentials and restart");
      while (true) delay(1000);
    }
    WiFi.setSleep(false);
    Serial.print("#IP "); Serial.println(WiFi.localIP());
  } else {
    WiFi.mode(WIFI_AP);
    if (!WiFi.softAP(AP_NAME, AP_PASSWORD)) {
      Serial.println("#ERROR access point startup failed");
      while (true) delay(1000);
    }
    Serial.print("#IP "); Serial.println(WiFi.softAPIP());
  }
  server.begin();
  Serial.printf("#TCP port=%u fs=%lu\n", TCP_PORT, (unsigned long)SAMPLE_HZ);
#elif TRANSPORT == 2
  if (!SerialBT.begin("ESP32-EMG")) {
    Serial.println("#ERROR Bluetooth startup failed");
    while (true) delay(1000);
  }
#else
  startSampling();
#endif
}

void loop() {
#if TRANSPORT == 0
  if (!client || !client.connected()) {
    stopSampling();
    client.stop();
    client = server.accept();
    if (!client) { delay(10); return; }
    client.setNoDelay(true);
    client.printf("#ESP32-EMG fs=%lu unit=pin_mV\n", (unsigned long)SAMPLE_HZ);
    startSampling();
  }
#elif TRANSPORT == 2
  if (!SerialBT.hasClient()) { stopSampling(); delay(10); return; }
  if (!sampling) {
    SerialBT.printf("#ESP32-EMG fs=%lu unit=pin_mV\n", (unsigned long)SAMPLE_HZ);
    startSampling();
  }
#endif
  // Batch 20 samples (~10 ms). Sampling continues independently during transmission.
  char packet[1024];
  size_t used = 0;
  for (int i = 0; i < 20; ++i) {
    Sample s;
    if (xQueueReceive(samples, &s, pdMS_TO_TICKS(20)) != pdTRUE) break;
    int n = snprintf(packet + used, sizeof(packet) - used, "%lld %lu\n",
                     (long long)s.time_us, (unsigned long)s.mv);
    if (n <= 0 || (size_t)n >= sizeof(packet) - used) break;
    used += n;
  }
  size_t sent = 0;
  while (sent < used) {
#if TRANSPORT == 0
    size_t n = client.write((const uint8_t *)packet + sent, used - sent);
#elif TRANSPORT == 2
    size_t n = SerialBT.write((const uint8_t *)packet + sent, used - sent);
#else
    size_t n = Serial.write((const uint8_t *)packet + sent, used - sent);
#endif
    if (!n) {
#if TRANSPORT == 0
      client.stop();
#endif
      break;
    }
    sent += n;
  }
}
