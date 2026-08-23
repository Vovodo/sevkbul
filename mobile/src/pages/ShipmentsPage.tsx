import { useState } from 'react';
import { ChevronDown, ChevronUp, Trash2, RotateCcw, AlertTriangle, CheckCircle2, Clock } from 'lucide-react';
import { api, ShipmentProgress, ScannedLabel } from '../api';
import { triggerTapHaptic } from '../audio/audioEngine';

interface ShipmentsPageProps {
  shipments: ShipmentProgress[];
  onRefresh: () => void;
  onResetShipments: () => Promise<void>;
  onNavigateToManifest: () => void;
}

export default function ShipmentsPage({
  shipments,
  onRefresh,
  onResetShipments,
  onNavigateToManifest,
}: ShipmentsPageProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [scannedMap, setScannedMap] = useState<Record<number, ScannedLabel[]>>({});
  const [loadingMap, setLoadingMap] = useState<Record<number, boolean>>({});
  const [isResetting, setIsResetting] = useState<boolean>(false);
  const [undoError, setUndoError] = useState<string>('');

  const loadScannedLabels = async (shipmentId: number) => {
    setLoadingMap((prev) => ({ ...prev, [shipmentId]: true }));
    try {
      const labels = await api.getScannedLabels(shipmentId);
      setScannedMap((prev) => ({ ...prev, [shipmentId]: labels }));
    } catch {
      setScannedMap((prev) => ({ ...prev, [shipmentId]: [] }));
    } finally {
      setLoadingMap((prev) => ({ ...prev, [shipmentId]: false }));
    }
  };

  const toggleExpand = (shipmentId: number) => {
    void triggerTapHaptic();
    if (expandedId === shipmentId) {
      setExpandedId(null);
    } else {
      setExpandedId(shipmentId);
      if (!scannedMap[shipmentId]) {
        void loadScannedLabels(shipmentId);
      }
    }
  };

  const handleUndo = async (shipmentId: number, label: string) => {
    if (!window.confirm(`${label} etiketini sevkiyattan çıkarmak istiyor musunuz?`)) {
      return;
    }
    void triggerTapHaptic();
    setUndoError('');
    try {
      await api.undoScan(shipmentId, label);
      await loadScannedLabels(shipmentId);
      onRefresh();
    } catch (err: unknown) {
      setUndoError(err instanceof Error ? err.message : 'Okutma geri alınamadı');
    }
  };

  const handleResetClick = async () => {
    if (!window.confirm('Aktif sevkiyat iptal edilecek ve tüm okutma ilerlemesi sıfırlanacak. Emin misiniz?')) {
      return;
    }
    void triggerTapHaptic();
    setIsResetting(true);
    try {
      await onResetShipments();
    } finally {
      setIsResetting(false);
    }
  };

  return (
    <div className="mobile-page shipments-page">
      {/* Top Header Actions */}
      <div className="page-section-header">
        <div>
          <h2>Aktif Sevkiyatlar</h2>
          <span className="page-section-desc">{shipments.length} referans işlemde</span>
        </div>
        <div className="header-action-group">
          {shipments.length > 0 && (
            <button
              type="button"
              className="mobile-btn danger small"
              onClick={handleResetClick}
              disabled={isResetting}
            >
              <RotateCcw size={14} />
              <span>{isResetting ? 'Sıfırlanıyor...' : 'Sıfırla'}</span>
            </button>
          )}
        </div>
      </div>

      {undoError && (
        <div className="mobile-alert error">
          <AlertTriangle size={16} />
          <span>{undoError}</span>
        </div>
      )}

      {shipments.length === 0 ? (
        <div className="empty-state-card">
          <div className="empty-icon">📦</div>
          <h3>Aktif Sevkiyat Yok</h3>
          <p>Lütfen Kurulum sekmesinden stok ve sevkiyat hedeflerini tanımlayarak FİFO hesabını başlatın.</p>
        </div>
      ) : (
        <div className="shipments-list">
          {shipments.map((s) => {
            const isDone = s.is_complete || s.scanned_quantity >= s.requested_quantity;
            const isExpanded = expandedId === s.shipment_id;
            const scannedItems = scannedMap[s.shipment_id] || [];
            const isLoadingScanned = loadingMap[s.shipment_id];
            const progressRatio = s.requested_quantity > 0 ? (s.scanned_quantity / s.requested_quantity) * 100 : 0;

            return (
              <div key={s.shipment_id} className={`shipment-card ${isDone ? 'is-complete' : 'is-active'}`}>
                <div className="shipment-card-main" onClick={() => toggleExpand(s.shipment_id)}>
                  <div className="card-top-row">
                    <div className="ref-name-wrap">
                      <strong className="ref-title">{s.reference}</strong>
                      <span className={`status-pill ${isDone ? 'pill-done' : 'pill-active'}`}>
                        {isDone ? <CheckCircle2 size={12} /> : <Clock size={12} />}
                        <span>{isDone ? 'TAMAMLANDI' : 'DEVAM EDİYOR'}</span>
                      </span>
                    </div>

                    <div className="card-expand-icon">
                      {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                    </div>
                  </div>

                  {/* Progress Bar & Counters */}
                  <div className="card-progress-section">
                    <div className="progress-labels">
                      <span>Okutulan: <strong>{s.scanned_quantity} Adet</strong></span>
                      <span>Hedef: <strong>{s.requested_quantity} Adet</strong></span>
                    </div>
                    <div className="mobile-progress-track">
                      <div
                        className={`mobile-progress-fill ${isDone ? 'fill-done' : 'fill-active'}`}
                        style={{ width: `${Math.min(progressRatio, 100)}%` }}
                      />
                    </div>
                  </div>
                </div>

                {/* Expanded Scanned Items Accordion */}
                {isExpanded && (
                  <div className="scanned-items-drawer">
                    <div className="drawer-header">
                      <h4>Okutulmuş Etiketler ({scannedItems.length})</h4>
                    </div>

                    {isLoadingScanned ? (
                      <div className="drawer-loading">Yükleniyor...</div>
                    ) : scannedItems.length === 0 ? (
                      <div className="drawer-empty">Bu referans için henüz etiket okutulmadı</div>
                    ) : (
                      <div className="scanned-tags-list">
                        {scannedItems.map((item) => (
                          <div key={item.label} className="scanned-tag-row">
                            <div className="tag-info">
                              <span className="tag-label font-mono">{item.label}</span>
                              <div className="tag-meta">
                                <span className="tag-qty">{item.quantity} Adet</span>
                                {item.fifo_date && <span className="tag-date">FIFO: {item.fifo_date}</span>}
                              </div>
                            </div>

                            <button
                              type="button"
                              className="undo-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleUndo(s.shipment_id, item.label);
                              }}
                              title="Etiketi Kaldır"
                            >
                              <Trash2 size={15} />
                              <span>Kaldır</span>
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* Quick Action to Manifest */}
          <div className="manifest-shortcut-card">
            <button type="button" className="mobile-btn secondary full" onClick={onNavigateToManifest}>
              📋 Tam FİFO Manifestini ve Aday Listesini Görüntüle
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
