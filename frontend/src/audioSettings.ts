export type SuccessSoundId =
  | 'cyber_chime'
  | 'industrial_laser'
  | 'hyper_beep'
  | 'sonic_chime'
  | 'stadium_horn';

export type FailureSoundId =
  | 'warehouse_alarm'
  | 'hyper_error'
  | 'metal_strike'
  | 'emergency_buzz'
  | 'sub_impact_alarm';

export interface AudioSettings {
  enabled: boolean;
  volume: number;
  bassBoost: number;
  successSound: SuccessSoundId;
  failureSound: FailureSoundId;
}

export const SUCCESS_SOUND_OPTIONS: { id: SuccessSoundId; label: string; desc: string }[] = [
  { id: 'cyber_chime', label: 'Siber Melodi ⭐', desc: 'Gelecek nesil kristal sentezör arpeji — favori onay sesi' },
  { id: 'industrial_laser', label: 'Endüstriyel Lazer 🚀', desc: '40m mesafeden duyulan çift yüksek lazer + tiz onay çınlaması' },
  { id: 'hyper_beep', label: 'Hiper Okuyucu Bip ⚡', desc: 'El terminali tarzı Ultra-Yüksek frekanslı çift bip (2.4kHz - 3.2kHz)' },
  { id: 'sonic_chime', label: 'Sonik Akort 🎵', desc: 'Parlak ve yüksek enerjili 3 notalı kristal onay akordu' },
  { id: 'stadium_horn', label: 'Depo Onay Kornosu 🎺', desc: 'Gürültülü depo ortamında makine sesini yırtan 3 notalı güçlü kornolar' },
];

export const FAILURE_SOUND_OPTIONS: { id: FailureSoundId; label: string; desc: string }[] = [
  { id: 'warehouse_alarm', label: 'Depo İkaz Sireni 🚨', desc: '30-40 metre uzaklıktan net duyulan ritmik çift testere ikaz sireni (Önerilen)' },
  { id: 'hyper_error', label: 'Hiper Red İkazı 💥', desc: 'Keskin kare dalga 3\'lü sert vuruş — anında fark edilir red' },
  { id: 'metal_strike', label: 'Metalik İptal 🔨', desc: 'Tiz ve sert metalik darbe + hızlı alçalan frekans ikazı' },
  { id: 'emergency_buzz', label: 'Acil İkaz Hörnü 🔊', desc: 'Depo zemininde yankılanan çift buzzy ikaz kornosu' },
  { id: 'sub_impact_alarm', label: 'Ağır İkaz Darbesi 💣', desc: 'Derin vurmalı bas + keskin alçalan dual siren' },
];

const STORAGE_KEY = 'sevkiyatbul_audio_settings';

export const DEFAULT_AUDIO_SETTINGS: AudioSettings = {
  enabled: true,
  volume: 1.0,
  bassBoost: 0.8,
  successSound: 'cyber_chime',
  failureSound: 'warehouse_alarm',
};

export function loadAudioSettings(): AudioSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_AUDIO_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<AudioSettings>;
    return { ...DEFAULT_AUDIO_SETTINGS, ...parsed };
  } catch {
    return { ...DEFAULT_AUDIO_SETTINGS };
  }
}

export function saveAudioSettings(settings: AudioSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export type AudioSettingsListener = (settings: AudioSettings) => void;
const listeners = new Set<AudioSettingsListener>();

export function subscribeAudioSettings(listener: AudioSettingsListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function updateAudioSettings(partial: Partial<AudioSettings>): AudioSettings {
  const next = { ...loadAudioSettings(), ...partial };
  saveAudioSettings(next);
  listeners.forEach(fn => fn(next));
  return next;
}
