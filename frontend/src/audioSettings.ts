export type SuccessSoundId =
  | 'triumph'
  | 'golden'
  | 'pulse'
  | 'fanfare'
  | 'cyber_chime'
  | 'crystal_bell'
  | 'majestic_arpeggio';

export type FailureSoundId =
  | 'soft'
  | 'tick'
  | 'muted'
  | 'gentle'
  | 'siren_warn'
  | 'cyber_deny'
  | 'sub_impact';

export interface AudioSettings {
  enabled: boolean;
  volume: number;
  bassBoost: number;
  successSound: SuccessSoundId;
  failureSound: FailureSoundId;
}

export const SUCCESS_SOUND_OPTIONS: { id: SuccessSoundId; label: string; desc: string }[] = [
  { id: 'triumph', label: 'Zafer Akordu', desc: 'Yükselen 4 nota + parlak final — sevkiyat ürünü' },
  { id: 'golden', label: 'Altın Ding', desc: 'Sıcak zil tonu, derin bas — hoş onay' },
  { id: 'pulse', label: 'Bas Nabız', desc: 'Ritmik bas + yükselen ton' },
  { id: 'fanfare', label: 'Tamamlama Fanfarı', desc: '6 notalık yükselen fanfar — güçlü onay' },
  { id: 'cyber_chime', label: 'Siber Melodi', desc: 'Gelecek nesil sentezör arpeji + kristal tonlar' },
  { id: 'crystal_bell', label: 'Kristal Zil', desc: 'Yüksek frekanslı zil tınlaması + derin bas darbesi' },
  { id: 'majestic_arpeggio', label: 'Majestik Arpej', desc: 'Görkemli 5 notalı yükselen arpej ve süzülen tınlama' },
];

export const FAILURE_SOUND_OPTIONS: { id: FailureSoundId; label: string; desc: string }[] = [
  { id: 'soft', label: 'Çift Bonk + Buzz', desc: 'BONK-BONK + alçalan buzz — sevkiyat dışı (önerilen)' },
  { id: 'tick', label: 'Üçlü Bonk', desc: 'BONK-BONK-BONK — yanlış okutma, çok ayırt edilir' },
  { id: 'muted', label: 'Derin Red', desc: 'İki ağır bas + sert alçalma — uzaktan net' },
  { id: 'gentle', label: 'İkili Red', desc: 'Bonk-buzz tekrarı — kısa ama belirgin' },
  { id: 'siren_warn', label: 'Endüstriyel Siren', desc: 'Yüksek uyarılı ritmik depo ikaz sireni' },
  { id: 'cyber_deny', label: 'Siber Red', desc: 'Metalik dijital buzzy frekans + anında sert alçalma' },
  { id: 'sub_impact', label: 'Derin Darbe', desc: 'Derin alt bas darbesi + keskin ikaz frekansı' },
];

const STORAGE_KEY = 'sevkiyatbul_audio_settings';

export const DEFAULT_AUDIO_SETTINGS: AudioSettings = {
  enabled: true,
  volume: 0.95,
  bassBoost: 0.9,
  successSound: 'triumph',
  failureSound: 'soft',
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
