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

/**
 * 30-40 metre depo mesafesi için Maksimum Ses Çıkış Zinciri (Peak Limiter + 2.8kHz Ear Sensitivity Boost)
 */
function createSuccessChain(settings: AudioSettings, startTime: number, endTime: number) {
  const audioCtx = getContext();
  const input = audioCtx.createGain();

  // İnsan kulağının en hassas olduğu 2.8 kHz frekans boost (Depoda 30-40 metreden duyulması için)
  const earBoost = audioCtx.createBiquadFilter();
  earBoost.type = 'peaking';
  earBoost.frequency.value = 2800;
  earBoost.Q.value = 1.2;
  earBoost.gain.value = 6.0;

  const bass = audioCtx.createBiquadFilter();
  bass.type = 'lowshelf';
  bass.frequency.value = 120;
  bass.gain.value = 6 + settings.bassBoost * 10;

  const master = audioCtx.createGain();
  // Maksimum ses seviyesi (Sistemsel fulleme)
  master.gain.setValueAtTime(settings.volume * 3.5, startTime);

  // Brickwall Kompresör (Maksimum RMS ses şiddeti, bozulmayı önleyen dijital tavan)
  const comp = audioCtx.createDynamicsCompressor();
  comp.threshold.value = -1.5;
  comp.knee.value = 2.0;
  comp.ratio.value = 16.0;
  comp.attack.value = 0.001;
  comp.release.value = 0.05;

  input.connect(earBoost);
  earBoost.connect(bass);
  bass.connect(master);
  master.connect(comp);
  comp.connect(audioCtx.destination);

  const fade = audioCtx.createGain();
  fade.gain.setValueAtTime(1, startTime);
  fade.gain.setValueAtTime(1, Math.max(startTime, endTime - 0.03));
  fade.gain.linearRampToValueAtTime(0.001, endTime);
  fade.connect(input);
  return fade;
}

/**
 * 30-40 metre depo mesafesi için Maksimum İkaz Ses Zinciri
 */
function createFailureChain(settings: AudioSettings, startTime: number, endTime: number) {
  const audioCtx = getContext();
  const input = audioCtx.createGain();

  // Makine gürültüsünü delen 1.8 kHz & 3.2 kHz sert ikaz filtresi
  const earBoost = audioCtx.createBiquadFilter();
  earBoost.type = 'peaking';
  earBoost.frequency.value = 2200;
  earBoost.Q.value = 1.0;
  earBoost.gain.value = 8.0;

  const bass = audioCtx.createBiquadFilter();
  bass.type = 'lowshelf';
  bass.frequency.value = 100;
  bass.gain.value = 10 + settings.bassBoost * 12;

  const master = audioCtx.createGain();
  // Maksimum ikaz seviyesi (Sistemsel fulleme)
  master.gain.setValueAtTime(settings.volume * 4.5, startTime);

  const comp = audioCtx.createDynamicsCompressor();
  comp.threshold.value = -1.0;
  comp.knee.value = 1.0;
  comp.ratio.value = 20.0;
  comp.attack.value = 0.0005;
  comp.release.value = 0.04;

  input.connect(earBoost);
  earBoost.connect(bass);
  bass.connect(master);
  master.connect(comp);
  comp.connect(audioCtx.destination);

  const fade = audioCtx.createGain();
  fade.gain.setValueAtTime(1, startTime);
  fade.gain.setValueAtTime(1, Math.max(startTime, endTime - 0.02));
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
  playTone(output, freq * 2, start, dur * 0.5, 'square', peak * 0.25, 0.002);
}

/* ─── BAŞARI SESLERİ (30-40M UZAKTAN DUYULAN YÜKSEK HASSASİYETLİ PROFiLLER) ─── */

/** Siber Melodi (KORUNAN VE SESİ YÜKSELTİLEN FAVORİ SES) */
function playSuccessCyberChime(output: AudioNode, t: number) {
  playThump(output, t, 65, 0.12, 1.0);
  const chimeNotes = [523.25, 659.25, 783.99, 1046.50, 1318.51, 1567.98];
  chimeNotes.forEach((f, i) => {
    const s = t + 0.03 + i * 0.075;
    playTone(output, f, s, 0.32, 'sine', 0.95, 0.002);
    playTone(output, f * 2, s + 0.004, 0.22, 'triangle', 0.45, 0.002);
  });
}

/** Endüstriyel Lazer (Çift Lazer Süpürme + Tiz Kristal Çınlama) */
function playSuccessIndustrialLaser(output: AudioNode, t: number) {
  playSweep(output, 1400, 2800, t, 0.08, 'sawtooth', 0.85);
  playSweep(output, 1800, 3400, t + 0.07, 0.09, 'sine', 0.95);
  playTone(output, 3135.96, t + 0.15, 0.45, 'sine', 0.9, 0.002);
  playTone(output, 1567.98, t + 0.15, 0.45, 'triangle', 0.5, 0.003);
}

/** Hiper Okuyucu Bip (El Terminali Tarzı Ultra-Tiz Çift Bip) */
function playSuccessHyperBeep(output: AudioNode, t: number) {
  playTone(output, 2400, t, 0.08, 'square', 0.9, 0.001);
  playTone(output, 4800, t, 0.06, 'sine', 0.3, 0.001);
  playTone(output, 3200, t + 0.09, 0.12, 'square', 1.0, 0.001);
  playTone(output, 6400, t + 0.09, 0.08, 'sine', 0.35, 0.001);
}

/** Sonik Akort (Yüksek Enerjili 3 Notalı Akort + Tınlama) */
function playSuccessSonicChime(output: AudioNode, t: number) {
  playThump(output, t, 80, 0.1, 1.0);
  const notes = [1046.50, 1318.51, 1567.98];
  notes.forEach((f, i) => {
    const s = t + 0.02 + i * 0.065;
    playTone(output, f, s, 0.28, 'triangle', 0.9, 0.002);
    playTone(output, f * 2, s, 0.2, 'sine', 0.4, 0.002);
  });
  playTone(output, 2093.00, t + 0.2, 0.5, 'sine', 0.8, 0.002);
}

/** Depo Onay Kornosu (Makine Sesini Yırtan Güçlü 3 Notalı Pirinç Korno) */
function playSuccessStadiumHorn(output: AudioNode, t: number) {
  playThump(output, t, 70, 0.15, 1.0);
  const hornFreqs = [880.00, 1108.73, 1318.51];
  hornFreqs.forEach((f) => {
    playTone(output, f, t + 0.03, 0.35, 'sawtooth', 0.6, 0.004);
    playTone(output, f * 0.5, t + 0.03, 0.35, 'triangle', 0.4, 0.004);
  });
  playTone(output, 1760.00, t + 0.12, 0.4, 'sine', 0.5, 0.003);
}

/* ─── TEKRAR OKUTMA SESİ (ZATEN OKUTULDU — Başarıya yakın hoş, ama ayırt edilebilir) ─── */

/**
 * Tekrar okutma için özel ses zinciri:
 * Başarı zinciri ile aynı yapıda ama biraz daha yumuşak ve farklı frekans profili.
 */
function createDuplicateChain(settings: AudioSettings, startTime: number, endTime: number) {
  const audioCtx = getContext();
  const input = audioCtx.createGain();

  // Başarı sesinden ayırt etmek için 2.2 kHz civarı boost (daha sıcak ton)
  const earBoost = audioCtx.createBiquadFilter();
  earBoost.type = 'peaking';
  earBoost.frequency.value = 2200;
  earBoost.Q.value = 1.5;
  earBoost.gain.value = 5.0;

  const bass = audioCtx.createBiquadFilter();
  bass.type = 'lowshelf';
  bass.frequency.value = 130;
  bass.gain.value = 4 + settings.bassBoost * 8;

  const master = audioCtx.createGain();
  master.gain.setValueAtTime(settings.volume * 3.0, startTime);

  const comp = audioCtx.createDynamicsCompressor();
  comp.threshold.value = -2.0;
  comp.knee.value = 3.0;
  comp.ratio.value = 12.0;
  comp.attack.value = 0.001;
  comp.release.value = 0.06;

  input.connect(earBoost);
  earBoost.connect(bass);
  bass.connect(master);
  master.connect(comp);
  comp.connect(audioCtx.destination);

  const fade = audioCtx.createGain();
  fade.gain.setValueAtTime(1, startTime);
  fade.gain.setValueAtTime(1, Math.max(startTime, endTime - 0.03));
  fade.gain.linearRampToValueAtTime(0.001, endTime);
  fade.connect(input);
  return fade;
}

/**
 * Tekrar Okutma Sesi: Yumuşak Çift Zil
 * Başarı sesine benzer hoş bir ton ama ALÇALAN çift nota ile ayırt edilir.
 * Başarı sesi yükselir → Tekrar okutma sesi alçalır (kulak hemen farkı anlar)
 */
function playDuplicateSound(output: AudioNode, t: number) {
  // Yüksek notadan başla, alçalarak çift zil çal
  playTone(output, 1567.98, t, 0.22, 'sine', 0.85, 0.002);       // Yüksek tiz zil
  playTone(output, 3135.96, t, 0.15, 'triangle', 0.3, 0.002);    // Harmonik parıltı
  playTone(output, 1046.50, t + 0.14, 0.28, 'sine', 0.9, 0.002); // Alçalan ikinci zil
  playTone(output, 2093.00, t + 0.14, 0.2, 'triangle', 0.35, 0.002); // Harmonik
  // Yumuşak bas dolgu (derinlik hissi)
  playTone(output, 220, t, 0.35, 'sine', 0.5, 0.005);
}

const DUPLICATE_DURATION = 0.5;

/* ─── BAŞARISIZ SESLERİ (30-40M UZAKTAN NET AYIRT EDİLEN İKAZ PROFiLLERİ) ─── */

/** Depo İkaz Sireni (Ritmik Çift Testere İkaz Sireni) */
function playFailureWarehouseAlarm(output: AudioNode, t: number) {
  playThump(output, t, 120, 0.12, 1.0);
  playSweep(output, 850, 220, t + 0.02, 0.16, 'sawtooth', 1.0);
  playThump(output, t + 0.14, 120, 0.12, 1.0);
  playSweep(output, 950, 180, t + 0.16, 0.2, 'sawtooth', 1.0);
}

/** Hiper Red İkazı (Keskin Kare Dalga 3'lü Sert Vuruş) */
function playFailureHyperError(output: AudioNode, t: number) {
  playTone(output, 520, t, 0.08, 'square', 1.0, 0.001);
  playTone(output, 440, t + 0.09, 0.08, 'square', 1.0, 0.001);
  playTone(output, 260, t + 0.18, 0.15, 'square', 1.0, 0.001);
  playSweep(output, 600, 100, t + 0.18, 0.18, 'sawtooth', 0.7);
}

/** Metalik İptal (Tiz Metal Sert Darbe + Alçalan İkaz) */
function playFailureMetalStrike(output: AudioNode, t: number) {
  playTone(output, 2200, t, 0.05, 'square', 0.9, 0.001);
  playSweep(output, 1600, 150, t + 0.02, 0.22, 'sawtooth', 1.0);
  playThump(output, t + 0.05, 90, 0.18, 1.0);
}

/** Acil İkaz Hörnü (Depo Zemininde Yankılanan Çift İkaz Kornosu) */
function playFailureEmergencyBuzz(output: AudioNode, t: number) {
  playTone(output, 380, t, 0.14, 'square', 0.9, 0.002);
  playTone(output, 1800, t, 0.14, 'sawtooth', 0.5, 0.002);
  playTone(output, 380, t + 0.16, 0.18, 'square', 1.0, 0.002);
  playTone(output, 1800, t + 0.16, 0.18, 'sawtooth', 0.55, 0.002);
}

/** Ağır İkaz Darbesi (Derin Vurmalı Bas + Dual Siren) */
function playFailureSubImpactAlarm(output: AudioNode, t: number) {
  playThump(output, t, 45, 0.25, 1.0);
  playSweep(output, 900, 120, t + 0.02, 0.26, 'square', 0.95);
  playSweep(output, 600, 90, t + 0.14, 0.22, 'sawtooth', 0.85);
}

const SUCCESS_DURATIONS: Record<SuccessSoundId, number> = {
  cyber_chime: 0.8,
  industrial_laser: 0.65,
  hyper_beep: 0.25,
  sonic_chime: 0.75,
  stadium_horn: 0.8,
};

const FAILURE_DURATIONS: Record<FailureSoundId, number> = {
  warehouse_alarm: 0.42,
  hyper_error: 0.38,
  metal_strike: 0.35,
  emergency_buzz: 0.4,
  sub_impact_alarm: 0.45,
};

function playSuccessPreset(id: SuccessSoundId, settings: AudioSettings) {
  const t = getContext().currentTime;
  const dur = SUCCESS_DURATIONS[id] || 0.8;
  const output = createSuccessChain(settings, t, t + dur);
  switch (id) {
    case 'industrial_laser': playSuccessIndustrialLaser(output, t); break;
    case 'hyper_beep': playSuccessHyperBeep(output, t); break;
    case 'sonic_chime': playSuccessSonicChime(output, t); break;
    case 'stadium_horn': playSuccessStadiumHorn(output, t); break;
    case 'cyber_chime': default: playSuccessCyberChime(output, t); break;
  }
}

function playFailurePreset(id: FailureSoundId, settings: AudioSettings) {
  const t = getContext().currentTime;
  const dur = FAILURE_DURATIONS[id] || 0.4;
  const output = createFailureChain(settings, t, t + dur);
  switch (id) {
    case 'hyper_error': playFailureHyperError(output, t); break;
    case 'metal_strike': playFailureMetalStrike(output, t); break;
    case 'emergency_buzz': playFailureEmergencyBuzz(output, t); break;
    case 'sub_impact_alarm': playFailureSubImpactAlarm(output, t); break;
    case 'warehouse_alarm': default: playFailureWarehouseAlarm(output, t); break;
  }
}


/* ─── MİKTAR AŞILDI İKAZ SESİ (Turuncu Alarm — SEVKİYAT DOLU) ─── */

/**
 * MİKTAR AŞILDI: Keskin uyarı - çift darbe + alçalan sweep
 * Hata sesinden farklı, daha "dur" diyen otoriter bir ton
 */
function playExceededSound(output: AudioNode, t: number) {
  // Çift sert kısa darbe
  playTone(output, 1800, t, 0.06, 'square', 0.95, 0.001);
  playTone(output, 1800, t + 0.08, 0.06, 'square', 0.95, 0.001);
  // Alçalan uyarı sweep
  playSweep(output, 1200, 300, t + 0.16, 0.25, 'sawtooth', 0.8);
  // Derin bas vuruş
  playThump(output, t + 0.16, 60, 0.2, 0.9);
}

const EXCEEDED_DURATION = 0.5;

/* ─── SEVKİYAT TAMAMLANDI: MINECRAFT LEVEL UP SESİ ─── */

/**
 * Otantik Minecraft Level Up Ses Efekti:
 * Hızla yükselen 12 notalı arpej (Bb4 -> Db7) + retro çan/arp tınısı + kristal parıltılı bitiş akoru.
 * Duyulduğu an anında tanınan ve yüksek dopamin hissi veren efsanevi Minecraft Level Up efekti.
 */
function playMinecraftLevelUp(output: AudioNode, t: number) {
  // Minecraft Level Up notaları (Hz)
  const mcNotes = [
    466.16, // Bb4 (0.00s)
    554.37, // Db5 (0.05s)
    622.25, // Eb5 (0.10s)
    739.99, // Gb5 (0.15s)
    830.61, // Ab5 (0.20s)
    932.33, // Bb5 (0.25s)
    1108.73, // Db6 (0.30s)
    1244.51, // Eb6 (0.35s)
    1479.98, // Gb6 (0.40s)
    1661.22, // Ab6 (0.45s)
    1864.66, // Bb6 (0.50s)
    2217.46, // Db7 (0.55s - Doruk)
  ];

  // Hızlı yükselen basamaklar
  mcNotes.forEach((freq, i) => {
    const noteStart = t + i * 0.048;
    const isHigh = i >= 8;
    const dur = isHigh ? 0.35 : 0.18;
    const peak = isHigh ? 0.85 : 0.7;

    // Ana çan/arp notası (Triangle + Sine karışımı - Minecraft tınısı)
    playTone(output, freq, noteStart, dur, 'triangle', peak, 0.002);
    playTone(output, freq, noteStart + 0.001, dur, 'sine', peak * 0.7, 0.002);
    // Retro kare dalga vuruşu (Minecraft ses motorunun karakteristik tıkırtısı)
    playTone(output, freq * 0.5, noteStart, 0.04, 'square', 0.15, 0.001);
  });

  // Doruk noktasında kristal parıltılı çınlama akoru (Db6 + F6 + Ab6 + Db7)
  const chordStart = t + 0.56;
  playTone(output, 1108.73, chordStart, 0.9, 'triangle', 0.5, 0.003); // Db6
  playTone(output, 1396.91, chordStart + 0.01, 0.95, 'sine', 0.45, 0.003); // F6
  playTone(output, 1661.22, chordStart + 0.02, 1.0, 'sine', 0.5, 0.003); // Ab6
  playTone(output, 2217.46, chordStart + 0.03, 1.1, 'sine', 0.6, 0.003); // Db7
  playTone(output, 4434.92, chordStart + 0.04, 0.6, 'sine', 0.25, 0.003); // Kristal Shimmer

  // Sıcak bas alt dolgu
  playTone(output, 138.59, chordStart, 0.8, 'sine', 0.35, 0.01); // Db3
}

const COMPLETION_DURATION = 1.8;

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

export function playResultSound(
  category: 'success' | 'failure' | 'duplicate' | 'exceeded' | 'completion' | 'not_found',
  settings?: AudioSettings,
) {
  const s = settings ?? loadAudioSettings();
  if (!s.enabled) return;

  if (category === 'success') {
    playSuccessPreset(s.successSound, s);
  } else if (category === 'duplicate') {
    const t = getContext().currentTime;
    const output = createDuplicateChain(s, t, t + DUPLICATE_DURATION);
    playDuplicateSound(output, t);
  } else if (category === 'exceeded') {
    const t = getContext().currentTime;
    const output = createFailureChain(s, t, t + EXCEEDED_DURATION);
    playExceededSound(output, t);
  } else if (category === 'completion') {
    const t = getContext().currentTime;
    const output = createSuccessChain(s, t, t + COMPLETION_DURATION);
    playMinecraftLevelUp(output, t);
  } else if (category === 'not_found') {
    // ETİKET BULUNAMADI: "Acil İkaz Hörnü 🔊" (Depo zemininde yankılanan çift buzzy ikaz kornosu)
    const t = getContext().currentTime;
    const dur = FAILURE_DURATIONS.emergency_buzz || 0.4;
    const output = createFailureChain(s, t, t + dur);
    playFailureEmergencyBuzz(output, t);
  } else {
    playFailurePreset(s.failureSound, s);
  }
}
