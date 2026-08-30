import { useState, useRef, useEffect } from 'react';
import {
  ChevronDown,
  ChevronUp,
  Trash2,
  RotateCcw,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Edit2,
  Check,
  X,
  Plus,
  ListOrdered,
  ScanLine,
} from 'lucide-react';
import { api, ShipmentProgress, ScannedLabel, ShipmentManifestItem } from '../api';
import { triggerTapHaptic } from '../audio/audioEngine';

interface ShipmentsPageProps {
  shipments: ShipmentProgress[];
  onRefresh: () => void;
  onResetShipments: () => Promise<void>;
  onNavigateToManifest: () => void;
  onNavigateToSetup?: () => void;
}

export default function ShipmentsPage({
  shipments,
  onRefresh,
  onResetShipments,
  onNavigateToManifest,
  onNavigateToSetup,
}: ShipmentsPageProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [activeTabMap, setActiveTabMap] = useState<Record<number, 'scanned' | 'fifo'>>({});
  const [scannedMap, setScannedMap] = useState<Record<number, ScannedLabel[]>>({});
  const [fifoMap, setFifoMap] = useState<Record<number, ShipmentManifestItem[]>>({});
  const [loadingMap, setLoadingMap] = useState<Record<number, boolean>>({});
  const [isResetting, setIsResetting] = useState<boolean>(false);
  const [undoError, setUndoError] = useState<string>('');

  // Editing state for shipment names
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editNameValue, setEditNameValue] = useState<string>('');
  const [isSavingName, setIsSavingName] = useState<boolean>(false);
  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId != null) {
      setTimeout(() => editInputRef.current?.focus(), 50);
    }
  }, [editingId]);

  const loadScannedLabels = async (shipmentId: number) => {
    try {
      const labels = await api.getScannedLabels(shipmentId);
      setScannedMap((prev) => ({ ...prev, [shipmentId]: labels }));
    } catch {
      setScannedMap((prev) => ({ ...prev, [shipmentId]: [] }));
    }
  };

  const loadFifoManifest = async (shipmentId: number) => {
    try {
      const manifests = await api.getManifest();
      const match = manifests.find((m) => m.shipment_id === shipmentId);
      setFifoMap((prev) => ({ ...prev, [shipmentId]: match?.items || [] }));
    } catch {
      setFifoMap((prev) => ({ ...prev, [shipmentId]: [] }));
    }
  };

  const toggleExpand = (shipmentId: number) => {
    void triggerTapHaptic();
    if (expandedId === shipmentId) {
      setExpandedId(null);
    } else {
      setExpandedId(shipmentId);
      if (!activeTabMap[shipmentId]) {
        setActiveTabMap((prev) => ({ ...prev, [shipmentId]: 'scanned' }));
      }
      setLoadingMap((prev) => ({ ...prev, [shipmentId]: true }));
      Promise.all([loadScannedLabels(shipmentId), loadFifoManifest(shipmentId)]).finally(() => {
        setLoadingMap((prev) => ({ ...prev, [shipmentId]: false }));
      });
    }
  };

  const handleStartEdit = (shipment: ShipmentProgress, e: React.MouseEvent) => {
    e.stopPropagation();
    void triggerTapHaptic();
    setEditingId(shipment.shipment_id);
    setEditNameValue(shipment.name || '');
  };

  const handleCancelEdit = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    setEditingId(null);
    setEditNameValue('');
  };

  const handleSaveEdit = async (shipmentId: number, e?: React.MouseEvent | React.KeyboardEvent) => {
    e?.stopPropagation();
    void triggerTapHaptic();
    if (isSavingName) return;
    setIsSavingName(true);
    try {
      await api.renameShipment(shipmentId, editNameValue.trim());
      setEditingId(null);
      onRefresh();
    } catch (err: unknown) {
      setUndoError(err instanceof Error ? err.message : 'İsim güncellenemedi');
    } finally {
      setIsSavingName(false);
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
      await Promise.all([loadScannedLabels(shipmentId), loadFifoManifest(shipmentId)]);
      onRefresh();
    } catch (err: unknown) {
      setUndoError(err instanceof Error ? err.message : 'Okutma geri alınamadı');
    }
  };

  const handleResetClick = async () => {
    if (!window.confirm('Tüm aktif sevkiyatlar iptal edilecek ve tüm okutma ilerlemesi sıfırlanacak. Emin misiniz?')) {
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
          <h2>Sevkiyatlar ({shipments.length})</h2>
          <span className="page-section-desc">FIFO devamlılığı ile çoklu yönetim</span>
        </div>
        <div className="header-action-group" style={{ display: 'flex', gap: '0.4rem' }}>
          {onNavigateToSetup && (
            <button
              type="button"
              className="mobile-btn primary small"
              onClick={() => {
                void triggerTapHaptic();
                onNavigateToSetup();
              }}
              title="Yeni Sevkiyat Ekle"
            >
              <Plus size={14} />
              <span>Yeni Sevkiyat</span>
            </button>
          )}
          {shipments.length > 0 && (
            <button
              type="button"
              className="mobile-btn danger small"
              onClick={handleResetClick}
              disabled={isResetting}
              title="Tüm Sevkiyatları Sıfırla"
            >
              <RotateCcw size={14} />
              <span>{isResetting ? '...' : 'Sıfırla'}</span>
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
          {onNavigateToSetup && (
            <button
              type="button"
              className="mobile-btn primary"
              style={{ marginTop: '1rem' }}
              onClick={onNavigateToSetup}
            >
              <Plus size={16} />
              <span>İlk Sevkiyatı Başlat</span>
            </button>
          )}
        </div>
      ) : (
        <div className="shipments-list">
          {shipments.map((s, index) => {
            const isDone = s.is_complete || s.scanned_quantity >= s.requested_quantity;
            const isExpanded = expandedId === s.shipment_id;
            const isEditing = editingId === s.shipment_id;
            const currentTab = activeTabMap[s.shipment_id] || 'scanned';
            const scannedItems = scannedMap[s.shipment_id] || [];
            const fifoItems = fifoMap[s.shipment_id] || [];
            const isLoadingDetails = loadingMap[s.shipment_id];
            const progressRatio = s.requested_quantity > 0 ? (s.scanned_quantity / s.requested_quantity) * 100 : 0;
            const displayName = s.name || `${index + 1}. Sevkiyat`;

            return (
              <div key={s.shipment_id} className={`shipment-card ${isDone ? 'is-complete' : 'is-active'}`}>
                <div className="shipment-card-main" onClick={() => toggleExpand(s.shipment_id)}>
                  {/* Top Card Row: Index + Title/Edit + Status */}
                  <div className="card-top-row">
                    <div className="ref-name-wrap" style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.2rem' }}>
                        <span
                          style={{
                            background: isDone ? 'var(--success)' : 'var(--primary)',
                            color: '#fff',
                            fontSize: '0.75rem',
                            fontWeight: 800,
                            padding: '0.15rem 0.45rem',
                            borderRadius: '6px',
                            minWidth: '20px',
                            textAlign: 'center',
                          }}
                        >
                          {index + 1}
                        </span>

                        {isEditing ? (
                          <div
                            style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flex: 1 }}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <input
                              ref={editInputRef}
                              type="text"
                              value={editNameValue}
                              onChange={(e) => setEditNameValue(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleSaveEdit(s.shipment_id, e);
                                if (e.key === 'Escape') handleCancelEdit();
                              }}
                              placeholder={`${index + 1}. Sevkiyat`}
                              style={{
                                background: 'var(--surface2)',
                                border: '1px solid var(--primary)',
                                color: '#fff',
                                fontSize: '0.85rem',
                                padding: '0.2rem 0.5rem',
                                borderRadius: '4px',
                                outline: 'none',
                                flex: 1,
                              }}
                              maxLength={60}
                            />
                            <button
                              type="button"
                              onClick={(e) => handleSaveEdit(s.shipment_id, e)}
                              disabled={isSavingName}
                              style={{
                                background: 'var(--success)',
                                border: 'none',
                                color: '#fff',
                                padding: '0.25rem 0.45rem',
                                borderRadius: '4px',
                                cursor: 'pointer',
                              }}
                            >
                              <Check size={14} />
                            </button>
                            <button
                              type="button"
                              onClick={handleCancelEdit}
                              style={{
                                background: 'var(--surface2)',
                                border: '1px solid var(--border)',
                                color: 'var(--muted)',
                                padding: '0.25rem 0.45rem',
                                borderRadius: '4px',
                                cursor: 'pointer',
                              }}
                            >
                              <X size={14} />
                            </button>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', minWidth: 0 }}>
                            <strong
                              style={{
                                fontSize: '0.95rem',
                                color: '#fff',
                                fontWeight: 700,
                                whiteSpace: 'nowrap',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                              }}
                            >
                              {displayName}
                            </strong>
                            <button
                              type="button"
                              onClick={(e) => handleStartEdit(s, e)}
                              title="İsmi Düzenle"
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: 'var(--muted)',
                                padding: '2px 4px',
                                cursor: 'pointer',
                                display: 'inline-flex',
                                alignItems: 'center',
                              }}
                            >
                              <Edit2 size={13} />
                            </button>
                          </div>
                        )}
                      </div>

                      {/* Reference code */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span className="ref-title" style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                          {s.reference}
                        </span>
                        <span className={`status-pill ${isDone ? 'pill-done' : 'pill-active'}`}>
                          {isDone ? <CheckCircle2 size={11} /> : <Clock size={11} />}
                          <span>{isDone ? 'TAMAMLANDI' : 'DEVAM EDİYOR'}</span>
                        </span>
                      </div>
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

                {/* Expanded Drawer (Scanned + FIFO Pool views) */}
                {isExpanded && (
                  <div className="scanned-items-drawer">
                    {/* Sub-tab buttons */}
                    <div
                      style={{
                        display: 'flex',
                        gap: '0.4rem',
                        marginBottom: '0.65rem',
                        borderBottom: '1px solid var(--border)',
                        paddingBottom: '0.5rem',
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => setActiveTabMap((prev) => ({ ...prev, [s.shipment_id]: 'scanned' }))}
                        style={{
                          flex: 1,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: '0.3rem',
                          padding: '0.4rem 0.6rem',
                          borderRadius: '6px',
                          border: currentTab === 'scanned' ? '1px solid var(--primary)' : '1px solid transparent',
                          background: currentTab === 'scanned' ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                          color: currentTab === 'scanned' ? 'var(--primary)' : 'var(--muted)',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          cursor: 'pointer',
                        }}
                      >
                        <ScanLine size={13} />
                        <span>Okutulanlar ({scannedItems.length})</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => setActiveTabMap((prev) => ({ ...prev, [s.shipment_id]: 'fifo' }))}
                        style={{
                          flex: 1,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: '0.3rem',
                          padding: '0.4rem 0.6rem',
                          borderRadius: '6px',
                          border: currentTab === 'fifo' ? '1px solid var(--primary)' : '1px solid transparent',
                          background: currentTab === 'fifo' ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                          color: currentTab === 'fifo' ? 'var(--primary)' : 'var(--muted)',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          cursor: 'pointer',
                        }}
                      >
                        <ListOrdered size={13} />
                        <span>FIFO Havuzu ({fifoItems.length})</span>
                      </button>
                    </div>

                    {isLoadingDetails ? (
                      <div className="drawer-loading">Yükleniyor...</div>
                    ) : currentTab === 'scanned' ? (
                      /* Tab 1: Okutulan Etiketler */
                      <div>
                        {scannedItems.length === 0 ? (
                          <div className="drawer-empty">Bu sevkiyat için henüz etiket okutulmadı</div>
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
                                  <Trash2 size={14} />
                                  <span>Kaldır</span>
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      /* Tab 2: FIFO Aday Listesi */
                      <div>
                        {fifoItems.length === 0 ? (
                          <div className="drawer-empty">FIFO adayı bulunamadı</div>
                        ) : (
                          <div className="scanned-tags-list">
                            {fifoItems.map((item) => (
                              <div
                                key={item.label}
                                className="scanned-tag-row"
                                style={{
                                  borderLeft:
                                    item.status === 'scanned'
                                      ? '3px solid var(--success)'
                                      : item.status === 'partial'
                                      ? '3px solid var(--warning)'
                                      : '3px solid var(--border)',
                                }}
                              >
                                <div className="tag-info">
                                  <span className="tag-label font-mono">{item.label}</span>
                                  <div className="tag-meta">
                                    <span className="tag-qty">{item.quantity} Adet</span>
                                    {item.fifo_date && <span className="tag-date">FIFO: {item.fifo_date}</span>}
                                  </div>
                                </div>

                                <span
                                  style={{
                                    fontSize: '0.7rem',
                                    fontWeight: 700,
                                    color:
                                      item.status === 'scanned'
                                        ? 'var(--success)'
                                        : item.status === 'partial'
                                        ? 'var(--warning)'
                                        : 'var(--muted)',
                                    whiteSpace: 'nowrap',
                                  }}
                                >
                                  {item.status === 'scanned' ? '✅ Okutuldu' : item.status === 'partial' ? '⚡ Kısmi' : '⏳ Bekliyor'}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
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
              📋 Tüm FİFO Manifestini ve Çıktı Tablosunu Görüntüle
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
