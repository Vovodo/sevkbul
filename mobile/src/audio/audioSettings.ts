export type SuccessSoundId = 'minecraft_levelup' | 'cyber_chime' | 'industrial_laser' | 'hyper_beep';
export type FailureSoundId = 'warehouse_alarm' | 'hyper_error' | 'metal_strike' | 'emergency_buzz';

export interface MobileAudioSettings {
  enabled: boolean;
  hapticsEnabled: boolean;
  volume: number; // 0.1 - 1.0
  successSound: SuccessSoundId;
  failureSound: FailureSoundId;
}

const STORAGE_KEY = 'sevkbul_mobile_audio_settings';

export const DEFAULT_MOBILE_AUDIO_SETTINGS: MobileAudioSettings = {
  enabled: true,
  hapticsEnabled: true,
  volume: 0.9,
  successSound: 'minecraft_levelup',
  failureSound: 'warehouse_alarm',
};

export function loadMobileAudioSettings(): MobileAudioSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_MOBILE_AUDIO_SETTINGS };
    return { ...DEFAULT_MOBILE_AUDIO_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_MOBILE_AUDIO_SETTINGS };
  }
}

export function saveMobileAudioSettings(settings: MobileAudioSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // ignore
  }
}
