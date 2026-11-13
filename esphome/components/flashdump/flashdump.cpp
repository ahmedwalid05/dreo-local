#include "flashdump.h"
#include "esphome/core/log.h"
#include "Arduino.h"

extern "C" {
#include "flash.h"
}

namespace esphome {
namespace flashdump {

static const char *TAG = "flashdump";

// READ-ONLY dump of calibration + tail region
// Calibration: 0x1E0000, 4KB (TLS certs, device serial, RF calibration)
// Tail: 0x1E1000 to 0x1FFFFF (~60KB, unknown content)
// Output as hex over the log, 32 bytes per line

void FlashDumpButton::press_action() {
  const uint32_t CAL_BASE = 0x1E1000;
  const uint32_t CAL_LEN = 0x1F000;
  const uint32_t TAIL_BASE = 0x1E1000;
  const uint32_t TAIL_LEN = 0x1F000;    // ~124KB to end of 2MB flash
  
  uint8_t buf[32];
  char hex[65];
  
  ESP_LOGW(TAG, "=== READ-ONLY TAIL DUMP: 0x1E1000 +0x1000 ===");
  ESP_LOGW(TAG, "CALBEGIN");
  for (uint32_t off = 0; off < CAL_LEN; off += 32) {
    flash_read((char*)buf, 32, CAL_BASE + off);
    static const char hc[] = "0123456789ABCDEF"; for (int i = 0; i < 32; i++) { hex[i*2] = hc[buf[i] >> 4]; hex[i*2+1] = hc[buf[i] & 0xF]; }
    hex[64] = 0;
    ESP_LOGW(TAG, "CAL:%06X:%s", off, hex);
    delay(10);  // let the log flush
  }
  ESP_LOGW(TAG, "CALEND");
  
  ESP_LOGW(TAG, "=== TAIL REGION: 0x1E1000 +0x1F000 (first 4KB only) ===");
  ESP_LOGW(TAG, "TAILBEGIN");
  for (uint32_t off = 0; off < 0x1000; off += 32) {
    flash_read((char*)buf, 32, TAIL_BASE + off);
    static const char hc[] = "0123456789ABCDEF"; for (int i = 0; i < 32; i++) { hex[i*2] = hc[buf[i] >> 4]; hex[i*2+1] = hc[buf[i] & 0xF]; }
    hex[64] = 0;
    ESP_LOGW(TAG, "TAIL:%06X:%s", off, hex);
    delay(10);
  }
  ESP_LOGW(TAG, "TAILEND");
  
  ESP_LOGW(TAG, "=== DUMP COMPLETE (read-only, nothing written) ===");
}

}  // namespace flashdump
}  // namespace esphome
namespace esphome { namespace flashdump {
static void do_dump() {
  const uint32_t CAL_BASE = 0x1E1000;
  uint8_t buf[32];
  static const char hc[] = "0123456789ABCDEF";
  char hex[65];
  ESP_LOGW("flashdump", "CALBEGIN");
  for (uint32_t off = 0; off < 0x1000; off += 32) {
    flash_read((char*)buf, 32, CAL_BASE + off);
    for (int i = 0; i < 32; i++) { hex[i*2]=hc[buf[i]>>4]; hex[i*2+1]=hc[buf[i]&0xF]; }
    hex[64]=0;
    ESP_LOGW("flashdump", "CAL:%06X:%s", off, hex);
    delay(5);
  }
  ESP_LOGW("flashdump", "CALEND");
  ESP_LOGW("flashdump", "COMPLETE");
}
void trigger_dump() { do_dump(); }
} }
