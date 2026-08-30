import { useState, useRef, useEffect, useCallback } from 'react';
import { Camera, CornerDownLeft, XCircle, CheckCircle, AlertTriangle, Ban, AlertCircle, Maximize2 } from 'lucide-react';
import { api, ScanResponse, ShipmentProgress, RecentScan } from '../api';
import { playMobileSound, triggerTapHaptic } from '../audio/audioEngine';
import CameraScannerModal from '../components/CameraScannerModal';
import FullscreenScanModal from '../components/FullscreenScanModal';

interface ScanPageProps {
  shipments: ShipmentProgress[];
  selectedShipmentId?: number | null;
  onSelectShipment?: (id: number) => void;
  recentScans: RecentScan[];
  lastScan: ScanResponse | null;
  onSetLastScan: (scan: ScanResponse | null) => void;
  onRefreshShipments: () => void;
  onNavigateToSetup: () => void;
  onNavigateToShipments: () => void;
}

export default function ScanPage({
  shipments,
  selectedShipmentId,
  onSelectShipment,
  recentScans,
  lastScan,
  onSetLastScan,
  onRefreshShipments,
  onNavigateToSetup,
  onNavigateToShipments,
}: ScanPageProps) {
  const [scanValue, setScanValue] = useState<string>('');
  const [isScanning, setIsScanning] = useState<boolean>(false);
  const [showCamera, setShowCamera] = useState<boolean>(false);
  const [showFullscreen, setShowFullscreen] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string>('');
  const inputRef = useRef<HTMLInputElement>(null);

  const focusInput = useCallback(() => {
    setTimeout(() => {
      inputRef.current?.focus({ preventScroll: true });
    }, 50);
  }, []);

  useEffect(() => {
    focusInput();
  }, [focusInput]);

  const executeScan = useCallback(async (labelToScan: string) => {
    const trimmed = labelToScan.trim();
    if (!trimmed) return;

    setIsScanning(true);
    setErrorMsg('');

    try {
      const result = await api.scan(trimmed, selectedShipmentId);
      onSetLastScan(result);

      // Ses & Titreşim
      if (result.is_complete && result.success) {
        // Sevkiyat tamamlandıysa zafer melodisi (Minecraft Level Up)
        playMobileSound('completion');
      } else if (result.result === 'SEVKİYAT ÜRÜNÜ') {
        playMobileSound('success');
      } else if (result.result === 'ZATEN OKUTULDU') {
        playMobileSound('duplicate');
      } else if (result.result === 'MİKTAR AŞILDI') {
        playMobileSound('exceeded');
      } else {
        playMobileSound('failure');
      }

      onRefreshShipments();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Okutma sırasında hata oluştu';
      setErrorMsg(msg);
      playMobileSound('failure');
    } finally {
      setIsScanning(false);
      setScanValue('');
      focusInput();
    }
  }, [focusInput, onRefreshShipments, onSetLastScan]);



  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void executeScan(scanValue);
  };

  const handleCameraScanResult = (decodedText: string) => {
    void executeScan(decodedText);
  };

  const getResultBadgeInfo = (result: string) => {
    switch (result) {
      case 'SEVKİYAT ÜRÜNÜ':
        return { bgClass: 'res-success', icon: <CheckCircle size={28} />, title: 'SEVKİYAT ÜRÜNÜ' };
      case 'MİKTAR AŞILDI':
        return { bgClass: 'res-exceeded', icon: <Ban size={28} />, title: 'MİKTAR AŞILDI' };
      case 'ZATEN OKUTULDU':
        return { bgClass: 'res-duplicate', icon: <AlertCircle size={28} />, title: 'ZATEN OKUTULDU' };
      case 'ETİKET BULUNAMADI':
        return { bgClass: 'res-notfound', icon: <AlertTriangle size={28} />, title: 'ETİKET BULUNAMADI' };
      case 'SEVKİYAT DIŞI':
      default:
        return { bgClass: 'res-failure', icon: <XCircle size={28} />, title: 'SEVKİYAT DIŞI' };
    }
  };

  const totalScanned = shipments.reduce((sum, s) => sum + s.scanned_quantity, 0);
  const totalTarget = shipments.reduce((sum, s) => sum + s.requested_quantity, 0);
  const isAllComplete = shipments.length > 0 && shipments.every((s) => s.is_complete || s.scanned_quantity >= s.requested_quantity);

  const selectedShipment = shipments.find((s) => s.shipment_id === selectedShipmentId) || shipments[0];
  const selectedIdx = shipments.findIndex((s) => s.shipment_id === selectedShipment?.shipment_id);
  const selectedTitle = selectedShipment?.name || `${selectedIdx + 1}. Sevkiyat`;

  return (
    <div className="mobile-page scan-page">
      {/* Top Active Shipment Quick Summary Bar */}
      {shipments.length > 0 ? (
        <div className="scan-summary-bar" onClick={onNavigateToShipments}>
          <div className="summary-bar-info">
            <span className="summary-tag">{shipments.length} Sevkiyat Aktif</span>
            <strong className="summary-qty">
              {totalScanned} / {totalTarget} Adet ({isAllComplete ? 'TAMAMLANDI ✓' : `%${Math.round(totalTarget > 0 ? (totalScanned / totalTarget) * 100 : 0)}`})
            </strong>
          </div>
          <div className="summary-bar-action">Detaylar ❯</div>
        </div>
      ) : (
        <div className="scan-empty-banner">
          <span>⚠️ Henüz aktif bir sevkiyat hedefi bulunmuyor.</span>
          <button type="button" className="mobile-btn primary small" onClick={onNavigateToSetup}>
            Kurulum Yap
          </button>
        </div>
      )}

      {/* Aktif Okutulan Sevkiyat Hedefi & Seçici */}
      {shipments.length > 0 && selectedShipment && (
        <div
          style={{
            background: 'linear-gradient(135deg, rgba(30, 58, 138, 0.4) 0%, rgba(15, 23, 42, 0.7) 100%)',
            border: '1px solid rgba(59, 130, 246, 0.4)',
            borderRadius: '10px',
            padding: '0.65rem 0.85rem',
            marginBottom: '0.65rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span
                style={{
                  background: '#2563eb',
                  color: '#fff',
                  fontSize: '0.65rem',
                  fontWeight: 800,
                  padding: '2px 6px',
                  borderRadius: '4px',
                  letterSpacing: '0.04em',
                }}
              >
                🎯 SEÇİLİ SEVKİYAT
              </span>
              <strong style={{ fontSize: '0.9rem', color: '#fff' }}>{selectedTitle}</strong>
            </div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              {selectedShipment.scanned_quantity} / {selectedShipment.requested_quantity} Adet
            </span>
          </div>

          <div style={{ fontSize: '0.75rem', color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>
            Ref: {selectedShipment.reference}
          </div>

          {/* Quick Pill Switcher if multiple shipments exist */}
          {shipments.length > 1 && (
            <div
              style={{
                display: 'flex',
                gap: '0.35rem',
                marginTop: '0.5rem',
                overflowX: 'auto',
                paddingBottom: '2px',
              }}
            >
              {shipments.map((s, idx) => {
                const isCur = selectedShipmentId === s.shipment_id;
                const sName = s.name || `${idx + 1}. Sevkiyat`;
                return (
                  <button
                    key={s.shipment_id}
                    type="button"
                    onClick={() => {
                      void triggerTapHaptic();
                      onSelectShipment?.(s.shipment_id);
                      focusInput();
                    }}
                    style={{
                      background: isCur ? '#2563eb' : 'var(--surface2)',
                      border: isCur ? '1px solid #3b82f6' : '1px solid var(--border)',
                      color: isCur ? '#fff' : 'var(--muted)',
                      padding: '3px 8px',
                      borderRadius: '6px',
                      fontSize: '0.7rem',
                      fontWeight: isCur ? 700 : 500,
                      whiteSpace: 'nowrap',
                      cursor: 'pointer',
                    }}
                  >
                    {isCur ? '🎯 ' : ''}{idx + 1}. {sName}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Primary Scan Input Card */}
      <div className="scan-input-card">
        <form onSubmit={handleSubmit} className="scan-form">
          <div className="input-with-actions">
            <input
              ref={inputRef}
              type="text"
              className="mobile-scan-input"
              value={scanValue}
              onChange={(e) => setScanValue(e.target.value)}
              placeholder="Barkod / QR okutun veya yazın..."
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck="false"
              disabled={isScanning}
            />

            {scanValue && (
              <button
                type="button"
                className="input-clear-btn"
                onClick={() => {
                  setScanValue('');
                  focusInput();
                }}
              >
                <XCircle size={18} />
              </button>
            )}

            <button
              type="submit"
              className="scan-submit-btn"
              disabled={!scanValue.trim() || isScanning}
              aria-label="Okut"
            >
              <CornerDownLeft size={20} />
            </button>
          </div>
        </form>

        {/* Scanner Action Buttons (Camera & Fullscreen) */}
        <div className="scan-action-row">
          <button
            type="button"
            className="camera-launch-btn"
            onClick={() => {
              void triggerTapHaptic();
              setShowCamera(true);
            }}
          >
            <Camera size={18} />
            <span>Kamera ile Tara</span>
          </button>

          <button
            type="button"
            className="fs-launch-btn"
            onClick={() => {
              void triggerTapHaptic();
              setShowFullscreen(true);
            }}
          >
            <Maximize2 size={18} />
            <span>Tam Ekran Modu</span>
          </button>
        </div>
      </div>

      {/* Error Alert */}
      {errorMsg && (
        <div className="mobile-alert error">
          <AlertCircle size={16} />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Dynamic Big Result Flash Card */}
      <div className="scan-result-container">
        {lastScan ? (
          (() => {
            const badge = getResultBadgeInfo(lastScan.result);
            return (
              <div className={`scan-result-card ${badge.bgClass}`}>
                <div className="result-card-header">
                  <div className="result-card-icon">{badge.icon}</div>
                  <div className="result-card-title">{badge.title}</div>
                  <button
                    type="button"
                    className="result-card-maximize-btn"
                    onClick={() => {
                      void triggerTapHaptic();
                      setShowFullscreen(true);
                    }}
                    title="Tam Ekran"
                  >
                    <Maximize2 size={16} />
                  </button>
                </div>

                <div className="result-card-meta">
                  <div className="result-meta-row main">
                    <span className="meta-key">ETİKET:</span>
                    <strong className="meta-val font-mono">{lastScan.label}</strong>
                  </div>

                  {lastScan.reference && (
                    <div className="result-meta-row">
                      <span className="meta-key">REFERANS:</span>
                      <strong className="meta-val">{lastScan.reference}</strong>
                    </div>
                  )}

                  <div className="result-meta-grid">
                    {lastScan.quantity != null && (
                      <div className="meta-grid-item">
                        <span>MİKTAR</span>
                        <strong>{lastScan.quantity} Adet</strong>
                      </div>
                    )}
                    {lastScan.fifo_date && (
                      <div className="meta-grid-item">
                        <span>FIFO TARİHİ</span>
                        <strong className="font-mono">{lastScan.fifo_date}</strong>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })()
        ) : (
          <div className="scan-waiting-card">
            <div className="waiting-pulse-dot" />
            <span>Okutma için etiket bekleniyor...</span>
          </div>
        )}
      </div>

      {/* Recent Scans Section */}
      <div className="recent-scans-section">
        <div className="recent-header">
          <h3>Son Okutmalar ({recentScans.length})</h3>
        </div>

        {recentScans.length === 0 ? (
          <div className="recent-empty">Henüz okutma kaydı yok</div>
        ) : (
          <div className="recent-scans-list">
            {recentScans.map((item, idx) => {
              const isOk = item.result === 'SEVKİYAT ÜRÜNÜ';
              const isExceeded = item.result === 'MİKTAR AŞILDI';
              const isDup = item.result === 'ZATEN OKUTULDU';
              const itemClass = isOk ? 'is-ok' : isExceeded ? 'is-exceeded' : isDup ? 'is-dup' : 'is-err';
              const icon = isOk ? '✓' : isExceeded ? '🚫' : isDup ? '⚠' : '✕';

              return (
                <div key={idx} className={`recent-scan-item ${itemClass}`}>
                  <div className="item-left">
                    <span className="item-icon-box">{icon}</span>
                    <div className="item-text">
                      <strong className="item-label font-mono">{item.label}</strong>
                      <span className="item-ref">{item.reference || item.result}</span>
                    </div>
                  </div>

                  <div className="item-right">
                    {item.quantity != null && <span className="item-qty">{item.quantity} Adet</span>}
                    <span className="item-time">{item.time}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Camera Scanner Modal */}
      <CameraScannerModal
        isOpen={showCamera}
        onClose={() => setShowCamera(false)}
        onScanResult={handleCameraScanResult}
      />

      {/* Fullscreen Live Scan Modal */}
      <FullscreenScanModal
        isOpen={showFullscreen}
        onClose={() => setShowFullscreen(false)}
        lastScan={lastScan}
        onScan={(val) => void executeScan(val)}
        isScanning={isScanning}
      />
    </div>
  );
}

