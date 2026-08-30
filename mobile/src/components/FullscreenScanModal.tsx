import { useEffect, useRef, useCallback } from 'react';
import { Minimize2, CheckCircle, AlertTriangle, Ban, AlertCircle, XCircle } from 'lucide-react';
import { ScanResponse } from '../api';
import { ScreenOrientation } from '@capacitor/screen-orientation';
import { Capacitor } from '@capacitor/core';
import { triggerTapHaptic } from '../audio/audioEngine';

interface FullscreenScanModalProps {
  isOpen: boolean;
  onClose: () => void;
  lastScan: ScanResponse | null;
  onScan: (label: string) => void;
  isScanning?: boolean;
}

export default function FullscreenScanModal({
  isOpen,
  onClose,
  lastScan,
  onScan,
  isScanning = false,
}: FullscreenScanModalProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const focusInput = useCallback(() => {
    setTimeout(() => {
      inputRef.current?.focus({ preventScroll: true });
    }, 100);
  }, []);

  // Lock orientation to landscape or optimize for full screen when open
  useEffect(() => {
    if (!isOpen) return;

    focusInput();

    // Lock orientation if native platform supports it
    if (Capacitor.isNativePlatform()) {
      ScreenOrientation.lock({ orientation: 'landscape' }).catch(() => {});
    } else {
      try {
        const screenAny = window.screen as unknown as { orientation?: { lock?: (o: string) => Promise<void> } };
        if (screenAny.orientation?.lock) {
          screenAny.orientation.lock('landscape').catch(() => {});
        }
      } catch {
        // ignore
      }
    }

    return () => {
      if (Capacitor.isNativePlatform()) {
        ScreenOrientation.unlock().catch(() => {});
      } else {
        try {
          const screenAny = window.screen as unknown as { orientation?: { unlock?: () => void } };
          if (screenAny.orientation?.unlock) {
            screenAny.orientation.unlock();
          }
        } catch {
          // ignore
        }
      }
    };
  }, [isOpen, focusInput]);

  if (!isOpen) return null;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const val = e.currentTarget.value.trim();
      if (val) {
        onScan(val);
        e.currentTarget.value = '';
      }
    }
  };

  const getBadgeDetails = (result: string) => {
    switch (result) {
      case 'SEVKİYAT ÜRÜNÜ':
        return { bgClass: 'res-success', icon: <CheckCircle size={64} />, title: 'SEVKİYAT ÜRÜNÜ' };
      case 'MİKTAR AŞILDI':
        return { bgClass: 'res-exceeded', icon: <Ban size={64} />, title: 'MİKTAR AŞILDI' };
      case 'ZATEN OKUTULDU':
        return { bgClass: 'res-duplicate', icon: <AlertCircle size={64} />, title: 'ZATEN OKUTULDU' };
      case 'ETİKET BULUNAMADI':
        return { bgClass: 'res-notfound', icon: <AlertTriangle size={64} />, title: 'ETİKET BULUNAMADI' };
      case 'SEVKİYAT DIŞI':
      default:
        return { bgClass: 'res-failure', icon: <XCircle size={64} />, title: 'SEVKİYAT DIŞI' };
    }
  };

  const badge = lastScan ? getBadgeDetails(lastScan.result) : null;

  return (
    <div className="mobile-fs-overlay" role="dialog" aria-modal="true" onClick={focusInput}>
      {/* Invisible auto-focused barcode input */}
      <input
        ref={inputRef}
        type="text"
        className="mobile-fs-hidden-input"
        onKeyDown={handleKeyDown}
        disabled={isScanning}
        autoFocus
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck="false"
      />

      {/* Top action bar */}
      <div className="mobile-fs-header">
        <span className="mobile-fs-live-badge">🔴 CANLI OKUTMA EKRANI</span>
        <button
          type="button"
          className="mobile-fs-close-btn"
          onClick={() => {
            void triggerTapHaptic();
            onClose();
          }}
        >
          <Minimize2 size={18} />
          <span>Tam Ekrandan Çık</span>
        </button>
      </div>

      {/* Main Fullscreen Display Card */}
      <div className="mobile-fs-card-wrap">
        {lastScan && badge ? (
          <div key={lastScan.label + lastScan.result} className={`mobile-fs-card ${badge.bgClass}`}>
            <div className="mobile-fs-card-icon">{badge.icon}</div>
            <div className="mobile-fs-card-title">{badge.title}</div>

            <div className="mobile-fs-details">
              <div className="mobile-fs-label-block">
                <span className="mobile-fs-meta-label">ETİKET NO</span>
                <strong className="mobile-fs-label-val font-mono">{lastScan.label}</strong>
              </div>

              <div className="mobile-fs-meta-grid">
                {lastScan.reference && (
                  <div className="mobile-fs-meta-item">
                    <span className="mobile-fs-meta-label">REFERANS</span>
                    <strong className="mobile-fs-meta-val">{lastScan.reference}</strong>
                  </div>
                )}
                {lastScan.quantity != null && (
                  <div className="mobile-fs-meta-item">
                    <span className="mobile-fs-meta-label">MİKTAR</span>
                    <strong className="mobile-fs-meta-val">{lastScan.quantity} ADET</strong>
                  </div>
                )}
                {lastScan.fifo_date && (
                  <div className="mobile-fs-meta-item">
                    <span className="mobile-fs-meta-label">FIFO TARİHİ</span>
                    <strong className="mobile-fs-meta-val font-mono">{lastScan.fifo_date}</strong>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="mobile-fs-card waiting">
            <div className="mobile-fs-waiting-dot" />
            <div className="mobile-fs-card-title">Okutma Bekleniyor...</div>
            <span className="mobile-fs-hint">Barkod veya QR kod okuttuğunuzda sonuç anında burada belirecektir.</span>
          </div>
        )}
      </div>
    </div>
  );
}
