#include "pkr_pattern.h"

namespace pkr {

uint32_t default_clip_ms(uint8_t role) {
  switch (role) {
    case CLIP_WARNING: return 18000;
    case CLIP_CRITICAL: return 20000;
    case CLIP_AUTO: return 15000;
    case CLIP_ALL_CLEAR: return 15000;
    case CLIP_TEST: return 5000;
    case CLIP_DRILL: return 8000;
    case CLIP_DRILL_END: return 3000;
    default: return 0;
  }
}

static uint32_t clip_len(const PlanOptions& o, uint8_t role) {
  return (role < 8 && o.clip_ms[role]) ? o.clip_ms[role] : default_clip_ms(role);
}

static Segment steady(uint16_t hz, uint32_t ms, uint8_t vol = 100) {
  Segment s{Seg::Steady, ms};
  s.f_lo = s.f_hi = hz;
  s.volume = vol;
  return s;
}
static Segment silence(uint32_t ms) { return Segment{Seg::Silence, ms}; }
static Segment warble(uint16_t lo, uint16_t hi, uint16_t period, uint32_t ms) {
  Segment s{Seg::Warble, ms};
  s.f_lo = lo;
  s.f_hi = hi;
  s.period_ms = period;
  return s;
}
static Segment clip(uint8_t role, uint32_t ms, uint8_t vol = 100) {
  Segment s{Seg::Clip, ms};
  s.clip = role;
  s.volume = vol;
  return s;
}

static void w1_tone(std::vector<Segment>& v) {
  for (int i = 0; i < 3; i++) {
    v.push_back(steady(650, 5000));
    v.push_back(silence(3000));
  }
}
static void c1_tone(std::vector<Segment>& v) { v.push_back(warble(500, 1050, 6000, 60000)); }

// Voice slot 1: a lead-in of the pattern's own tone for 25 s, so its voice always runs 25 s after
// slot 0's and the two never talk over each other (MIC Japan's overlapping-speech lesson).
static void lead_in(std::vector<Segment>& out, const std::vector<Segment>& tone, uint32_t total) {
  uint32_t t = 0;
  for (size_t i = 0; t < total; i = (i + 1) % tone.size()) {
    Segment s = tone[i];
    if (s.ms > total - t) s.ms = total - t;
    out.push_back(s);
    t += s.ms;
  }
}

PlayPlan make_plan(uint8_t pattern, bool autonomy, const PlanOptions& o) {
  PlayPlan p;
  p.pattern = pattern;
  p.autonomy = autonomy;
  std::vector<Segment> tone;
  switch (pattern) {
    case PKR_PATTERN_W1:
      w1_tone(tone);
      p.cycle = tone;
      p.cycle.push_back(clip(CLIP_WARNING, clip_len(o, CLIP_WARNING)));
      p.cycle.push_back(silence(15000));
      p.first_cycles = 5;
      p.repeat_every_s = 900;
      p.repeat_cycles = 2;
      p.cap_on_s = 1200;
      p.strobe = STROBE_AMBER;
      break;
    case PKR_PATTERN_C1:
      c1_tone(tone);
      p.cycle = tone;
      p.cycle.push_back(clip(autonomy ? CLIP_AUTO : CLIP_CRITICAL, clip_len(o, autonomy ? CLIP_AUTO : CLIP_CRITICAL)));
      p.cycle.push_back(silence(10000));
      p.first_cycles = 10;
      p.repeat_every_s = autonomy ? 900 : 600;
      p.repeat_cycles = autonomy ? 10 : 3;
      p.cap_on_s = autonomy ? PKR_LIMIT_AUTONOMY_CAP_S : 2700;
      p.strobe = STROBE_RED;
      break;
    case PKR_PATTERN_A1:
      tone.push_back(steady(650, 30000));
      p.cycle = tone;
      p.cycle.push_back(clip(CLIP_ALL_CLEAR, clip_len(o, CLIP_ALL_CLEAR)));
      p.cycle.push_back(silence(5000));
      p.first_cycles = 1;
      p.repeat_every_s = 300;
      p.repeat_cycles = 1;
      p.max_blocks = 2;
      p.cap_on_s = 120;
      p.strobe = STROBE_GREEN;
      p.strobe_limit_ms = 30000;
      p.k3_mirror = false;
      break;
    case PKR_PATTERN_T1:
      for (int i = 0; i < 3; i++) {
        p.cycle.push_back(steady(900, 300, 50));
        p.cycle.push_back(silence(300));
      }
      p.cycle.push_back(clip(CLIP_TEST, clip_len(o, CLIP_TEST), 50));
      p.cycle.push_back(steady(900, 5000, 50));
      p.first_cycles = 1;
      p.max_blocks = 1;
      p.cap_on_s = 30;
      p.strobe = STROBE_AMBER;
      p.strobe_follows_tone = true;  // three flashes with the beeps (and the closing tone)
      p.k3_mirror = false;           // the electronic siren cannot play at 50 %
      break;
    case PKR_PATTERN_D1:
      // the drill clip comes FIRST, so nobody mistakes the tone that follows for a real alarm
      p.cycle.push_back(clip(CLIP_DRILL, clip_len(o, CLIP_DRILL)));
      if (o.drill_with_c1) {
        c1_tone(p.cycle);
      } else {
        w1_tone(p.cycle);
      }
      p.cycle.push_back(clip(CLIP_DRILL_END, clip_len(o, CLIP_DRILL_END)));
      p.first_cycles = 1;
      p.max_blocks = 1;
      p.cap_on_s = 120;
      p.strobe = STROBE_AMBER;
      break;
    case PKR_PATTERN_B1:
      p.cycle.push_back(steady(1200, 1500));
      p.cycle.push_back(silence(8500));
      p.first_cycles = 12;  // 2 minutes per wake, as v2
      p.max_blocks = 1;
      p.cap_on_s = 120;
      p.strobe = STROBE_RED;
      p.k3_mirror = false;
      break;
    default:
      return p;
  }
  // command overrides
  if (o.cycles) p.first_cycles = o.cycles;
  if (o.repeat_every_s) p.repeat_every_s = o.repeat_every_s;
  if (o.repeat_cycles) p.repeat_cycles = o.repeat_cycles;
  if (o.cap_on_s) p.cap_on_s = o.cap_on_s;
  if (o.volume) p.volume = o.volume > 100 ? 100 : o.volume;
  if (o.voice_slot == 1 && !tone.empty() && (pattern == PKR_PATTERN_W1 || pattern == PKR_PATTERN_C1 ||
                                            pattern == PKR_PATTERN_A1)) {
    std::vector<Segment> c;
    lead_in(c, tone, (uint32_t)PKR_LIMIT_VOICE_SLOT_OFFSET_S * 1000u);
    // prepend the lead-in to the first cycle only: the player plays `lead` once per block
    p.cycle.insert(p.cycle.begin(), c.begin(), c.end());
    p.lead_segments = (uint8_t)c.size();  // the player plays these once per block
  }
  return p;
}

uint32_t cycle_ms(const PlayPlan& p) {
  uint32_t t = 0;
  for (size_t i = p.lead_segments; i < p.cycle.size(); i++) t += p.cycle[i].ms;
  return t;
}

void PatternPlayer::start(const PlayPlan& plan, uint32_t now_ms) {
  plan_ = plan;
  ended_by_cap_ = false;
  sound_ms_ = 0;
  was_sound_ = false;
  blocks_done_ = 0;
  out_ = Output();
  if (plan_.cycle.empty() || plan_.first_cycles == 0) {
    phase_ = Phase::Idle;
    return;
  }
  phase_ = Phase::Block;
  seg_ = 0;
  seg_start_ = now_ms;
  cycles_left_ = plan_.first_cycles;
  cycle_in_block_ = 0;
  cont_start_ = block_start_ = now_ms;
  last_ms_ = now_ms;
  compute(now_ms, plan_.cycle[0].kind == Seg::Clip);
}

void PatternPlayer::stop() {
  phase_ = Phase::Idle;
  out_ = Output();
}

const Output& PatternPlayer::tick(uint32_t now_ms) {
  if (phase_ == Phase::Idle) {
    out_ = Output();
    return out_;
  }
  uint32_t dt = now_ms - last_ms_;
  last_ms_ = now_ms;
  if (was_sound_) sound_ms_ += dt;
  if (plan_.cap_on_s && sound_ms_ >= plan_.cap_on_s * 1000u) {
    ended_by_cap_ = true;
    stop();
    return out_;
  }
  bool entered_clip = false;
  for (int guard = 0; guard < 1000; guard++) {
    if (phase_ == Phase::Gap) {
      if ((int32_t)(now_ms - gap_until_) < 0) break;
      phase_ = Phase::Block;
      seg_ = 0;
      seg_start_ = gap_until_;
      cycles_left_ = plan_.repeat_cycles;
      cycle_in_block_ = 0;
      block_start_ = gap_until_;
      if (plan_.repeat_every_s >= PKR_LIMIT_REST_S) cont_start_ = gap_until_;
      entered_clip = plan_.cycle[0].kind == Seg::Clip;
      continue;
    }
    if (phase_ == Phase::Rest) {
      if ((int32_t)(now_ms - rest_until_) < 0) break;
      phase_ = Phase::Block;
      seg_start_ = rest_until_ - rest_offset_;
      cont_start_ = rest_until_;
      continue;
    }
    // Block
    if (now_ms - cont_start_ >= (uint32_t)PKR_LIMIT_CONTINUOUS_MAX_S * 1000u) {
      phase_ = Phase::Rest;
      uint32_t at = cont_start_ + (uint32_t)PKR_LIMIT_CONTINUOUS_MAX_S * 1000u;
      rest_offset_ = at - seg_start_;
      rest_until_ = at + (uint32_t)PKR_LIMIT_REST_S * 1000u;
      continue;
    }
    const Segment& s = plan_.cycle[seg_];
    if (now_ms - seg_start_ < s.ms) break;
    seg_start_ += s.ms;
    seg_++;
    if (seg_ >= plan_.cycle.size()) {
      cycle_in_block_++;
      cycles_left_--;
      if (cycles_left_ == 0) {
        blocks_done_++;
        if (plan_.repeat_cycles == 0 || blocks_done_ >= plan_.max_blocks) {
          stop();
          return out_;
        }
        phase_ = Phase::Gap;
        gap_until_ = seg_start_ + plan_.repeat_every_s * 1000u;
        continue;
      }
      seg_ = plan_.lead_segments;  // the lead-in plays once per block
    }
    if (plan_.cycle[seg_].kind == Seg::Clip) entered_clip = true;
  }
  compute(now_ms, entered_clip);
  return out_;
}

void PatternPlayer::compute(uint32_t now_ms, bool entered_clip) {
  Output o;
  o.active = phase_ != Phase::Idle;
  o.in_block = phase_ == Phase::Block;
  o.resting = phase_ == Phase::Rest;
  o.block_index = blocks_done_;
  o.cycle_index = cycle_in_block_;
  o.seg_index = (uint8_t)seg_;
  if (phase_ == Phase::Block) {
    const Segment& s = plan_.cycle[seg_];
    uint32_t el = now_ms - seg_start_;
    uint8_t vol = (uint8_t)((uint32_t)s.volume * plan_.volume / 100u);
    if (s.kind == Seg::Steady || s.kind == Seg::Warble) {
      o.tone = true;
      o.volume = vol;
      o.tone_seg_elapsed_ms = el;
      o.tone_seg_ms = s.ms;
      if (s.kind == Seg::Steady) {
        o.freq_hz = s.f_lo;
      } else {
        o.sweep = true;
        uint32_t ph = el % s.period_ms, half = s.period_ms / 2u;
        uint32_t span = (uint32_t)(s.f_hi - s.f_lo);
        uint32_t x = ph < half ? ph : s.period_ms - ph;  // triangle 0..half..0
        o.freq_hz = (uint16_t)(s.f_lo + span * x / half);
      }
      o.k3 = plan_.k3_mirror;
    } else if (s.kind == Seg::Clip) {
      o.clip_playing = true;
      o.clip = s.clip;
      o.volume = vol;
      o.clip_start = entered_clip;
    }
  }
  if (o.active) {
    if (plan_.strobe_follows_tone) {
      o.strobe = o.tone;
    } else if (plan_.strobe_limit_ms) {
      o.strobe = phase_ == Phase::Block && now_ms - block_start_ < plan_.strobe_limit_ms;
    } else {
      o.strobe = true;
    }
    o.strobe_colour = o.strobe ? plan_.strobe : (uint8_t)STROBE_OFF;
  }
  was_sound_ = o.tone || o.clip_playing;
  out_ = o;
}

}  // namespace pkr
