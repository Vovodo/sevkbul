import { useState, useRef, useEffect, useCallback } from 'react';
import { api, ShipmentProgress, ScanResponse, ShipmentTarget, RecentScan, ScannedLabel } from '../api';
import { playScanSound, getResultStyle, initAudio, ScanResultType } from '../audio';
import SoundSettings from '../components/SoundSettings';
import ManifestModal from '../components/ManifestModal';
import MobileDownloadModal from '../components/MobileDownloadModal';
import { useLiveUpdates, WsMessage } from '../useLiveUpdates';

type Phase = 'setup' | 'scanning';

export default function OperationPage() {
  const [phase, setPhase] = useState<Phase>('setup');
  const [showSetup, setShowSetup] = useState(true);
  const [showManifestModal, setShowManifestModal] = useState(false);
  const [showDownloadModal, setShowDownloadModal] = useState(false);
  const [stockLoaded, setStockLoaded] = useState(false);
  const [stockCount, setStockCount] = useState(0);
  const [targets, setTargets] = useState<ShipmentTarget[]>([]);
  const [shipments, setShipments] = useState<ShipmentProgress[]>([]);
  const [manualRef, setManualRef] = useState('');
  const [manualQty, setManualQty] = useState('');
  const [scanValue, setScanValue] = useState('');
  const [lastScan, setLastScan] = useState<ScanResponse | null>(null);
  const [recentScans, setRecentScans] = useState<RecentScan[]>([]);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [scannedMap, setScannedMap] = useState<Record<number, ScannedLabel[]>>({});
  const [loading, setLoading] = useState('');
  const [error, setError] = useState('');
  const [hourlyFifo, setHourlyFifo] = useState<boolean>(() => {
    return localStorage.getItem('hourlyFifo') === 'true';
  });
  const [isFullscreen, setIsFullscreen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const isScanning = phase === 'scanning' && shipments.length > 0;

  const focusScanInput = useCallback(() => {
    if (!isScanning) return;
    setTimeout(() => inputRef.current?.focus({ preventScroll: true }), 30);
  }, [isScanning]);

  const lockLandscape = useCallback(async () => {
    try {
      const orientation = screen.orientation as ScreenOrientation & {
        lock?: (type: 'landscape' | 'landscape-primary' | 'landscape-secondary') => Promise<void>;
      };
      if (orientation?.lock) {
        await orientation.lock('landscape');
      }
    } catch {
      // iOS / bazı tarayıcılarda desteklenmeyebilir
    }
  }, []);

  const unlockOrientation = useCallback(() => {
    try {
      screen.orientation?.unlock();
    } catch {
      // ignore
    }
  }, []);

  const exitFullscreen = useCallback(() => {
    setIsFullscreen(false);
    unlockOrientation();
    if (document.fullscreenElement && document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    }
  }, [unlockOrientation]);

  const enterFullscreen = useCallback(async () => {
    setIsFullscreen(true);
    try {
      if (document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen();
      }
      await lockLandscape();
    } catch {
      // Tam ekran / yön kilidi desteklenmese de overlay çalışır
    }
    focusScanInput();
  }, [lockLandscape, focusScanInput]);

  useEffect(() => {
    const onFullscreenChange = () => {
      if (!document.fullscreenElement) {
        setIsFullscreen(false);
        unlockOrientation();
      }
    };
    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, [unlockOrientation]);

  useEffect(() => {
    if (isFullscreen) {
      document.body.classList.add('fs-active');
      focusScanInput();
    } else {
      document.body.classList.remove('fs-active');
      focusScanInput();
    }
    return () => document.body.classList.remove('fs-active');
  }, [isFullscreen, focusScanInput]);

  useEffect(() => {
    initAudio();
    api.healthCheck()
      .then(h => {
        if (!h.features?.includes('shipment_targets')) {
          setError('Backend sürümü güncel değil.');
        } else if (!h.features?.includes('shipment_reset')) {
          setError('Sıfırlama servisi için backend güncellemesi gerekiyor.');
        }
      })
      .catch(() => setError('Backend bağlantısı kurulamadı.'));
    api.getInventoryStats().then(s => {
      setStockLoaded(s.total_labels > 0);
      setStockCount(s.total_labels);
    }).catch(() => {});
    api.getTargets().then(setTargets).catch(() => {});
    api.getShipmentStatus().then(s => {
      if (s.length > 0) {
        setShipments(s);
        setPhase('scanning');
        setShowSetup(false);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => { focusScanInput(); }, [isScanning, focusScanInput]);

  // ─── Gerçek Zamanlı Canlı Güncelleme (WebSocket) ───
  const handleWsMessage = useCallback((msg: WsMessage) => {
    const d = msg.data;

    if (msg.event === 'stock_import') {
      // Başka bir kullanıcı stok yükledi
      if (d?.total_labels != null) {
        setStockLoaded(d.total_labels > 0);
        setStockCount(d.total_labels);
      }
      return;
    }

    if (msg.event === 'reset') {
      // Başka bir kullanıcı sevkiyatı sıfırladı
      setShipments([]);
      setPhase('setup');
      setShowSetup(true);
      setExpandedId(null);
      setScannedMap({});
      setRecentScans([]);
      setLastScan(null);
      // Hedefleri de güncelle
      if (d?.targets) {
        setTargets(d.targets);
      }
      return;
    }

    // Tüm diğer olaylarda (scan, undo, find, target_add, target_import, target_clear)
    // Backend her zaman güncel shipments ve targets listesini gönderir
    if (d?.shipments) {
      setShipments(d.shipments);
      if (d.shipments.length > 0 && phase === 'setup') {
        setPhase('scanning');
        setShowSetup(false);
      }
    }

    if (d?.targets) {
      setTargets(d.targets);
    }

    // Okutma bildirimi: tüm cihazlarda son okutma sonucunu göster
    if (msg.event === 'scan' && d?.scan) {
      const scanData = d.scan as ScanResponse;
      setLastScan(scanData);

      // Ses efekti çal
      try {
        if (scanData.is_complete && scanData.success) {
          playScanSound('COMPLETE');
        } else {
          playScanSound(scanData.result as ScanResultType);
        }
      } catch {
        // audio context user interaction needed
      }


      // Son Okutmalar listesine ekle
      setRecentScans(prev => [{
        label: scanData.label,
        reference: scanData.reference,
        quantity: scanData.quantity,
        result: scanData.result,
        time: new Date().toLocaleTimeString('tr-TR'),
      }, ...prev].slice(0, 30));

      // Bildirim banner'ını 3.5 saniye göster
      setTimeout(() => {
        setLastScan(prev => prev?.label === scanData.label ? null : prev);
      }, 3500);
    }


    // Okutma veya undo sonrası genişletilmiş sevkiyatın etiketlerini güncelle
    if ((msg.event === 'scan' || msg.event === 'undo') && expandedId != null) {
      api.getScannedLabels(expandedId).then(labels => {
        setScannedMap(prev => ({ ...prev, [expandedId]: labels }));
      }).catch(() => {});
    }
  }, [phase, expandedId]);

  useLiveUpdates(handleWsMessage);

  const handleStockUpload = async (file: File) => {
    setLoading('stock');
    setError('');
    try {
      const r = await api.importStock(file);
      setStockLoaded(true);
      setStockCount(r.successful);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Stok yüklenemedi');
    } finally {
      setLoading('');
    }
  };

  const handleShipmentExcel = async (file: File) => {
    setLoading('shipment');
    setError('');
    try {
      const r = await api.importTargetsExcel(file);
      setTargets(r.targets);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sevkiyat Exceli yüklenemedi');
    } finally {
      setLoading('');
    }
  };

  const handleAddTarget = async () => {
    if (!manualRef.trim() || !manualQty) return;
    setError('');
    try {
      const t = await api.addTarget(manualRef.trim(), parseFloat(manualQty));
      setTargets(prev => [...prev, t]);
      setManualRef('');
      setManualQty('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Hedef eklenemedi');
    }
  };

  const handleFind = async () => {
    setLoading('find');
    setError('');
    try {
      const r = await api.findShipments(hourlyFifo);
      setShipments(r.shipments);
      setTargets([]);
      if (r.shipments.length > 0) {
        setPhase('scanning');
        setShowSetup(false);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sevkiyat bulunamadı');
    } finally {
      setLoading('');
    }
  };

  const handleReset = async () => {
    if (!window.confirm('Aktif sevkiyat iptal edilecek ve tüm ilerleme sıfırlanacak. Emin misiniz?')) return;
    setLoading('reset');
    setError('');
    try {
      await api.resetShipments();
      setShipments([]);
      setPhase('setup');
      setShowSetup(true);
      setExpandedId(null);
      setScannedMap({});
      setRecentScans([]);
      setLastScan(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sıfırlama hatası');
    } finally {
      setLoading('');
    }
  };

  const refreshStatus = () => {
    api.getShipmentStatus().then(setShipments).catch(() => {});
  };

  const loadScanned = async (shipmentId: number) => {
    try {
      const labels = await api.getScannedLabels(shipmentId);
      setScannedMap(prev => ({ ...prev, [shipmentId]: labels }));
    } catch {
      setScannedMap(prev => ({ ...prev, [shipmentId]: [] }));
    }
  };

  const toggleExpand = async (shipmentId: number) => {
    if (expandedId === shipmentId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(shipmentId);
    if (!scannedMap[shipmentId]) {
      await loadScanned(shipmentId);
    }
  };

  const handleUndoScan = async (shipmentId: number, label: string) => {
    if (!window.confirm(`${label} okutmasını kaldırmak istiyor musunuz?`)) return;
    setError('');
    try {
      const updated = await api.undoScan(shipmentId, label);
      setShipments(prev => prev.map(s => s.shipment_id === shipmentId ? updated : s));
      await loadScanned(shipmentId);
      setRecentScans(prev => prev.filter(s => !(s.label === label && s.result === 'SEVKİYAT ÜRÜNÜ')));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Okutma kaldırılamadı');
    }
  };

  const handleScan = useCallback(async (label: string) => {
    const trimmed = label.trim();
    if (!trimmed) return;

    try {
      const result = await api.scan(trimmed);
      setLastScan(result);
      playScanSound(result.result as ScanResultType);

      // Sevkiyat tamamlandıysa zafer melodisi çal
      if (result.is_complete && result.success) {
        setTimeout(() => playScanSound('COMPLETE' as ScanResultType), 300);
      }

      setTimeout(() => setLastScan(null), 1200);
      // NOT: recentScans, shipments ve scannedLabels güncellemesi
      // WebSocket handler tarafından yapılır (çift log önlenir)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Okutma hatası');
    } finally {
      setScanValue('');
      focusScanInput();
    }
  }, [focusScanInput]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleScan(scanValue);
    }
  };

  const resultStyle = lastScan ? getResultStyle(lastScan.result) : null;

  const statusLabel = (s: ShipmentProgress) => {
    if (s.is_complete || s.status === 'completed') return 'TAMAMLANDI';
    if (s.scanned_quantity > 0) return 'DEVAM EDİYOR';
    return 'BEKLİYOR';
  };

  return (
    <div className="op-page">
      <header className="op-header">
        <h1>SEVKİYAT BUL</h1>
        {stockLoaded && <span className="op-badge ok">{stockCount.toLocaleString('tr-TR')} etiket yüklü</span>}
        <div className="op-header-actions">
          {shipments.length > 0 && (
            <button
              type="button"
              className="op-btn primary compact"
              onClick={() => setShowManifestModal(true)}
              style={{ fontWeight: 700 }}
            >
              📋 FİFO Liste / Çıktı
            </button>
          )}
          {isScanning && (
            <>
              <button type="button" className="op-btn secondary compact" onClick={() => setShowSetup(v => !v)}>
                {showSetup ? 'Formu Gizle' : 'Formu Göster'}
              </button>
              <button
                type="button"
                className="op-btn danger compact"
                onClick={handleReset}
                disabled={loading === 'reset'}
              >
                {loading === 'reset' ? 'Sıfırlanıyor...' : 'Sevkiyatı Sıfırla'}
              </button>
            </>
          )}
          <button
            type="button"
            className="op-btn secondary compact mobile-download-header-btn"
            onClick={() => setShowDownloadModal(true)}
            style={{ fontWeight: 700, borderColor: '#3b82f6', color: '#93c5fd' }}
          >
            📱 Mobil İndir / QR
          </button>
          <SoundSettings />
        </div>
      </header>

      <ManifestModal isOpen={showManifestModal} onClose={() => setShowManifestModal(false)} />
      <MobileDownloadModal isOpen={showDownloadModal} onClose={() => setShowDownloadModal(false)} />

      {error && <div className="op-alert error">{error}</div>}

      {(showSetup || shipments.length === 0) && (
        <section className="op-section">
          <div className="op-row">
            <div className="op-field">
              <label>STOK EXCELİ</label>
              <label className="op-file-btn">
                {loading === 'stock' ? 'Yükleniyor...' : stockLoaded ? '✓ Yüklendi — Değiştir' : 'Dosya Seç'}
                <input type="file" accept=".xlsx,.xls" hidden onChange={e => {
                  const f = e.target.files?.[0];
                  if (f) handleStockUpload(f);
                }} />
              </label>
            </div>
            <div className="op-field">
              <label>SEVKİYAT EXCELİ</label>
              <label className="op-file-btn">
                {loading === 'shipment' ? 'Yükleniyor...' : 'Dosya Seç'}
                <input type="file" accept=".xlsx,.xls" hidden onChange={e => {
                  const f = e.target.files?.[0];
                  if (f) handleShipmentExcel(f);
                }} />
              </label>
            </div>
          </div>

          <div className="op-divider">veya manuel hedef</div>

          <div className="op-row">
            <div className="op-field flex-2">
              <label>REFERANS</label>
              <input value={manualRef} onChange={e => setManualRef(e.target.value)} placeholder="6681378-HZN-1" />
            </div>
            <div className="op-field flex-1">
              <label>MİKTAR</label>
              <input type="number" value={manualQty} onChange={e => setManualQty(e.target.value)} placeholder="240" />
            </div>
            <button className="op-btn secondary" onClick={handleAddTarget}>HEDEF EKLE</button>
          </div>

          {targets.length > 0 && (
            <div className="op-target-list">
              {targets.map(t => (
                <div key={t.id} className="op-target-item">
                  <span>{t.reference}</span>
                  <span>{t.target_quantity} adet</span>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: '1rem', marginBottom: '0.75rem', display: 'flex', justifyContent: 'center' }}>
            <button
              type="button"
              className={`op-btn compact ${hourlyFifo ? 'primary' : 'secondary'}`}
              onClick={() => setHourlyFifo(prev => {
                const next = !prev;
                localStorage.setItem('hourlyFifo', String(next));
                return next;
              })}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.5rem 1rem',
                fontSize: '0.85rem',
                fontWeight: 600,
                borderRadius: '8px',
                border: hourlyFifo ? '1px solid #3b82f6' : '1px solid #374151',
                background: hourlyFifo ? 'rgba(59, 130, 246, 0.15)' : 'rgba(31, 41, 55, 0.5)',
                color: hourlyFifo ? '#60a5fa' : '#9ca3af',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
              }}
            >
              <span>⏰ Saat Filtresi (FİFO Saat Önceliği):</span>
              <strong style={{ color: hourlyFifo ? '#3b82f6' : '#6b7280' }}>
                {hourlyFifo ? '⚡ AÇIK (Saat+Tarih Birebir)' : '📅 KAPALI (Sadece Gün/Tarih)'}
              </strong>
            </button>
          </div>

          <button
            className="op-btn primary large"
            onClick={handleFind}
            disabled={loading === 'find' || !stockLoaded || targets.length === 0}
          >
            {loading === 'find' ? 'Hesaplanıyor...' : 'SEVKİYATI BUL'}
          </button>
        </section>
      )}

      {shipments.length > 0 && (
        <section className="op-section">
          <h2>SEVKİYAT HAZIR</h2>
          <div className="op-shipment-table">
            {shipments.map(s => {
              const expanded = expandedId === s.shipment_id;
              const scanned = scannedMap[s.shipment_id] || [];
              const isDone = s.is_complete || s.status === 'completed';
              return (
                <div key={s.shipment_id} className={`op-shipment-block ${expanded ? 'expanded' : ''} ${isDone ? 'completed' : ''}`}>
                  <button
                    type="button"
                    className="op-shipment-row clickable"
                    onClick={() => toggleExpand(s.shipment_id)}
                  >
                    <div className="op-shipment-ref">
                      <span className="op-expand-icon">{expanded ? '▼' : '▶'}</span>
                      {s.reference}
                    </div>
                    <div className="op-shipment-target">Hedef: {s.requested_quantity}</div>
                    <div className="op-shipment-progress">
                      <span>{s.scanned_quantity} / {s.requested_quantity}</span>
                      <div className="op-progress-bar">
                        <div className={`op-progress-fill ${isDone ? 'done' : ''}`} style={{ width: `${Math.min(s.progress_percent, 100)}%` }} />
                      </div>
                    </div>
                    <div className={`op-status ${isDone ? 'done' : s.scanned_quantity > 0 ? 'active' : 'wait'}`}>
                      {statusLabel(s)}
                    </div>
                  </button>

                  {expanded && (
                    <div className="op-scanned-list">
                      <div className="op-scanned-header">
                        Okutulan Etiketler ({scanned.length})
                      </div>
                      {scanned.length === 0 ? (
                        <div className="op-scanned-empty">Henüz okutma yok</div>
                      ) : (
                        scanned.map(item => (
                          <div key={item.label} className="op-scanned-item">
                            <span className="op-scanned-label">{item.label}</span>
                            <span>{item.quantity} adet</span>
                            <span className="op-scanned-fifo">FIFO: {item.fifo_date}</span>
                            <button
                              type="button"
                              className="op-btn danger compact"
                              onClick={() => handleUndoScan(s.shipment_id, item.label)}
                            >
                              Kaldır
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {isScanning && (
        <section className="op-section scan-section">
          <h2>ETİKET / QR OKUT</h2>
          <div className="op-scan-area">
            <input
              ref={inputRef}
              className="op-scan-input"
              value={scanValue}
              onChange={e => setScanValue(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Etiket okutun veya yazın..."
              autoFocus
            />
            <button className="op-btn primary" onClick={() => handleScan(scanValue)}>OKUT</button>
          </div>

          <div className="op-result-wrap">
            <button
              type="button"
              className="op-result-fs-btn"
              onMouseDown={e => e.preventDefault()}
              onTouchStart={e => e.preventDefault()}
              onClick={enterFullscreen}
              title="Tam Ekran / Büyüteç Modu"
              aria-label="Bildirimi tam ekranda göster"
            >
              <span className="op-result-fs-icon" aria-hidden>🔍</span>
              <span className="op-result-fs-icon-expand" aria-hidden>⛶</span>
            </button>

            {lastScan && resultStyle ? (
              <div className="op-result" style={{ background: resultStyle.bg }}>
                <div className="op-result-icon">{resultStyle.icon}</div>
                <div className="op-result-text">{lastScan.result}</div>
                <div className="op-result-detail">
                  <div>Etiket: <strong>{lastScan.label}</strong></div>
                  {lastScan.reference && <div>Referans: {lastScan.reference}</div>}
                  {lastScan.quantity != null && <div>Miktar: {lastScan.quantity}</div>}
                  {lastScan.fifo_date && <div>FIFO: {lastScan.fifo_date}</div>}
                </div>
              </div>
            ) : (
              <div className="op-result waiting">SONUÇ BEKLENİYOR</div>
            )}
          </div>

          {recentScans.length > 0 && (
            <div className="op-recent">
              <h3>SON OKUTMALAR</h3>
              {recentScans.map((s, i) => {
                const isOk = s.result === 'SEVKİYAT ÜRÜNÜ';
                const isExceeded = s.result === 'MİKTAR AŞILDI';
                const cls = isOk ? 'ok' : isExceeded ? 'exceeded' : 'err';
                const icon = isOk ? '✓' : isExceeded ? '🚫' : '✕';
                return (
                  <div key={i} className={`op-recent-item ${cls}`}>
                    <span>{icon}</span>
                    <span>{s.label}</span>
                    <span>{s.reference || s.result}</span>
                    {s.quantity != null && <span>{s.quantity} adet</span>}
                    <span className="op-recent-time">{s.time}</span>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {isFullscreen && (
        <div className="fs-overlay" role="dialog" aria-modal="true" aria-label="Tam ekran okutma bildirimi">
          <button type="button" className="fs-close-btn" onClick={exitFullscreen}>
            ✕ Tam Ekrandan Çık
          </button>

          <div className="fs-card-container">
            {lastScan && resultStyle ? (
              <div key={lastScan.label + lastScan.result} className="fs-card fs-card-flash" style={{ background: resultStyle.bg }}>
                <div className="fs-card-icon">{resultStyle.icon}</div>
                <div className="fs-card-result-text">{lastScan.result}</div>
                <div className="fs-card-details">
                  <div className="fs-card-label-block">
                    <span className="fs-card-label-title">ETİKET NO</span>
                    <strong className="fs-card-label-val">{lastScan.label}</strong>
                  </div>
                  <div className="fs-card-meta-grid">
                    {lastScan.reference && (
                      <div className="fs-meta-item">
                        <span>REFERANS</span>
                        <strong>{lastScan.reference}</strong>
                      </div>
                    )}
                    {lastScan.quantity != null && (
                      <div className="fs-meta-item">
                        <span>MİKTAR</span>
                        <strong>{lastScan.quantity} ADET</strong>
                      </div>
                    )}
                    {lastScan.fifo_date && (
                      <div className="fs-meta-item">
                        <span>FIFO TARİHİ</span>
                        <strong>{lastScan.fifo_date}</strong>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="fs-card waiting">
                <div className="fs-card-icon">⏳</div>
                <div className="fs-card-result-text">SONUÇ BEKLENİYOR</div>
                <div className="fs-card-sub">Yeni okutma geldiğinde burada büyük boyutta görüntülenecek</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
