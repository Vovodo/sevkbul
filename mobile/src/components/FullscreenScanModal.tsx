import { useEffect } from 'react';
import { X, CheckCircle, AlertTriangle, Ban, AlertCircle, XCircle } from 'lucide-react';
import { ScanResponse } from '../api';
import { ScreenOrientation } from '@capacitor/screen-orientation';
import { Capacitor } from '@capacitor/core';
import { triggerTapHaptic } from '../audio/audioEngine';

interface FullscreenScanModalProps {
  isOpen: boolean;
  onClose: () => void;
  lastScan: ScanResponse | null;
  onScan?: (label: string) => void;
  isScanning?: boolean;
}

export default function FullscreenScanModal({
  isOpen,
  onClose,
  lastScan,
}: FullscreenScanModalProps) {
  // Ekranı otomatik yatay (landscape) yap ve tarayıcıyı tam ekran yap (klavye AÇILMAZ)
  useEffect(() => {
    if (!isOpen) return;

    // Tarayıcı / Web fullscreen modunu tetikle
    if (document.documentElement.requestFullscreen) {
      document.documentElement.requestFullscreen().catch(() => {});
    }

    // Ekranı yatay (landscape) kilitle
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
      // Çıkışta tam ekrandan çık ve ekranı normale döndür
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      }

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
  }, [isOpen]);

  if (!isOpen) return null;

  const getBadgeDetails = (result: string) => {
    switch (result) {
      case 'SEVKİYAT ÜRÜNÜ':
        return { bgClass: 'res-success', icon: <CheckCircle size={72} />, title: 'SEVKİYAT ÜRÜNÜ' };
      case 'MİKTAR AŞILDI':
        return { bgClass: 'res-exceeded', icon: <Ban size={72} />, title: 'MİKTAR AŞILDI' };
      case 'ZATEN OKUTULDU':
        return { bgClass: 'res-duplicate', icon: <AlertCircle size={72} />, title: 'ZATEN OKUTULDU' };
      case 'ETİKET BULUNAMADI':
        return { bgClass: 'res-notfound', icon: <AlertTriangle size={72} />, title: 'ETİKET BULUNAMADI' };
      case 'SEVKİYAT DIŞI':
      default:
        return { bgClass: 'res-failure', icon: <XCircle size={72} />, title: 'SEVKİYAT DIŞI' };
    }
  };

  const badge = lastScan ? getBadgeDetails(lastScan.result) : null;

  const handleClose = () => {
    void triggerTapHaptic();
    onClose();
  };

  return (
    <div className="mobile-fs-overlay" role="dialog" aria-modal="true">
      {/* Minimal Floating Close Button */}
      <button
        type="button"
        className="mobile-fs-floating-close-btn"
        onClick={handleClose}
        title="Tam Ekrandan Çık"
        aria-label="Kapat"
      >
        <X size={24} />
      </button>

      {/* Sıfıra Sıfır Tam Ekran Bildirim Kartı */}
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
            <span className="mobile-fs-hint">Barkod veya QR kod okutulduğunda sonuç %100 tam ekran burada belirecektir.</span>
          </div>
        )}
      </div>
    </div>
  );
}
