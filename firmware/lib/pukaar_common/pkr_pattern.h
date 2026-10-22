// Alarm patterns (section 4.1) as data, and a player that turns one into outputs over time.
//
//  W1 "teen lambi": 3 x (5 s steady 650 Hz, 3 s off), warning clip, 15 s silence; 5 cycles, then
//                   2 cycles every 15 min; cap 20 min sound-on; amber strobe.
//  C1 "lahar":      60 s rising and falling 500-1050 Hz (6 s period), critical clip, 10 s silence;
//                   10 cycles, then 3 every 10 min; cap 45 min; red strobe.
//  A1 "sthir":      30 s steady 650 Hz, all-clear clip; once, repeated once after 5 min; cap 2 min;
//                   green strobe for 30 s.
//  T1:              3 x 0.3 s beeps at 900 Hz (50 %), test clip, 5 s steady (50 %); once; <= 30 s.
//  D1:              drill clip FIRST, one W1 cycle (C1 only with DDMA consent), "it was a drill" clip;
//                   once; <= 2 min. Always wrapped: a drill never plays a bare W1 or C1.
//  AUTO:            C1 with the automatic clip; 10 cycles, re-armed every 15 min; cap 30 min.
//  B1:              1.5 s chirps at 1200 Hz every 10 s for 2 min (gauge bridge beacon).
// Every pattern: at most 10 min continuous, then 2 min rest. Voice slot 1 starts its voice 25 s
// later and keeps the tone going while slot 0 speaks.
#pragma once

#include <stdint.h>

#include <vector>

#include "schema.h"

namespace pkr {

enum class Seg : uint8_t { Silence, Steady, Warble, Clip };

enum ClipRole : uint8_t {
  CLIP_NONE = 0,
  CLIP_WARNING = 1,
  CLIP_CRITICAL = 2,
  CLIP_AUTO = 3,
  CLIP_ALL_CLEAR = 4,
  CLIP_TEST = 5,
  CLIP_DRILL = 6,
  CLIP_DRILL_END = 7,
};
uint32_t default_clip_ms(uint8_t role);

enum Strobe : uint8_t { STROBE_OFF = 0, STROBE_AMBER = 1, STROBE_RED = 2, STROBE_GREEN = 3 };

struct Segment {
  Seg kind;
  uint32_t ms;
  uint16_t f_lo = 0, f_hi = 0;  // Steady uses f_lo; Warble sweeps f_lo..f_hi..f_lo
  uint16_t period_ms = 0;       // Warble
  uint8_t volume = 100;         // percent of the command volume
  uint8_t clip = CLIP_NONE;
};

struct PlayPlan {
  uint8_t pattern = PKR_PATTERN_NONE;
  bool autonomy = false;            // C1 with the automatic clip (and its own timings)
  std::vector<Segment> cycle;       // one cycle (after `lead_segments` lead-in segments)
  uint8_t lead_segments = 0;        // voice slot 1: tone lead-in played once at each block start
  uint16_t first_cycles = 1;
  uint32_t repeat_every_s = 0;      // gap from the end of one block to the start of the next
  uint16_t repeat_cycles = 0;       // 0 = no repeats
  uint16_t max_blocks = 0xFFFF;     // including the first
  uint32_t cap_on_s = 0;            // total sound-on cap
  uint8_t volume = 100;
  uint8_t strobe = STROBE_OFF;
  uint32_t strobe_limit_ms = 0;     // 0 = whole time active; A1: 30 s per block
  bool strobe_follows_tone = false; // T1: three flashes with the beeps
  bool k3_mirror = true;            // the 12 V electronic siren follows the tone
};

struct PlanOptions {
  uint8_t voice_slot = 0;
  bool drill_with_c1 = false;          // pre-monsoon drill only, with DDMA consent
  uint32_t clip_ms[8] = {0};           // overrides from the clip catalog (0 = default)
  // command overrides (0 = pattern default)
  uint16_t cycles = 0;
  uint32_t repeat_every_s = 0;
  uint16_t repeat_cycles = 0;
  uint32_t cap_on_s = 0;
  uint8_t volume = 0;
};

// The plan for a pattern id (PKR_PATTERN_*). autonomy=true gives the C1 + auto clip variant.
// Returns an empty cycle for an unknown pattern.
PlayPlan make_plan(uint8_t pattern, bool autonomy, const PlanOptions& o);
// Sum of the cycle's segment durations.
uint32_t cycle_ms(const PlayPlan& p);

struct Output {
  bool active = false;     // the pattern is running (including its gaps and rests)
  bool in_block = false;   // inside a sounding block (not in a gap or thermal rest)
  bool resting = false;    // forced 2-minute thermal rest
  bool tone = false;
  uint16_t freq_hz = 0;
  bool sweep = false;       // a Warble segment (the DFPlayer plays its sweep track)
  uint8_t volume = 0;
  bool clip_playing = false;
  uint8_t clip = CLIP_NONE;
  bool clip_start = false; // edge: start the clip now
  bool strobe = false;
  uint8_t strobe_colour = STROBE_OFF;
  bool k3 = false;
  uint32_t tone_seg_elapsed_ms = 0;  // how long the current tone segment has played
  uint32_t tone_seg_ms = 0;          // its length
  uint8_t seg_index = 0;
  uint16_t cycle_index = 0;          // within the current block
  uint16_t block_index = 0;
};

class PatternPlayer {
 public:
  void start(const PlayPlan& plan, uint32_t now_ms);
  void stop();
  const Output& tick(uint32_t now_ms);
  bool active() const { return phase_ != Phase::Idle; }
  bool ended_by_cap() const { return ended_by_cap_; }
  uint32_t sound_on_ms() const { return sound_ms_; }
  const PlayPlan& plan() const { return plan_; }
  const Output& output() const { return out_; }

 private:
  enum class Phase : uint8_t { Idle, Block, Rest, Gap };
  void compute(uint32_t now_ms, bool entered_clip);
  PlayPlan plan_;
  Phase phase_ = Phase::Idle;
  size_t seg_ = 0;
  uint32_t seg_start_ = 0;
  uint16_t cycles_left_ = 0;
  uint16_t blocks_done_ = 0;
  uint16_t cycle_in_block_ = 0;
  uint32_t gap_until_ = 0, rest_until_ = 0, rest_offset_ = 0;
  uint32_t cont_start_ = 0, block_start_ = 0;
  uint32_t last_ms_ = 0;
  uint32_t sound_ms_ = 0;
  bool was_sound_ = false;
  bool ended_by_cap_ = false;
  Output out_;
};

}  // namespace pkr
