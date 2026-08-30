import { playResultSound, warmupAudioEngine } from './audioEngine';

export type ScanResultType =
  | 'SEVKİYAT ÜRÜNÜ'
  | 'SEVKİYAT DIŞI'
  | 'ETİKET BULUNAMADI'
  | 'ZATEN OKUTULDU'
  | 'MİKTAR AŞILDI';

const SUCCESS_RESULTS = new Set<string>(['SEVKİYAT ÜRÜNÜ']);
const DUPLICATE_RESULTS = new Set<string>(['ZATEN OKUTULDU']);
const EXCEEDED_RESULTS = new Set<string>(['MİKTAR AŞILDI']);
const NOT_FOUND_RESULTS = new Set<string>(['ETİKET BULUNAMADI']);

export function initAudio() {
  warmupAudioEngine();
}

export function playScanSound(result: ScanResultType | 'COMPLETE') {
  if (result === 'COMPLETE') {
    playResultSound('completion');
  } else if (SUCCESS_RESULTS.has(result)) {
    playResultSound('success');
  } else if (DUPLICATE_RESULTS.has(result)) {
    playResultSound('duplicate');
  } else if (EXCEEDED_RESULTS.has(result)) {
    playResultSound('exceeded');
  } else if (NOT_FOUND_RESULTS.has(result)) {
    playResultSound('not_found');
  } else {
    playResultSound('failure');
  }
}

export function getResultStyle(result: string) {
  switch (result) {
    case 'SEVKİYAT ÜRÜNÜ':
      return { bg: '#059669', icon: '✓', color: '#fff' };
    case 'SEVKİYAT DIŞI':
      return { bg: '#dc2626', icon: '✕', color: '#fff' };
    case 'ETİKET BULUNAMADI':
      return { bg: '#d97706', icon: '⚠', color: '#fff' };
    case 'ZATEN OKUTULDU':
      return { bg: '#7c3aed', icon: '⚠', color: '#fff' };
    case 'MİKTAR AŞILDI':
      return { bg: '#ea580c', icon: '🚫', color: '#fff' };
    default:
      return { bg: '#6b7280', icon: '?', color: '#fff' };
  }
}
