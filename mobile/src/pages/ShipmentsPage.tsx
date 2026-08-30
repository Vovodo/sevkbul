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
} from 'lucide-react';
import { api, ShipmentGroup, ShipmentProgress, ShipmentManifestItem } from '../api';
import { triggerTapHaptic } from '../audio/audioEngine';

interface ShipmentsPageProps {
  groups: ShipmentGroup[];
  selectedGroupId?: number | null;
  onSelectGroup?: (id: number) => void;
  onRefresh: () => void;
  onResetShipments: () => Promise<void>;
  onNavigateToManifest: () => void;
  onNavigateToSetup?: () => void;
}

export default function ShipmentsPage({
  groups,
  selectedGroupId,
  onSelectGroup,
  onRefresh,
  onResetShipments,
  onNavigateToManifest,
  onNavigateToSetup,
}: ShipmentsPageProps) {
  const [expandedGroupId, setExpandedGroupId] = useState<number | null>(null);
  const [expandedRefId, setExpandedRefId] = useState<number | null>(null);
  const [fifoMap, setFifoMap] = useState<Record<number, ShipmentManifestItem[]>>({});
  const [loadingMap, setLoadingMap] = useState<Record<number, boolean>>({});
  const [isResetting, setIsResetting] = useState<boolean>(false);
  const [undoError, setUndoError] = useState<string>('');

  // Editing state for group names
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [editNameValue, setEditNameValue] = useState<string>('');
  const [isSavingName, setIsSavingName] = useState<boolean>(false);
  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingGroupId != null) {
      setTimeout(() => editInputRef.current?.focus(), 50);
    }
  }, [editingGroupId]);

  // Whenever groups prop updates (e.g. on live scan), auto-refresh currently opened reference drawer
  useEffect(() => {
    if (expandedRefId != null) {
      loadFifoManifest(expandedRefId);
    }
  }, [groups, expandedRefId]);

  const loadFifoManifest = async (shipmentId: number) => {
    try {
      const manifests = await api.getManifest();
      const match = manifests.find((m) => m.shipment_id === shipmentId);
      setFifoMap((prev) => ({ ...prev, [shipmentId]: match?.items || [] }));
    } catch {
      setFifoMap((prev) => ({ ...prev, [shipmentId]: [] }));
    }
  };

  const toggleGroupExpand = (groupId: number) => {
    void triggerTapHaptic();
    setExpandedGroupId((prev) => (prev === groupId ? null : groupId));
  };

  const toggleRefExpand = (shipmentId: number) => {
    void triggerTapHaptic();
    if (expandedRefId === shipmentId) {
      setExpandedRefId(null);
    } else {
      setExpandedRefId(shipmentId);
      setLoadingMap((prev) => ({ ...prev, [shipmentId]: true }));
      loadFifoManifest(shipmentId).finally(() => {
        setLoadingMap((prev) => ({ ...prev, [shipmentId]: false }));
      });
    }
  };

  const handleStartEdit = (group: ShipmentGroup, e: React.MouseEvent) => {
    e.stopPropagation();
    void triggerTapHaptic();
    setEditingGroupId(group.group_id);
    setEditNameValue(group.name || '');
  };

  const handleCancelEdit = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    setEditingGroupId(null);
    setEditNameValue('');
  };

  const handleSaveEdit = async (groupId: number, e?: React.MouseEvent | React.KeyboardEvent) => {
    e?.stopPropagation();
    void triggerTapHaptic();
    if (isSavingName) return;
    setIsSavingName(true);
    try {
      await api.renameGroup(groupId, editNameValue.trim());
      setEditingGroupId(null);
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
      await loadFifoManifest(shipmentId);
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
          <h2>Sevkiyatlar ({groups.length})</h2>
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
          {groups.length > 0 && (
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

      {groups.length === 0 ? (
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
          {groups.map((g, index) => {
            const isDone = g.is_complete || g.scanned_quantity >= g.requested_quantity;
            const isExpanded = expandedGroupId === g.group_id;
            const isEditing = editingGroupId === g.group_id;
            const progressRatio = g.requested_quantity > 0 ? (g.scanned_quantity / g.requested_quantity) * 100 : 0;
            const displayName = g.name || `${index + 1}. Sevkiyat`;
            const isSelected = selectedGroupId === g.group_id;

            return (
              <div key={g.group_id} className={`shipment-card ${isDone ? 'is-complete' : 'is-active'} ${isSelected ? 'is-selected' : ''}`}>
                <div className="shipment-card-main" onClick={() => toggleGroupExpand(g.group_id)}>
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
                                if (e.key === 'Enter') handleSaveEdit(g.group_id, e);
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
                              onClick={(e) => handleSaveEdit(g.group_id, e)}
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
                              onClick={(e) => handleStartEdit(g, e)}
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

                      {/* Reference count and status */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span className="ref-title" style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                          {g.items.length} Referans
                        </span>
                        <span className={`status-pill ${isDone ? 'pill-done' : 'pill-active'}`}>
                          {isDone ? <CheckCircle2 size={11} /> : <Clock size={11} />}
                          <span>{isDone ? 'TAMAMLANDI' : 'DEVAM EDİYOR'}</span>
                        </span>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      {onSelectGroup && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void triggerTapHaptic();
                            onSelectGroup(g.group_id);
                          }}
                          style={{
                            background: isSelected ? '#2563eb' : 'var(--surface2)',
                            border: isSelected ? '1px solid #3b82f6' : '1px solid var(--border)',
                            color: isSelected ? '#fff' : 'var(--muted)',
                            fontSize: '0.68rem',
                            fontWeight: isSelected ? 800 : 600,
                            padding: '3px 7px',
                            borderRadius: '5px',
                            cursor: 'pointer',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {isSelected ? '🎯 SEÇİLİ' : 'Seç & Okut'}
                        </button>
                      )}
                      <div className="card-expand-icon">
                        {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                      </div>
                    </div>
                  </div>

                  {/* Progress Bar & Counters */}
                  <div className="card-progress-section">
                    <div className="progress-labels">
                      <span>Toplam Okutulan: <strong>{g.scanned_quantity} Adet</strong></span>
                      <span>Hedef: <strong>{g.requested_quantity} Adet</strong></span>
                    </div>
                    <div className="mobile-progress-track">
                      <div
                        className={`mobile-progress-fill ${isDone ? 'fill-done' : 'fill-active'}`}
                        style={{ width: `${Math.min(progressRatio, 100)}%` }}
                      />
                    </div>
                  </div>
                </div>

                {/* Expanded Drawer: All References in this group */}
                {isExpanded && (
                  <div className="scanned-items-drawer" style={{ background: 'rgba(0,0,0,0.2)', padding: '0.75rem' }}>
                    <div style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--muted)', marginBottom: '0.5rem' }}>
                      REFERANSLAR ({g.items.length})
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      {g.items.map((item: ShipmentProgress) => {
                        const itemDone = item.is_complete || item.scanned_quantity >= item.requested_quantity;
                        const itemPct = item.requested_quantity > 0 ? (item.scanned_quantity / item.requested_quantity) * 100 : 0;
                        const isRefOpen = expandedRefId === item.shipment_id;
                        const fifoItems = fifoMap[item.shipment_id] || [];
                        const isLoadingDetails = loadingMap[item.shipment_id];

                        return (
                          <div
                            key={item.shipment_id}
                            style={{
                              background: 'var(--surface2)',
                              border: '1px solid var(--border)',
                              borderRadius: '8px',
                              overflow: 'hidden',
                            }}
                          >
                            {/* Reference Item Header */}
                            <div
                              onClick={() => toggleRefExpand(item.shipment_id)}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                padding: '0.5rem 0.7rem',
                                cursor: 'pointer',
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flex: 1, minWidth: 0 }}>
                                <span style={{ fontSize: '0.7rem', color: 'var(--muted)' }}>
                                  {isRefOpen ? '▼' : '▶'}
                                </span>
                                <strong className="font-mono" style={{ fontSize: '0.85rem', color: '#fff' }}>
                                  {item.reference}
                                </strong>
                              </div>

                              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                  {item.scanned_quantity} / {item.requested_quantity}
                                </span>
                                <span
                                  className={`status-pill ${itemDone ? 'pill-done' : 'pill-active'}`}
                                  style={{ fontSize: '0.65rem', padding: '1px 5px' }}
                                >
                                  {itemDone ? '✓' : `%${Math.round(itemPct)}`}
                                </span>
                              </div>
                            </div>

                            {/* Mini progress bar */}
                            <div style={{ height: '2px', background: 'var(--border)', width: '100%' }}>
                              <div
                                style={{
                                  height: '100%',
                                  width: `${Math.min(itemPct, 100)}%`,
                                  background: itemDone ? 'var(--success)' : 'var(--primary)',
                                }}
                              />
                            </div>

                            {/* Reference Details: Tek Pencereli FIFO Listesi & Kaldır */}
                            {isRefOpen && (
                              <div style={{ padding: '0.6rem', borderTop: '1px solid var(--border)' }}>
                                {isLoadingDetails ? (
                                  <div className="drawer-loading" style={{ fontSize: '0.75rem' }}>Yükleniyor...</div>
                                ) : fifoItems.length === 0 ? (
                                  <div className="drawer-empty" style={{ fontSize: '0.75rem' }}>FIFO adayı bulunamadı</div>
                                ) : (
                                  <div className="scanned-tags-list">
                                    {fifoItems.map((fItem) => {
                                      const isScanned = fItem.status === 'scanned' || fItem.is_scanned;
                                      const isPartial = fItem.status === 'partial';

                                      return (
                                        <div
                                          key={fItem.label}
                                          className="scanned-tag-row"
                                          style={{
                                            borderLeft: isScanned
                                              ? '3px solid var(--success)'
                                              : isPartial
                                              ? '3px solid var(--warning)'
                                              : '3px solid var(--border)',
                                          }}
                                        >
                                          <div className="tag-info">
                                            <span className="tag-label font-mono" style={{ fontWeight: 600 }}>{fItem.label}</span>
                                            <div className="tag-meta">
                                              <span className="tag-qty">{fItem.quantity} Adet</span>
                                              {fItem.fifo_date && <span className="tag-date">FIFO: {fItem.fifo_date}</span>}
                                            </div>
                                          </div>

                                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                            <span
                                              style={{
                                                fontSize: '0.68rem',
                                                fontWeight: 700,
                                                color: isScanned
                                                  ? 'var(--success)'
                                                  : isPartial
                                                  ? 'var(--warning)'
                                                  : 'var(--muted)',
                                                whiteSpace: 'nowrap',
                                              }}
                                            >
                                              {isScanned ? '✅ Okutuldu' : isPartial ? '⚡ Kısmi' : '⏳ Bekliyor'}
                                            </span>

                                            {(isScanned || isPartial) && (
                                              <button
                                                type="button"
                                                className="undo-btn"
                                                onClick={(e) => {
                                                  e.stopPropagation();
                                                  handleUndo(item.shipment_id, fItem.label);
                                                }}
                                                title="Etiketi Kaldır"
                                              >
                                                <Trash2 size={13} />
                                                <span>Kaldır</span>
                                              </button>
                                            )}
                                          </div>
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
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
