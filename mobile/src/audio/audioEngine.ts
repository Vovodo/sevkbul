import { Haptics, ImpactStyle, NotificationType } from '@capacitor/haptics';
import {
  MobileAudioSettings,
  loadMobileAudioSettings,
} from './audioSettings';

let ctx: AudioContext | null = null;

function getContext(): AudioContext {
  if (!ctx) {
    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    ctx = new AudioCtx();
  }
  if (ctx.state === 'suspended') {
    void ctx.resume();
  }
  return ctx;
}

function playTone(
  output: AudioNode,
  freq: number,
  start: number,
  duration: number,
  type: OscillatorType = 'sine',
  peak = 0.8,
  attack = 0.003,
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
  gain.gain.exponentialRampToValueAtTime(peak, start + 0.003);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(gain);
  gain.connect(output);
  osc.start(start);
  osc.stop(start + duration + 0.04);
}

function playThump(output: AudioNode, start: number, freq = 90, dur = 0.12, peak = 1) {
  playTone(output, freq, start, dur, 'sine', peak, 0.002);
  playTone(output, freq * 0.5, start, dur, 'sine', peak * 0.85, 0.002);
}

function createMasterChain(settings: MobileAudioSettings, startTime: number, endTime: number) {
  const audioCtx = getContext();
  const input = audioCtx.createGain();
  const master = audioCtx.createGain();
  master.gain.setValueAtTime(settings.volume * 2.5, startTime);

  const comp = audioCtx.createDynamicsCompressor();
  comp.threshold.value = -2.0;
  comp.knee.value = 3.0;
  comp.ratio.value = 12.0;
  comp.attack.value = 0.001;
  comp.release.value = 0.05;

  input.connect(master);
  master.connect(comp);
  comp.connect(audioCtx.destination);

  const fade = audioCtx.createGain();
  fade.gain.setValueAtTime(1, startTime);
  fade.gain.setValueAtTime(1, Math.max(startTime, endTime - 0.03));
  fade.gain.linearRampToValueAtTime(0.001, endTime);
  fade.connect(input);
  return fade;
}

/* ─── BAŞARI SESLERİ ─── */

function playMinecraftLevelUp(output: AudioNode, t: number) {
  const mcNotes = [466.16, 554.37, 622.25, 739.99, 830.61, 932.33, 1108.73, 1244.51, 1479.98, 1661.22, 1864.66, 2217.46];
  mcNotes.forEach((freq, i) => {
    const noteStart = t + i * 0.045;
    const isHigh = i >= 8;
    const dur = isHigh ? 0.35 : 0.18;
    const peak = isHigh ? 0.9 : 0.75;
    playTone(output, freq, noteStart, dur, 'triangle', peak, 0.002);
    playTone(output, freq, noteStart + 0.001, dur, 'sine', peak * 0.7, 0.002);
    playTone(output, freq * 0.5, noteStart, 0.04, 'square', 0.15, 0.001);
  });

  const chordStart = t + 0.54;
  playTone(output, 1108.73, chordStart, 0.9, 'triangle', 0.5, 0.003);
  playTone(output, 1396.91, chordStart + 0.01, 0.95, 'sine', 0.45, 0.003);
  playTone(output, 1661.22, chordStart + 0.02, 1.0, 'sine', 0.5, 0.003);
  playTone(output, 2217.46, chordStart + 0.03, 1.1, 'sine', 0.6, 0.003);
  playTone(output, 138.59, chordStart, 0.8, 'sine', 0.35, 0.01);
}

function playCyberChime(output: AudioNode, t: number) {
  playThump(output, t, 65, 0.12, 1.0);
  const chimeNotes = [523.25, 659.25, 783.99, 1046.50, 1318.51, 1567.98];
  chimeNotes.forEach((f, i) => {
    const s = t + 0.03 + i * 0.07;
    playTone(output, f, s, 0.28, 'sine', 0.9, 0.002);
    playTone(output, f * 2, s + 0.004, 0.2, 'triangle', 0.4, 0.002);
  });
}

function playIndustrialLaser(output: AudioNode, t: number) {
  playSweep(output, 1400, 2800, t, 0.08, 'sawtooth', 0.85);
  playSweep(output, 1800, 3400, t + 0.07, 0.09, 'sine', 0.95);
  playTone(output, 3135.96, t + 0.15, 0.4, 'sine', 0.9, 0.002);
}

function playHyperBeep(output: AudioNode, t: number) {
  playTone(output, 2400, t, 0.08, 'square', 0.9, 0.001);
  playTone(output, 3200, t + 0.09, 0.12, 'square', 1.0, 0.001);
}

/* ─── ÖZEL DURUM SESLERİ ─── */

function playDuplicateSound(output: AudioNode, t: number) {
  playTone(output, 1567.98, t, 0.2, 'sine', 0.85, 0.002);
  playTone(output, 1046.50, t + 0.13, 0.25, 'sine', 0.9, 0.002);
  playTone(output, 220, t, 0.3, 'sine', 0.5, 0.005);
}

function playExceededSound(output: AudioNode, t: number) {
  playTone(output, 1800, t, 0.06, 'square', 0.95, 0.001);
  playTone(output, 1800, t + 0.08, 0.06, 'square', 0.95, 0.001);
  playSweep(output, 1200, 300, t + 0.15, 0.25, 'sawtooth', 0.85);
  playThump(output, t + 0.15, 60, 0.2, 0.9);
}

/* ─── HATA SESLERİ ─── */

function playWarehouseAlarm(output: AudioNode, t: number) {
  playThump(output, t, 120, 0.12, 1.0);
  playSweep(output, 850, 220, t + 0.02, 0.15, 'sawtooth', 1.0);
  playThump(output, t + 0.13, 120, 0.12, 1.0);
  playSweep(output, 950, 180, t + 0.15, 0.18, 'sawtooth', 1.0);
}

function playHyperError(output: AudioNode, t: number) {
  playTone(output, 520, t, 0.08, 'square', 1.0, 0.001);
  playTone(output, 440, t + 0.09, 0.08, 'square', 1.0, 0.001);
  playTone(output, 260, t + 0.18, 0.15, 'square', 1.0, 0.001);
}

function playMetalStrike(output: AudioNode, t: number) {
  playTone(output, 2200, t, 0.05, 'square', 0.9, 0.001);
  playSweep(output, 1600, 150, t + 0.02, 0.2, 'sawtooth', 1.0);
}

function playEmergencyBuzz(output: AudioNode, t: number) {
  // Acil İkaz Hörnü: Depo zemininde yankılanan güçlü çift buzzy ikaz kornosu
  // 1. İkaz Korna Vuruşu (Buzzy Düşük Frekans)
  playTone(output, 260, t, 0.15, 'sawtooth', 0.9, 0.003);
  playTone(output, 130, t, 0.16, 'square', 0.85, 0.003);
  playThump(output, t, 110, 0.13, 0.95);

  // 2. İkaz Korna Vuruşu (Daha Yüksek ve Sert)
  const t2 = t + 0.17;
  playTone(output, 320, t2, 0.20, 'sawtooth', 1.0, 0.003);
  playTone(output, 160, t2, 0.22, 'square', 0.9, 0.003);
  playThump(output, t2, 130, 0.16, 1.0);
}

export type SoundCategory = 'success' | 'failure' | 'duplicate' | 'exceeded' | 'completion' | 'not_found';

export async function triggerHaptic(category: SoundCategory) {
  const settings = loadMobileAudioSettings();
  if (!settings.hapticsEnabled) return;
  try {
    if (category === 'success' || category === 'completion') {
      await Haptics.notification({ type: NotificationType.Success });
    } else if (category === 'exceeded' || category === 'duplicate' || category === 'not_found') {
      await Haptics.notification({ type: NotificationType.Warning });
    } else {
      await Haptics.notification({ type: NotificationType.Error });
    }
  } catch {
    // Haptics might not be available in browser mode
  }
}

export async function triggerTapHaptic() {
  const settings = loadMobileAudioSettings();
  if (!settings.hapticsEnabled) return;
  try {
    await Haptics.impact({ style: ImpactStyle.Light });
  } catch {
    // ignore
  }
}

export function playMobileSound(category: SoundCategory, customSettings?: MobileAudioSettings) {
  const s = customSettings ?? loadMobileAudioSettings();
  void triggerHaptic(category);
  if (!s.enabled) return;

  const t = getContext().currentTime;
  const dur = category === 'completion' ? 1.8 : 0.6;
  const output = createMasterChain(s, t, t + dur);

  if (category === 'completion') {
    playMinecraftLevelUp(output, t);
  } else if (category === 'success') {
    switch (s.successSound) {
      case 'minecraft_levelup': playMinecraftLevelUp(output, t); break;
      case 'industrial_laser': playIndustrialLaser(output, t); break;
      case 'hyper_beep': playHyperBeep(output, t); break;
      case 'cyber_chime': default: playCyberChime(output, t); break;
    }
  } else if (category === 'duplicate') {
    playDuplicateSound(output, t);
  } else if (category === 'exceeded') {
    playExceededSound(output, t);
  } else if (category === 'not_found') {
    playEmergencyBuzz(output, t);
  } else {
    switch (s.failureSound) {
      case 'hyper_error': playHyperError(output, t); break;
      case 'metal_strike': playMetalStrike(output, t); break;
      case 'emergency_buzz': playEmergencyBuzz(output, t); break;
      case 'warehouse_alarm': default: playWarehouseAlarm(output, t); break;
    }
  }
}
