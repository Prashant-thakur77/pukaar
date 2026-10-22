/* Pukaar tipping-bucket counter for the ESP32-S3's ULP-RISC-V (spec 3.2): it counts tips while the main
 * CPU deep-sleeps.
 *
 * *** NOT BUILT BY THIS REPOSITORY'S IMAGES, AND UNTESTED ON HARDWARE. *** A ULP program is linked into
 * an image by the ESP-IDF build (ulp_embed_binary); the PlatformIO Arduino build used for gauge_v3 has
 * no such step, so gauge_v3 wakes on each tip instead (src/gauge_v3/main.cpp). Everything this program
 * decides is pkr_ulp_rain_step (lib/pukaar_common/pkr_rain.c), which the host tests run tick by tick
 * (test/native/test_nodes: debounce, bounce, the once-a-minute wake, the 5 ms clock across its wrap).
 *
 * It is kept out of a folder named `ulp/` on purpose: PlatformIO installs the ULP toolchains for every
 * env of a project that has one (several hundred MB), and builds it only under the ESP-IDF framework.
 *
 * To use it: an ESP-IDF 5.x (or `framework = arduino, espidf`) build of the gauge with
 *   CONFIG_ULP_COPROC_ENABLED=y, CONFIG_ULP_COPROC_TYPE_RISCV=y, CONFIG_ULP_COPROC_RESERVE_MEM=4096
 * and either this file in the project's `ulp/` folder (PlatformIO's ESP-IDF builder) or, in the main
 * component's CMakeLists.txt,
 *   ulp_embed_binary(ulp_rain "../ulp_riscv/rain_counter.c;../lib/pukaar_common/pkr_rain.c" "main.cpp")
 * The main CPU then, on a cold boot: rtc_gpio_init(BUCKET) as an input with its pull-up,
 * pkr_ulp_rain_init((pkr_ulp_rain_t *)&ulp_state, 0, level, <the NVS mirror>), ulp_riscv_load_binary(),
 * ulp_set_wakeup_period(0, 5000) (5 ms) and ulp_riscv_run(); before each deep sleep
 * esp_sleep_enable_ulp_wakeup(). At each reading it calls pkr_rain_take_report on the same state with
 * pkr_ulp_rain_now_s() as the time, exactly as the wake-on-tip build does with the wall clock.
 *
 * The state is plain C with 32-bit fields, so its layout is the same on the RISC-V ULP and the Xtensa
 * main CPU (both 32-bit little-endian). The ULP program never initialises it: until the main CPU has
 * (magic set), it does nothing. */
#include <stdint.h>

#include "pkr_rain.h"
#include "schema.h"
#include "ulp_riscv.h"
#include "ulp_riscv_gpio.h"
#include "ulp_riscv_utils.h"

#define BUCKET_GPIO GPIO_NUM_8 /* src/gauge_v3/main.cpp PIN_BUCKET: an RTC GPIO, reed to GND */

pkr_ulp_rain_t state;                                   /* ulp_state on the main CPU */
volatile uint32_t burst_tips_per_min = PKR_RAIN_BURST_TIPS_PER_MIN;

int main(void) {
  if (state.magic != PKR_ULP_RAIN_MAGIC) return 0;
  uint8_t level = (uint8_t)ulp_riscv_gpio_get_level(BUCKET_GPIO);
  if (pkr_ulp_rain_step(&state, level, (uint16_t)burst_tips_per_min)) ulp_riscv_wakeup_main_processor();
  return 0; /* halts; the ULP timer starts it again in 5 ms */
}
