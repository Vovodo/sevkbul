import {
  AudioSettings,
  FailureSoundId,
  SuccessSoundId,
  loadAudioSettings,
} from './audioSettings';

let ctx: AudioContext | null = null;

function getContext(): AudioContext {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

/** Başarı: sıcak bas + parlak tiz — yükselen melodi taşır */
function createSuccessChain(settings: AudioSettings, startTime: number, endTime: number) {
  const audioCtx = getContext();
  const input = audioCtx.createGain();

  const bass = audioCtx.createBiquadFilter();
  bass.type = 'lowshelf';
  bass.frequency.value = 100;
  bass.gain.value = 8 + settings.bassBoost * 14;

  const bright = audioCtx.createBiquadFilter();
  bright.type = 'highshelf';
  bright.frequency.value = 2200;
  bright.gain.value = 4;

  const master = audioCtx.createGain();
  master.gain.setValueAtTime(settings.volume * 1.85, startTime);

  const comp = audioCtx.createDynamicsCompressor();
  comp.threshold.value = -6;
  comp.ratio.value = 4;

  input.connect(bass);
  bass.connect(bright);
  bright.connect(master);
  master.connect(comp);
  comp.connect(audioCtx.destination);

  const fade = audioCtx.createGain();
  fade.gain.setValueAtTime(1, startTime);
  fade.gain.setValueAtTime(1, endTime - 0.04);
  fade.gain.linearRampToValueAtTime(0.001, endTime);
  fade.connect(input);
  return fade;
}

/** Başarısız: sert bas + orta frekans boost — depoda uzaktan duyulur, melodi YOK */
function createFailureChain(settings: AudioSettings, startTime: number, endTime: number) {
  const audioCtx = getContext();
  const input = audioCtx.createGain();

  const bass = audioCtx.createBiquadFilter();
  bass.type = 'lowshelf';
  bass.frequency.value = 80;
  bass.gain.value = 14 + settings.bassBoost * 12;

  const mid = audioCtx.createBiquadFilter();
  mid.type = 'peaking';
  mid.frequency.value = 420;
  mid.Q.value = 0.9;
  mid.gain.value = 10;

  const master = audioCtx.createGain();
  master.gain.setValueAtTime(settings.volume * 3.0, startTime);

  const comp = audioCtx.createDynamicsCompressor();
  comp.threshold.value = -2;
  comp.ratio.value = 2.5;
  comp.attack.value = 0.001;

  input.connect(bass);
  bass.connect(mid);
  mid.connect(master);
  master.connect(comp);
  comp.connect(audioCtx.destination);

  const fade = audioCtx.createGain();
  fade.gain.setValueAtTime(1, startTime);
  fade.gain.setValueAtTime(1, endTime - 0.02);
  fade.gain.linearRampToValueAtTime(0.001, endTime);
  fade.connect(input);
  return fade;
}

function playTone(
  output: AudioNode,
  freq: number,
  start: number,
  duration: number,
  type: OscillatorType = 'sine',
  peak = 0.55,
  attack = 0.006,
) {
  const audioCtx = getContext();
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(Math.max(peak, 0.0002), start + attack);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(gain);
  gain.connect(output);
  osc.start(start);
  osc.stop(start + duration + 0.04);
}

function playSweep(
  output: AudioNode,
  from: number,
  to: number,
  start: number,
  duration: number,
  type: OscillatorType,
  peak: number,
) {
  const audioCtx = getContext();
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(from, start);
  osc.frequency.exponentialRampToValueAtTime(Math.max(to, 20), start + duration);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(peak, start + 0.004);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(gain);
  gain.connect(output);
  osc.start(start);
  osc.stop(start + duration + 0.04);
}

function playThump(output: AudioNode, start: number, freq = 85, dur = 0.1, peak = 1) {
  playTone(output, freq, start, dur, 'sine', peak, 0.002);
  playTone(output, freq * 0.5, start, dur, 'sine', peak * 0.85, 0.002);
  playTone(output, freq * 2, start, dur * 0.5, 'square', peak * 0.18, 0.002);
}

function playRisingNote(output: AudioNode, freq: number, start: number, dur: number, peak: number) {
  playTone(output, freq, start, dur, 'sine', peak * 0.9, 0.005);
  playTone(output, freq, start, dur, 'triangle', peak * 0.65, 0.005);
  playTone(output, freq * 2, start + 0.008, dur * 0.75, 'sine', peak * 0.25, 0.004);
}

/* ─── BAŞARI SESLERİ ─── */

function playSuccessTriumph(output: AudioNode, t: number) {
  playThump(output, t, 50, 0.14, 1);
  playTone(output, 65, t, 0.85, 'sine', 0.55, 0.01);

  const notes = [262, 330, 392, 523];
  notes.forEach((f, i) => {
    const s = t + 0.08 + i * 0.13;
    const dur = i === notes.length - 1 ? 0.48 : 0.2;
    const peak = i === notes.length - 1 ? 0.85 : 0.68;
    playRisingNote(output, f, s, dur, peak);
  });

  const fin = t + 0.08 + 3 * 0.13;
  playTone(output, 659, fin + 0.04, 0.38, 'sine', 0.35, 0.005);
  playTone(output, 784, fin + 0.06, 0.3, 'triangle', 0.22, 0.005);
  playTone(output, 1047, fin + 0.08, 0.22, 'sine', 0.15, 0.004);
}

function playSuccessFanfare(output: AudioNode, t: number) {
  playThump(output, t, 55, 0.12, 1);
  playTone(output, 73, t, 0.95, 'sine', 0.5, 0.008);

  const notes = [196, 262, 330, 392, 523, 659];
  notes.forEach((f, i) => {
    const s = t + 0.06 + i * 0.1;
    const isLast = i === notes.length - 1;
    playRisingNote(output, f, s, isLast ? 0.5 : 0.14, isLast ? 0.88 : 0.62);
  });

  const fin = t + 0.06 + (notes.length - 1) * 0.1;
  playTone(output, 784, fin + 0.05, 0.35, 'sine', 0.3, 0.005);
  playTone(output, 988, fin + 0.08, 0.28, 'triangle', 0.2, 0.004);
}

function playSuccessGolden(output: AudioNode, t: number) {
  playThump(output, t, 110, 0.12, 0.95);
  playRisingNote(output, 440, t + 0.04, 0.45, 0.75);
  playRisingNote(output, 554, t + 0.12, 0.35, 0.5);
  playTone(output, 880, t + 0.08, 0.38, 'sine', 0.38, 0.005);
}

function playSuccessPulse(output: AudioNode, t: number) {
  playThump(output, t, 75, 0.12, 1);
  playThump(output, t + 0.16, 75, 0.12, 0.95);
  playRisingNote(output, 880, t + 0.08, 0.28, 0.6);
  playRisingNote(output, 1175, t + 0.2, 0.28, 0.55);
}

function playSuccessCyberChime(output: AudioNode, t: number) {
  playThump(output, t, 60, 0.12, 0.9);
  const chimeNotes = [523.25, 659.25, 783.99, 1046.50, 1318.51, 1567.98];
  chimeNotes.forEach((f, i) => {
    const s = t + 0.04 + i * 0.08;
    playTone(output, f, s, 0.3, 'sine', 0.75, 0.003);
    playTone(output, f * 2, s + 0.005, 0.2, 'triangle', 0.25, 0.003);
  });
}

function playSuccessCrystalBell(output: AudioNode, t: number) {
  playThump(output, t, 80, 0.15, 1);
  playTone(output, 1046.50, t + 0.02, 0.7, 'sine', 0.85, 0.002);
  playTone(output, 2093.00, t + 0.04, 0.5, 'sine', 0.45, 0.002);
  playTone(output, 3139.50, t + 0.06, 0.35, 'triangle', 0.25, 0.002);
}

function playSuccessMajesticArpeggio(output: AudioNode, t: number) {
  playThump(output, t, 45, 0.15, 1);
  const arpNotes = [261.63, 329.63, 392.00, 523.25, 659.25, 783.99];
  arpNotes.forEach((f, i) => {
    const s = t + i * 0.09;
    const dur = i === arpNotes.length - 1 ? 0.6 : 0.25;
    playRisingNote(output, f, s, dur, 0.75);
  });
}

/* ─── BAŞARISIZ SESLERİ ─── */

function playErrorPattern(output: AudioNode, t: number) {
  playThump(output, t, 90, 0.11, 1);
  playThump(output, t + 0.14, 90, 0.11, 1);
  playSweep(output, 480, 140, t + 0.1, 0.22, 'square', 0.95);
  playSweep(output, 320, 100, t + 0.12, 0.18, 'sawtooth', 0.35);
}

function playFailureSoft(output: AudioNode, t: number) {
  playErrorPattern(output, t);
}

function playFailureTick(output: AudioNode, t: number) {
  playThump(output, t, 80, 0.1, 1);
  playThump(output, t + 0.11, 80, 0.1, 1);
  playThump(output, t + 0.22, 80, 0.1, 1);
  playSweep(output, 400, 120, t + 0.08, 0.25, 'square', 0.9);
}

function playFailureMuted(output: AudioNode, t: number) {
  playThump(output, t, 70, 0.13, 1);
  playThump(output, t + 0.15, 70, 0.13, 1);
  playSweep(output, 550, 90, t + 0.12, 0.28, 'square', 1);
  playTone(output, 130, t + 0.28, 0.12, 'square', 0.7, 0.003);
}

function playFailureGentle(output: AudioNode, t: number) {
  playThump(output, t, 95, 0.1, 1);
  playSweep(output, 450, 180, t + 0.04, 0.14, 'square', 0.85);
  playThump(output, t + 0.18, 75, 0.1, 0.95);
  playSweep(output, 380, 110, t + 0.2, 0.12, 'square', 0.8);
}

function playFailureSirenWarn(output: AudioNode, t: number) {
  playThump(output, t, 100, 0.12, 1);
  playThump(output, t + 0.14, 100, 0.12, 1);
  playSweep(output, 850, 220, t + 0.02, 0.18, 'sawtooth', 0.9);
  playSweep(output, 850, 220, t + 0.16, 0.22, 'sawtooth', 0.95);
}

function playFailureCyberDeny(output: AudioNode, t: number) {
  playThump(output, t, 110, 0.1, 1);
  playSweep(output, 650, 90, t, 0.18, 'square', 0.95);
  playThump(output, t + 0.12, 110, 0.1, 1);
  playSweep(output, 650, 90, t + 0.12, 0.22, 'sawtooth', 0.95);
}

function playFailureSubImpact(output: AudioNode, t: number) {
  playThump(output, t, 45, 0.25, 1);
  playSweep(output, 350, 75, t + 0.02, 0.25, 'square', 0.85);
  playThump(output, t + 0.15, 50, 0.2, 0.9);
}

const SUCCESS_DURATIONS: Record<SuccessSoundId, number> = {
  triumph: 1.05,
  golden: 0.62,
  pulse: 0.55,
  fanfare: 1.15,
  cyber_chime: 0.8,
  crystal_bell: 0.75,
  majestic_arpeggio: 1.1,
};

const FAILURE_DURATIONS: Record<FailureSoundId, number> = {
  soft: 0.38,
  tick: 0.38,
  muted: 0.42,
  gentle: 0.36,
  siren_warn: 0.45,
  cyber_deny: 0.4,
  sub_impact: 0.45,
};

function playSuccessPreset(id: SuccessSoundId, settings: AudioSettings) {
  const t = getContext().currentTime;
  const dur = SUCCESS_DURATIONS[id] || 0.8;
  const output = createSuccessChain(settings, t, t + dur);
  switch (id) {
    case 'golden': playSuccessGolden(output, t); break;
    case 'pulse': playSuccessPulse(output, t); break;
    case 'fanfare': playSuccessFanfare(output, t); break;
    case 'cyber_chime': playSuccessCyberChime(output, t); break;
    case 'crystal_bell': playSuccessCrystalBell(output, t); break;
    case 'majestic_arpeggio': playSuccessMajesticArpeggio(output, t); break;
    default: playSuccessTriumph(output, t);
  }
}

function playFailurePreset(id: FailureSoundId, settings: AudioSettings) {
  const t = getContext().currentTime;
  const dur = FAILURE_DURATIONS[id] || 0.4;
  const output = createFailureChain(settings, t, t + dur);
  switch (id) {
    case 'tick': playFailureTick(output, t); break;
    case 'muted': playFailureMuted(output, t); break;
    case 'gentle': playFailureGentle(output, t); break;
    case 'siren_warn': playFailureSirenWarn(output, t); break;
    case 'cyber_deny': playFailureCyberDeny(output, t); break;
    case 'sub_impact': playFailureSubImpact(output, t); break;
    default: playFailureSoft(output, t);
  }
}

export function warmupAudioEngine() {
  getContext();
}

export function previewSuccessSound(id: SuccessSoundId, settings?: AudioSettings) {
  const s = settings ?? loadAudioSettings();
  if (!s.enabled) return;
  playSuccessPreset(id, s);
}

export function previewFailureSound(id: FailureSoundId, settings?: AudioSettings) {
  const s = settings ?? loadAudioSettings();
  if (!s.enabled) return;
  playFailurePreset(id, s);
}

export function playResultSound(category: 'success' | 'failure', settings?: AudioSettings) {
  const s = settings ?? loadAudioSettings();
  if (!s.enabled) return;
  if (category === 'success') {
    playSuccessPreset(s.successSound, s);
  } else {
    playFailurePreset(s.failureSound, s);
  }
}
