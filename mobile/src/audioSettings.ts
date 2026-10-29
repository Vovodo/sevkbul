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
  { id: 'cyber_chime', label: 'Siber melodi', desc: 'Kristal sentezör arpeji' },
  { id: 'industrial_laser', label: 'Endüstriyel lazer', desc: 'Uzaktan duyulan çift lazer ve onay çınlaması' },
  { id: 'hyper_beep', label: 'Hiper okuyucu bip', desc: 'El terminali tarzı yüksek frekanslı çift bip' },
  { id: 'sonic_chime', label: 'Sonik akort', desc: 'Üç notalı parlak onay akordu' },
  { id: 'stadium_horn', label: 'Depo onay kornası', desc: 'Gürültülü ortamda ayırt edilen üç notalı korna' },
];

export const FAILURE_SOUND_OPTIONS: { id: FailureSoundId; label: string; desc: string }[] = [
  { id: 'warehouse_alarm', label: 'Depo ikaz sireni', desc: 'Uzaktan duyulan ritmik çift ikaz' },
  { id: 'hyper_error', label: 'Hiper red ikazı', desc: 'Üçlü sert vuruş' },
  { id: 'metal_strike', label: 'Metalik iptal', desc: 'Sert metalik darbe ve alçalan ikaz' },
  { id: 'emergency_buzz', label: 'Acil ikaz kornası', desc: 'Depo zemininde yankılanan çift ikaz' },
  { id: 'sub_impact_alarm', label: 'Ağır ikaz darbesi', desc: 'Derin vuruş ve alçalan siren' },
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
