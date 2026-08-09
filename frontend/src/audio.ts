import { playResultSound, warmupAudioEngine } from './audioEngine';

export type ScanResultType =
  | 'SEVKİYAT ÜRÜNÜ'
  | 'SEVKİYAT DIŞI'
  | 'ETİKET BULUNAMADI'
  | 'ZATEN OKUTULDU';

const SUCCESS_RESULTS = new Set<string>(['SEVKİYAT ÜRÜNÜ', 'COMPLETE']);
const DUPLICATE_RESULTS = new Set<string>(['ZATEN OKUTULDU']);

export function initAudio() {
  warmupAudioEngine();
}

export function playScanSound(result: ScanResultType | 'COMPLETE') {
  if (SUCCESS_RESULTS.has(result)) {
    playResultSound('success');
  } else if (DUPLICATE_RESULTS.has(result)) {
    playResultSound('duplicate');
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
    default:
      return { bg: '#6b7280', icon: '?', color: '#fff' };
  }
}
