import { useState, useRef, useEffect } from 'react';
import { api, ShipmentProgress, ScannedLabel } from '../api';

interface ShipmentCardProps {
  shipment: ShipmentProgress;
  index: number;               // 1-bazlı sıra numarası
  onUndoScan: (shipmentId: number, label: string) => Promise<void>;
  onRename: (shipmentId: number, name: string) => void;
}

export default function ShipmentCard({ shipment: s, index, onUndoScan, onRename }: ShipmentCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [scanned, setScanned] = useState<ScannedLabel[]>([]);
  const [scannedLoaded, setScannedLoaded] = useState(false);
  const [loadingScanned, setLoadingScanned] = useState(false);
  const [showManifest, setShowManifest] = useState(false);
  const [manifest, setManifest] = useState<{ label: string; fifo_date: string; status: string; quantity: number }[]>([]);
  const [loadingManifest, setLoadingManifest] = useState(false);

  // İsim düzenleme state'i
  const [editing, setEditing] = useState(false);
  const [nameInput, setNameInput] = useState(s.name || '');
  const [savingName, setSavingName] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  const isDone = s.is_complete || s.status === 'completed';
  const progress = Math.min(s.progress_percent, 100);
  const displayName = s.name || `${index}. Sevkiyat`;

  useEffect(() => {
    setNameInput(s.name || '');
  }, [s.name]);

  // Accordion aç/kapat
  const toggleExpand = async () => {
    setExpanded(prev => !prev);
    if (!scannedLoaded && !expanded) {
      setLoadingScanned(true);
      try {
        const labels = await api.getScannedLabels(s.shipment_id);
        setScanned(labels);
        setScannedLoaded(true);
      } catch { setScanned([]); }
      finally { setLoadingScanned(false); }
    }
  };

  // İsim kaydet
  const saveName = async () => {
    if (savingName) return;
    setSavingName(true);
    try {
      const updated = await api.renameShipment(s.shipment_id, nameInput.trim());
      onRename(s.shipment_id, updated.name || '');
    } catch { /* sessizce geç */ }
    finally {
      setSavingName(false);
      setEditing(false);
    }
  };

  const handleNameKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') saveName();
    if (e.key === 'Escape') { setEditing(false); setNameInput(s.name || ''); }
  };

  const startEditing = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditing(true);
    setTimeout(() => nameRef.current?.focus(), 30);
  };

  // Okutulan etiket kaldır
  const handleUndo = async (label: string) => {
    await onUndoScan(s.shipment_id, label);
    // Etiket listesini güncelle
    const updated = await api.getScannedLabels(s.shipment_id);
    setScanned(updated);
  };

  // FIFO Manifest yükle
  const toggleManifest = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!showManifest) {
      setLoadingManifest(true);
      try {
        const all = await api.getManifest();
        const mine = all.find(m => m.shipment_id === s.shipment_id);
        setManifest(mine?.items || []);
      } catch { setManifest([]); }
      finally { setLoadingManifest(false); }
    }
    setShowManifest(prev => !prev);
  };

  return (
    <div className={`shipment-card-v2 ${isDone ? 'sc-done' : 'sc-active'}`}>
      {/* ── Kart Başlığı ── */}
      <div className="sc-header" onClick={toggleExpand}>
        {/* Sol: Sıra numarası + isim */}
        <div className="sc-title-group">
          <span className="sc-index">{index}</span>
          <div className="sc-name-wrap">
            {editing ? (
              <input
                ref={nameRef}
                className="sc-name-input"
                value={nameInput}
                onChange={e => setNameInput(e.target.value)}
                onBlur={saveName}
                onKeyDown={handleNameKeyDown}
                onClick={e => e.stopPropagation()}
                placeholder={`${index}. Sevkiyat`}
                maxLength={80}
                disabled={savingName}
              />
            ) : (
              <span className="sc-name">{displayName}</span>
            )}
            <button
              className="sc-edit-btn"
              onClick={startEditing}
              title="İsim Düzenle"
              type="button"
            >✏️</button>
          </div>
        </div>

        {/* Sağ: Durum pill + expand ikon */}
        <div className="sc-header-right">
          <span className={`sc-status-pill ${isDone ? 'pill-done' : 'pill-active'}`}>
            {isDone ? '✅ Tamamlandı' : '🔄 Devam Ediyor'}
          </span>
          <span className="sc-chevron">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* ── Progress Bar ── */}
      <div className="sc-progress-row" onClick={toggleExpand}>
        <div className="sc-ref">{s.reference}</div>
        <div className="sc-progress-nums">
          <span>{s.scanned_quantity} / {s.requested_quantity} adet</span>
          <span className="sc-pct">{Math.round(progress)}%</span>
        </div>
        <div className="sc-progress-track">
          <div
            className={`sc-progress-fill ${isDone ? 'fill-done' : 'fill-active'}`}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* ── Açılan İçerik ── */}
      {expanded && (
        <div className="sc-body">
          {/* Aksiyon butonları */}
          <div className="sc-actions">
            <button
              className={`op-btn compact ${showManifest ? 'primary' : 'secondary'}`}
              onClick={toggleManifest}
              type="button"
            >
              {loadingManifest ? '⏳ Yükleniyor...' : showManifest ? '📋 FIFO Listesini Gizle' : '📋 FIFO Listesini Göster'}
            </button>
          </div>

          {/* FIFO Manifest */}
          {showManifest && (
            <div className="sc-manifest">
              <div className="sc-manifest-header">
                <strong>FIFO Havuzu — {manifest.length} Etiket</strong>
              </div>
              {manifest.length === 0 ? (
                <div className="sc-empty">FIFO listesi boş</div>
              ) : (
                <div className="sc-manifest-table">
                  <div className="sc-manifest-thead">
                    <span>Etiket</span>
                    <span>Miktar</span>
                    <span>FIFO Tarihi</span>
                    <span>Durum</span>
                  </div>
                  {manifest.map(item => (
                    <div
                      key={item.label}
                      className={`sc-manifest-row ${item.status === 'scanned' ? 'row-scanned' : item.status === 'partial' ? 'row-partial' : 'row-pending'}`}
                    >
                      <span className="mono">{item.label}</span>
                      <span>{item.quantity}</span>
                      <span>{item.fifo_date}</span>
                      <span className="sc-item-status">
                        {item.status === 'scanned' ? '✅ Okutuldu' : item.status === 'partial' ? '⚡ Kısmi' : '⏳ Bekliyor'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Okutulan Etiketler */}
          <div className="sc-scanned-section">
            <div className="sc-scanned-title">
              Okutulan Etiketler {scannedLoaded ? `(${scanned.length})` : ''}
            </div>
            {loadingScanned ? (
              <div className="sc-empty">Yükleniyor...</div>
            ) : scanned.length === 0 ? (
              <div className="sc-empty">Henüz okutma yok</div>
            ) : (
              <div className="sc-scanned-list">
                {scanned.map(item => (
                  <div key={item.label} className="sc-scanned-row">
                    <span className="mono sc-scan-label">{item.label}</span>
                    <span className="sc-scan-qty">{item.quantity} adet</span>
                    <span className="sc-scan-fifo">FIFO: {item.fifo_date}</span>
                    <button
                      type="button"
                      className="op-btn danger compact"
                      onClick={e => { e.stopPropagation(); handleUndo(item.label); }}
                    >Kaldır</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
