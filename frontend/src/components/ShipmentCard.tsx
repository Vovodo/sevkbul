import { useState, useRef, useEffect } from 'react';
import { api, ShipmentGroup, ShipmentProgress, ShipmentManifestItem } from '../api';

interface ShipmentCardProps {
  group: ShipmentGroup;
  index: number; // 1-bazlı sıra numarası
  isSelected?: boolean;
  onSelect?: () => void;
  onUndoScan: (shipmentId: number, label: string) => Promise<void>;
  onRenameGroup: (groupId: number, name: string) => void;
}

export default function ShipmentCard({
  group: g,
  index,
  isSelected,
  onSelect,
  onUndoScan,
  onRenameGroup,
}: ShipmentCardProps) {
  const [expanded, setExpanded] = useState(true);

  // Reference-level details state (FIFO manifest with live status & undo)
  const [expandedRefs, setExpandedRefs] = useState<Record<number, boolean>>({});
  const [manifestMap, setManifestMap] = useState<Record<number, ShipmentManifestItem[]>>({});
  const [loadingManifest, setLoadingManifest] = useState<Record<number, boolean>>({});

  // Group name editing state
  const [editing, setEditing] = useState(false);
  const [nameInput, setNameInput] = useState(g.name || '');
  const [savingName, setSavingName] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  const isDone = g.is_complete || g.status === 'completed';
  const progress = Math.min(g.progress_percent, 100);
  const displayName = g.name || `${index}. Sevkiyat`;

  useEffect(() => {
    setNameInput(g.name || '');
  }, [g.name]);

  const toggleExpand = () => {
    setExpanded(prev => !prev);
  };

  const saveName = async () => {
    if (savingName) return;
    setSavingName(true);
    try {
      await api.renameGroup(g.group_id, nameInput.trim());
      onRenameGroup(g.group_id, nameInput.trim());
    } catch {
      /* ignore */
    } finally {
      setSavingName(false);
      setEditing(false);
    }
  };

  const handleNameKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') saveName();
    if (e.key === 'Escape') {
      setEditing(false);
      setNameInput(g.name || '');
    }
  };

  const startEditing = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditing(true);
    setTimeout(() => nameRef.current?.focus(), 30);
  };

  const toggleRefItem = async (shipmentId: number) => {
    const nextState = !expandedRefs[shipmentId];
    setExpandedRefs(prev => ({ ...prev, [shipmentId]: nextState }));

    if (nextState) {
      loadManifestForRef(shipmentId);
    }
  };

  const loadManifestForRef = async (shipmentId: number) => {
    setLoadingManifest(prev => ({ ...prev, [shipmentId]: true }));
    try {
      const all = await api.getManifest();
      const match = all.find(m => m.shipment_id === shipmentId);
      setManifestMap(prev => ({ ...prev, [shipmentId]: match?.items || [] }));
    } catch {
      setManifestMap(prev => ({ ...prev, [shipmentId]: [] }));
    } finally {
      setLoadingManifest(prev => ({ ...prev, [shipmentId]: false }));
    }
  };

  // Whenever group data updates (e.g. after a scan), auto-refresh any open reference's manifest!
  useEffect(() => {
    Object.keys(expandedRefs).forEach(key => {
      const sid = Number(key);
      if (expandedRefs[sid]) {
        loadManifestForRef(sid);
      }
    });
  }, [g, expandedRefs]);

  const handleUndo = async (shipmentId: number, label: string) => {
    await onUndoScan(shipmentId, label);
    await loadManifestForRef(shipmentId);
  };

  return (
    <div className={`shipment-card-v2 ${isDone ? 'sc-done' : 'sc-active'} ${isSelected ? 'sc-selected' : ''}`}>
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
            >
              ✏️
            </button>
            <span style={{ fontSize: '0.8rem', color: '#9ca3af', marginLeft: '6px' }}>
              ({g.items.length} Referans)
            </span>
          </div>
        </div>

        {/* Sağ: Seçim Butonu + Durum pill + expand ikon */}
        <div className="sc-header-right" onClick={e => e.stopPropagation()}>
          {onSelect && (
            <button
              type="button"
              className={`sc-select-btn ${isSelected ? 'is-selected' : ''}`}
              onClick={onSelect}
              title={isSelected ? 'Şu an bu sevkiyat okutuluyor' : 'Okutmak için bu sevkiyatı seç'}
            >
              {isSelected ? '🎯 SEÇİLİ HEDEF' : 'Okutmak İçin Seç'}
            </button>
          )}
          <span className={`sc-status-pill ${isDone ? 'pill-done' : 'pill-active'}`}>
            {isDone ? '✅ Tamamlandı' : '🔄 Devam Ediyor'}
          </span>
          <span className="sc-chevron" onClick={toggleExpand} style={{ cursor: 'pointer' }}>
            {expanded ? '▲' : '▼'}
          </span>
        </div>
      </div>

      {/* ── Toplam İlerleme Progress Bar ── */}
      <div className="sc-progress-row" onClick={toggleExpand}>
        <div className="sc-progress-nums">
          <span>Toplam Okutulan: <strong>{g.scanned_quantity} / {g.requested_quantity} adet</strong></span>
          <span className="sc-pct">{Math.round(progress)}%</span>
        </div>
        <div className="sc-progress-track">
          <div
            className={`sc-progress-fill ${isDone ? 'fill-done' : 'fill-active'}`}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* ── Açılan İçerik: Bu Sevkiyattaki Referanslar Listesi ── */}
      {expanded && (
        <div className="sc-body" style={{ padding: '0.75rem 1rem 1rem' }}>
          <div style={{ fontSize: '0.82rem', fontWeight: 700, color: '#9ca3af', marginBottom: '0.6rem' }}>
            BU SEVKİYATTAKİ REFERANSLAR ({g.items.length})
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {g.items.map((item: ShipmentProgress) => {
              const itemDone = item.is_complete || item.scanned_quantity >= item.requested_quantity;
              const itemPct = item.requested_quantity > 0 ? (item.scanned_quantity / item.requested_quantity) * 100 : 0;
              const isItemExpanded = !!expandedRefs[item.shipment_id];
              const manifestList = manifestMap[item.shipment_id] || [];

              return (
                <div
                  key={item.shipment_id}
                  style={{
                    background: '#0d1117',
                    border: '1px solid #1f2937',
                    borderRadius: '8px',
                    overflow: 'hidden',
                  }}
                >
                  {/* Reference Header Row */}
                  <div
                    onClick={() => toggleRefItem(item.shipment_id)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '0.6rem 0.8rem',
                      cursor: 'pointer',
                      background: isItemExpanded ? 'rgba(255,255,255,0.02)' : 'transparent',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, minWidth: 0 }}>
                      <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>
                        {isItemExpanded ? '▼' : '▶'}
                      </span>
                      <strong className="mono" style={{ fontSize: '0.9rem', color: '#f3f4f6' }}>
                        {item.reference}
                      </strong>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.8rem' }}>
                      <span style={{ fontSize: '0.82rem', color: '#9ca3af' }}>
                        {item.scanned_quantity} / {item.requested_quantity} adet
                      </span>
                      <span
                        className={`sc-status-pill ${itemDone ? 'pill-done' : 'pill-active'}`}
                        style={{ fontSize: '0.68rem', padding: '1px 6px' }}
                      >
                        {itemDone ? '✓ TAMAM' : `%${Math.round(itemPct)}`}
                      </span>
                    </div>
                  </div>

                  {/* Reference Mini Progress Bar */}
                  <div style={{ height: '3px', background: '#1f2937', width: '100%' }}>
                    <div
                      style={{
                        height: '100%',
                        width: `${Math.min(itemPct, 100)}%`,
                        background: itemDone ? '#10b981' : '#3b82f6',
                        transition: 'width 0.3s ease',
                      }}
                    />
                  </div>

                  {/* Reference Expanded Details (Tek Pencereli FIFO Manifest & Okutulan/Kaldır Listesi) */}
                  {isItemExpanded && (
                    <div style={{ padding: '0.65rem 0.8rem', borderTop: '1px solid #1f2937' }}>
                      <div className="sc-manifest" style={{ margin: 0 }}>
                        {loadingManifest[item.shipment_id] ? (
                          <div className="sc-empty">Yükleniyor...</div>
                        ) : manifestList.length === 0 ? (
                          <div className="sc-empty">FIFO adayı bulunamadı</div>
                        ) : (
                          <div className="sc-manifest-table">
                            <div className="sc-manifest-thead">
                              <span>Etiket</span>
                              <span>Miktar</span>
                              <span>FIFO Tarihi</span>
                              <span style={{ textAlign: 'right' }}>Durum / İşlem</span>
                            </div>
                            {manifestList.map(m => {
                              const isScanned = m.status === 'scanned' || m.is_scanned;
                              const isPartial = m.status === 'partial';

                              return (
                                <div
                                  key={m.label}
                                  className={`sc-manifest-row ${
                                    isScanned
                                      ? 'row-scanned'
                                      : isPartial
                                      ? 'row-partial'
                                      : 'row-pending'
                                  }`}
                                >
                                  <span className="mono" style={{ fontWeight: 600 }}>{m.label}</span>
                                  <span>{m.quantity} adet</span>
                                  <span style={{ color: '#9ca3af', fontSize: '0.75rem' }}>{m.fifo_date}</span>
                                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.5rem' }}>
                                    <span className="sc-item-status">
                                      {isScanned
                                        ? '✅ Okutuldu'
                                        : isPartial
                                        ? '⚡ Kısmi'
                                        : '⏳ Bekliyor'}
                                    </span>
                                    {(isScanned || isPartial) && (
                                      <button
                                        type="button"
                                        className="op-btn danger compact"
                                        style={{ fontSize: '0.7rem', padding: '1px 7px', lineHeight: 1.2 }}
                                        onClick={e => {
                                          e.stopPropagation();
                                          handleUndo(item.shipment_id, m.label);
                                        }}
                                        title="Okutmayı Sevkiyattan Kaldır"
                                      >
                                        Kaldır
                                      </button>
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
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
}
