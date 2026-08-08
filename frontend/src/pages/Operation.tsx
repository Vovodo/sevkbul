import { useState, useRef, useEffect, useCallback } from 'react';
import { api, ShipmentProgress, ScanResponse, ShipmentTarget, RecentScan, ScannedLabel } from '../api';
import { playScanSound, getResultStyle, initAudio, ScanResultType } from '../audio';
import SoundSettings from '../components/SoundSettings';

type Phase = 'setup' | 'scanning';

export default function OperationPage() {
  const [phase, setPhase] = useState<Phase>('setup');
  const [showSetup, setShowSetup] = useState(true);
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
  const inputRef = useRef<HTMLInputElement>(null);

  const isScanning = phase === 'scanning' && shipments.length > 0;

  const focusInput = useCallback(() => {
    if (isScanning) setTimeout(() => inputRef.current?.focus(), 30);
  }, [isScanning]);

  useEffect(() => {
    initAudio();
    fetch('/api/health')
      .then(r => r.json())
      .then(h => {
        if (!h.features?.includes('shipment_targets')) {
          setError('Backend güncel değil. "SevkiyatBul - Backend" penceresini kapatıp start.cmd ile yeniden başlatın.');
        } else if (!h.features?.includes('shipment_reset')) {
          setError('Sıfırlama için backend yeniden başlatılmalı: scripts\\restart-backend.cmd — ardından frontend penceresini de yeniden başlatın.');
        }
      })
      .catch(() => setError('Backend bağlantısı kurulamadı. start.cmd ile sunucuları başlatın.'));
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

  useEffect(() => { focusInput(); }, [isScanning, focusInput]);

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
      const r = await api.findShipments();
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

      setRecentScans(prev => [{
        label: result.label,
        reference: result.reference,
        quantity: result.quantity,
        result: result.result,
        time: new Date().toLocaleTimeString('tr-TR'),
      }, ...prev].slice(0, 30));

      refreshStatus();

      if (result.success && result.shipment_id && expandedId === result.shipment_id) {
        loadScanned(result.shipment_id);
      }

      setTimeout(() => setLastScan(null), 1200);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Okutma hatası');
    } finally {
      setScanValue('');
      focusInput();
    }
  }, [focusInput, expandedId]);

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
          <SoundSettings />
        </div>
      </header>

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

          {recentScans.length > 0 && (
            <div className="op-recent">
              <h3>SON OKUTMALAR</h3>
              {recentScans.map((s, i) => (
                <div key={i} className={`op-recent-item ${s.result === 'SEVKİYAT ÜRÜNÜ' ? 'ok' : 'err'}`}>
                  <span>{s.result === 'SEVKİYAT ÜRÜNÜ' ? '✓' : '✕'}</span>
                  <span>{s.label}</span>
                  <span>{s.reference || s.result}</span>
                  {s.quantity != null && <span>{s.quantity} adet</span>}
                  <span className="op-recent-time">{s.time}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
