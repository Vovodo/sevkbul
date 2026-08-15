import { useEffect, useState, useCallback } from 'react';
import { api, ShipmentManifest } from '../api';
import { useLiveUpdates } from '../useLiveUpdates';

interface ManifestModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function ManifestModal({ isOpen, onClose }: ManifestModalProps) {
  const [manifests, setManifests] = useState<ShipmentManifest[]>([]);
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

  if (!isOpen) return null;

  const handlePrint = () => {
    window.print();
  };

  const totalRequested = manifests.reduce((sum, m) => sum + m.requested_quantity, 0);
  const totalScanned = manifests.reduce((sum, m) => sum + m.scanned_quantity, 0);
  const totalLabels = manifests.reduce((sum, m) => sum + m.items.length, 0);
  const completedRefs = manifests.filter(m => m.is_complete || m.scanned_quantity >= m.requested_quantity).length;

  return (
    <div className="manifest-overlay" onClick={onClose}>
      <div className="manifest-modal" onClick={e => e.stopPropagation()}>
        {/* Screen Header */}
        <div className="manifest-header no-print">
          <div className="manifest-title">
            <h2>📋 FİFO HESAPLAMA VE SİSTEM MANİFESTİ</h2>
            <div className="manifest-badges">
              <span className="manifest-badge info">{manifests.length} Referans</span>
              <span className="manifest-badge ok">Toplam: {totalScanned} / {totalRequested} Adet ({completedRefs}/{manifests.length} Tamamlandı)</span>
              <span className="manifest-badge pool">{totalLabels} Aday Etiket</span>
            </div>
          </div>
          <div className="manifest-actions">
            <button type="button" className="op-btn primary compact" onClick={handlePrint} style={{ fontWeight: 700 }}>
              🖨️ Yazdır / PDF İndir
            </button>
            <button type="button" className="op-btn danger compact" onClick={onClose}>
              ✕ Kapat
            </button>
          </div>
        </div>

        {/* Printable & Compact Container */}
        <div className="manifest-body printable-manifest">
          {/* Print Title Header (Only visible on printout) */}
          <div className="manifest-print-top-bar print-only">
            <div className="manifest-print-title-left">
              <strong className="manifest-doc-title">SEVKİYAT BUL — FİFO YÜKLEME VE HESAPLAMA MANİFESTİ</strong>
              <span className="manifest-doc-date">Tarih: {new Date().toLocaleString('tr-TR')}</span>
            </div>
            <div className="manifest-print-title-right">
              <span className="manifest-doc-stat">Toplam İlerleme: <strong>{totalScanned} / {totalRequested} Adet</strong></span>
              <span className="manifest-doc-stat">Tamamlanan Referans: <strong>{completedRefs} / {manifests.length}</strong></span>
              <span className="manifest-legend">
                <span className="legend-item"><span className="compact-dot filled">●</span> Bulunan (Okutuldu)</span>
                <span className="legend-item"><span className="compact-dot empty">○</span> Bulunamayan (Bekliyor)</span>
              </span>
            </div>
          </div>

          {loading && manifests.length === 0 ? (
            <div className="manifest-loading">Yükleniyor...</div>
          ) : error ? (
            <div className="op-alert error">{error}</div>
          ) : manifests.length === 0 ? (
            <div className="manifest-empty">Henüz aktif bir sevkiyat hesaplaması yok.</div>
          ) : (
            <div className="manifest-compact-list">
              {manifests.map((m) => {
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
                          {isComplete ? 'TAMAMLANDI ✓' : 'DEVAM EDİYOR'}
                        </span>
                      </div>
                    </div>

                    {/* Dense Table */}
                    <table className="manifest-dense-table">
                      <thead>
                        <tr>
                          <th style={{ width: '28px', textAlign: 'center' }}>DURUM</th>
                          <th style={{ width: '130px' }}>ETİKET NO</th>
                          <th style={{ width: '150px' }}>REFERANS</th>
                          <th style={{ width: '65px', textAlign: 'right' }}>MİKTAR</th>
                          <th style={{ width: '140px' }}>FİFO TARİH & SAAT</th>
                          <th style={{ width: '140px' }}>FİFO GRUBU</th>
                          <th style={{ width: '85px', textAlign: 'center' }}>DURUM</th>
                        </tr>
                      </thead>
                      <tbody>
                        {m.items.map((item, itemIdx) => (
                          <tr key={itemIdx} className={item.is_scanned ? 'scanned-item-row' : 'pending-item-row'}>
                            <td className="dot-cell" style={{ textAlign: 'center' }}>
                              {item.is_scanned ? (
                                <span className="compact-dot filled" title="Okutuldu / Bulundu">●</span>
                              ) : (
                                <span className="compact-dot empty" title="Bekliyor / Bulunamadı">○</span>
                              )}
                            </td>
                            <td className="font-mono label-text">{item.label}</td>
                            <td className="ref-cell">{item.reference}</td>
                            <td className="qty-cell" style={{ textAlign: 'right' }}>{item.quantity}</td>
                            <td className="font-mono date-cell">{item.fifo_date}</td>
                            <td className="font-mono date-cell text-muted">{item.fifo_group_date}</td>
                            <td style={{ textAlign: 'center' }}>
                              <span className={`badge-pill ${item.is_scanned ? 'badge-scanned' : 'badge-pending'}`}>
                                {item.is_scanned ? 'OKUTULDU' : 'BEKLİYOR'}
                              </span>
                            </td>
                          </tr>
                        ))}
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
