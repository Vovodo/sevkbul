import { useEffect, useState, useCallback, useMemo } from 'react';
import { Download, Globe, Printer, TriangleAlert, X } from 'lucide-react';
import { api, ShipmentManifest } from '../api';
import { useLiveUpdates } from '../useLiveUpdates';
import Logo from './Logo';

interface ManifestModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface GroupedManifest {
  groupId: number;
  groupName: string;
  manifests: ShipmentManifest[];
  totalRequested: number;
  totalScanned: number;
  totalLabels: number;
  completedRefs: number;
}

export default function ManifestModal({ isOpen, onClose }: ManifestModalProps) {
  const [manifests, setManifests] = useState<ShipmentManifest[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | 'all'>('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchManifest = useCallback(async () => {
    if (!isOpen) return;
    setLoading(true);
    setError('');
    try {
      const data = await api.getManifest();
      setManifests(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Manifest verisi alınamadı');
    } finally {
      setLoading(false);
    }
  }, [isOpen]);

  useEffect(() => {
    fetchManifest();
  }, [fetchManifest]);

  // Real-time live update for manifest view
  useLiveUpdates(useCallback(() => {
    if (isOpen) {
      api.getManifest().then(setManifests).catch(() => {});
    }
  }, [isOpen]));

  // Grupları oluştur
  const groups = useMemo<GroupedManifest[]>(() => {
    const map = new Map<number, GroupedManifest>();
    manifests.forEach((m) => {
      const gid = m.group_id || m.shipment_id;
      const gname = m.group_name || `${gid}. Sevkiyat`;
      if (!map.has(gid)) {
        map.set(gid, {
          groupId: gid,
          groupName: gname,
          manifests: [],
          totalRequested: 0,
          totalScanned: 0,
          totalLabels: 0,
          completedRefs: 0,
        });
      }
      const g = map.get(gid)!;
      g.manifests.push(m);
      g.totalRequested += m.requested_quantity;
      g.totalScanned += m.scanned_quantity;
      g.totalLabels += m.items.length;
      if (m.is_complete || m.scanned_quantity >= m.requested_quantity) {
        g.completedRefs += 1;
      }
    });
    return Array.from(map.values());
  }, [manifests]);

  // İlk grup seçimini otomatik ayarla
  useEffect(() => {
    if (groups.length > 0) {
      if (selectedGroupId !== 'all' && !groups.some(g => g.groupId === selectedGroupId)) {
        setSelectedGroupId(groups[0].groupId);
      } else if (selectedGroupId === 'all' && groups.length > 1) {
        // Çoklu grup varsa ilk grubu seç
        setSelectedGroupId(groups[0].groupId);
      }
    }
  }, [groups, selectedGroupId]);

  if (!isOpen) return null;

  // Seçili grubun manifestleri ve istatistikleri
  const currentGroup = selectedGroupId !== 'all' ? groups.find(g => g.groupId === selectedGroupId) : null;
  const displayManifests = currentGroup ? currentGroup.manifests : manifests;

  const totalRequested = currentGroup ? currentGroup.totalRequested : manifests.reduce((sum, m) => sum + m.requested_quantity, 0);
  const totalScanned = currentGroup ? currentGroup.totalScanned : manifests.reduce((sum, m) => sum + m.scanned_quantity, 0);
  const totalLabels = currentGroup ? currentGroup.totalLabels : manifests.reduce((sum, m) => sum + m.items.length, 0);
  const completedRefs = currentGroup ? currentGroup.completedRefs : manifests.filter(m => m.is_complete || m.scanned_quantity >= m.requested_quantity).length;
  const activeTitle = currentGroup ? currentGroup.groupName : 'Tüm Sevkiyatlar';

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="manifest-overlay" onClick={onClose}>
      <div className="manifest-modal" onClick={e => e.stopPropagation()}>
        {/* Screen Header */}
        <div className="manifest-header no-print">
          <div className="manifest-title" style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <Logo size="sm" variant="icon" />
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <h2>FİFO HESAPLAMA VE SİSTEM MANİFESTİ</h2>
                {currentGroup && (
                  <span
                    style={{
                      background: 'rgba(59, 130, 246, 0.2)',
                      border: '1px solid #3b82f6',
                      color: '#93c5fd',
                      fontSize: '0.78rem',
                      fontWeight: 800,
                      padding: '2px 8px',
                      borderRadius: '6px',
                    }}
                  >
                    {currentGroup.groupName}
                  </span>
                )}
              </div>
              <div className="manifest-badges">
                <span className="manifest-badge info">{displayManifests.length} Referans</span>
                <span className="manifest-badge ok">
                  Toplam: {totalScanned} / {totalRequested} Adet ({completedRefs}/{displayManifests.length} Tamamlandı)
                </span>
                <span className="manifest-badge pool">{totalLabels} FIFO Tarihi</span>
              </div>
            </div>
          </div>
          <div className="manifest-actions">
            <a
              className="op-btn secondary compact"
              href={api.exportManifestExcelUrl(selectedGroupId !== 'all' ? selectedGroupId : null)}
              download
              style={{ fontWeight: 700, textDecoration: 'none', borderColor: '#10b981', color: '#6ee7b7' }}
            >
              <Download size={15} /> Excel İndir
            </a>
            <button type="button" className="op-btn primary compact" onClick={handlePrint} style={{ fontWeight: 700 }}>
              <Printer size={15} /> Yazdır / PDF
            </button>
            <button type="button" className="op-btn danger compact" onClick={onClose}>
              <X size={15} /> Kapat
            </button>
          </div>
        </div>

        {/* Sevkiyat Seçici Sekmeler (Shipment Switcher Tabs) */}
        {groups.length > 0 && (
          <div
            className="manifest-group-tabs no-print"
            style={{
              display: 'flex',
              gap: '0.5rem',
              padding: '0.6rem 1.25rem',
              background: '#0d1527',
              borderBottom: '1px solid #1e293b',
              overflowX: 'auto',
            }}
          >
            {groups.map((g, idx) => {
              const isCur = selectedGroupId === g.groupId;
              return (
                <button
                  key={g.groupId}
                  type="button"
                  onClick={() => setSelectedGroupId(g.groupId)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.45rem',
                    padding: '0.4rem 0.85rem',
                    borderRadius: '8px',
                    border: isCur ? '1px solid #3b82f6' : '1px solid #334155',
                    background: isCur ? 'rgba(59, 130, 246, 0.25)' : '#1e293b',
                    color: isCur ? '#fff' : '#94a3b8',
                    fontSize: '0.82rem',
                    fontWeight: isCur ? 700 : 500,
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <span
                    style={{
                      background: isCur ? '#2563eb' : '#475569',
                      color: '#fff',
                      fontSize: '0.7rem',
                      fontWeight: 800,
                      padding: '1px 6px',
                      borderRadius: '4px',
                    }}
                  >
                    {idx + 1}
                  </span>
                  <span>{g.groupName}</span>
                  <span style={{ fontSize: '0.72rem', opacity: 0.8 }}>({g.manifests.length} Ref • {g.totalScanned}/{g.totalRequested})</span>
                </button>
              );
            })}

            {groups.length > 1 && (
              <button
                type="button"
                onClick={() => setSelectedGroupId('all')}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.4rem 0.8rem',
                  borderRadius: '8px',
                  border: selectedGroupId === 'all' ? '1px solid #3b82f6' : '1px solid #334155',
                  background: selectedGroupId === 'all' ? 'rgba(59, 130, 246, 0.25)' : '#1e293b',
                  color: selectedGroupId === 'all' ? '#fff' : '#94a3b8',
                  fontSize: '0.82rem',
                  fontWeight: selectedGroupId === 'all' ? 700 : 500,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                <Globe size={14} /> Tümü ({manifests.length})
              </button>
            )}
          </div>
        )}

        {/* Printable & Compact Container */}
        <div className="manifest-body printable-manifest">
          {/* Print Title Header (Only visible on printout) */}
          <div className="manifest-print-top-bar print-only">
            <div className="manifest-print-title-left">
              <strong className="manifest-doc-title">SEVKİYAT BUL — {activeTitle.toUpperCase()} FİFO MANİFESTİ</strong>
              <span className="manifest-doc-date">Tarih: {new Date().toLocaleString('tr-TR')}</span>
            </div>
            <div className="manifest-print-title-right">
              <span className="manifest-doc-stat">Toplam İlerleme: <strong>{totalScanned} / {totalRequested} Adet</strong></span>
              <span className="manifest-doc-stat">Tamamlanan Referans: <strong>{completedRefs} / {displayManifests.length}</strong></span>
              <span className="manifest-legend">
                <span className="legend-item"><span className="compact-dot filled">●</span> Tarih doldu</span>
                <span className="legend-item"><span className="compact-dot empty">○</span> Tarih açık</span>
              </span>
            </div>
          </div>

          {loading && manifests.length === 0 ? (
            <div className="manifest-loading">Yükleniyor...</div>
          ) : error ? (
            <div className="op-alert error">{error}</div>
          ) : displayManifests.length === 0 ? (
            <div className="manifest-empty">Bu sevkiyat için henüz referans veya etiket bulunmuyor.</div>
          ) : (
            <div className="manifest-compact-list">
              {displayManifests.map((m) => {
                const isComplete = m.is_complete || m.scanned_quantity >= m.requested_quantity;
                return (
                  <div key={m.shipment_id} className={`manifest-ref-block ${isComplete ? 'is-complete' : ''}`}>
                    {/* Compact Section Header */}
                    <div className="manifest-compact-ref-header">
                      <div className="ref-header-left">
                        <strong className="ref-code">{m.reference}</strong>
                        <span className="ref-filter-pill">
                          {m.hourly_fifo ? 'SAAT ÖNCELİKLİ (HH:MM)' : 'GÜN ÖNCELİKLİ'}
                        </span>
                      </div>
                      <div className="ref-header-right">
                        <span className="ref-qty-box">
                          İlerleme: <strong>{m.scanned_quantity} / {m.requested_quantity}</strong>
                        </span>
                        <span className={`ref-status-pill ${isComplete ? 'done' : 'ongoing'}`}>
                          {isComplete ? 'Tamamlandı' : 'Devam ediyor'}
                        </span>
                      </div>
                    </div>

                    {/* Dense Table */}
                    <table className="manifest-dense-table">
                      <thead>
                        <tr>
                          <th style={{ width: '28px', textAlign: 'center' }}>DURUM</th>
                          <th style={{ width: '160px' }}>FİFO TARİHİ</th>
                          <th style={{ width: '150px' }}>REFERANS</th>
                          <th style={{ width: '80px', textAlign: 'right' }}>BEKLENEN</th>
                          <th style={{ width: '80px', textAlign: 'right' }}>OKUTULAN</th>
                          <th>OKUTULAN ETİKET</th>
                          <th style={{ width: '100px', textAlign: 'center' }}>DURUM</th>
                        </tr>
                      </thead>
                      <tbody>
                        {m.items.map((item, itemIdx) => {
                          const scanned = item.scanned_quantity ?? 0;
                          const filled = item.is_scanned || scanned >= item.quantity;
                          const stateLabel = filled ? 'DOLDU' : scanned > 0 ? 'DEVAM' : 'AÇIK';
                          return (
                          <tr key={itemIdx} className={`${filled ? 'scanned-item-row' : 'pending-item-row'}${item.outside_fifo ? ' outside-fifo-row' : ''}`}>
                            <td className="dot-cell" style={{ textAlign: 'center' }}>
                              {item.outside_fifo ? (
                                <TriangleAlert size={14} aria-label="FIFO dışı" />
                              ) : filled ? (
                                <span className="compact-dot filled" title="Tarih doldu">●</span>
                              ) : (
                                <span className="compact-dot empty" title="Tarih açık">○</span>
                              )}
                            </td>
                            <td className="font-mono label-text">{item.fifo_group_date}</td>
                            <td className="ref-cell">{item.reference}</td>
                            <td className="qty-cell" style={{ textAlign: 'right' }}>{item.quantity}</td>
                            <td className="qty-cell" style={{ textAlign: 'right' }}>{item.scanned_quantity ?? 0}</td>
                            <td className="manifest-scan-cell">
                              {(item.scanned_labels ?? []).length === 0 ? (
                                <span className="manifest-scan-empty">—</span>
                              ) : (
                                <span className="manifest-scan-list">
                                  {(item.scanned_labels || []).map(read => (
                                    <span key={read.label} className={`manifest-scan-label${read.outside_fifo ? ' is-outside' : ''}`}>
                                      <span>{read.label}</span>
                                      <em>{read.quantity}</em>
                                    </span>
                                  ))}
                                </span>
                              )}
                            </td>
                            <td style={{ textAlign: 'center' }}>
                              {item.outside_fifo ? (
                                <span className="badge-pill badge-outside" title="Yeniden hesaplamada bu tarihin yerini daha eski bir FIFO aldı">FIFO dışı</span>
                              ) : (
                                <span className={`badge-pill ${filled ? 'badge-scanned' : 'badge-pending'}`}>
                                  {stateLabel}
                                </span>
                              )}
                            </td>
                          </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
