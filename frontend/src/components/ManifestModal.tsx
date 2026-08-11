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

  return (
    <div className="manifest-overlay" onClick={onClose}>
      <div className="manifest-modal" onClick={e => e.stopPropagation()}>
        {/* Printable & Screen Header */}
        <div className="manifest-header no-print">
          <div className="manifest-title">
            <h2>📋 FİFO HESAPLAMA VE SİSTEM MANİFESTİ</h2>
            <div className="manifest-badges">
              <span className="manifest-badge info">{manifests.length} Sevkiyat Referansı</span>
              <span className="manifest-badge ok">{totalScanned} / {totalRequested} Adet Okutuldu</span>
              <span className="manifest-badge pool">{totalLabels} Aday Etiket Havuzda</span>
            </div>
          </div>
          <div className="manifest-actions">
            <button type="button" className="op-btn primary compact" onClick={handlePrint}>
              🖨️ Yazdır / PDF
            </button>
            <button type="button" className="op-btn danger compact" onClick={onClose}>
              ✕ Kapat
            </button>
          </div>
        </div>

        {/* Printable Area Body */}
        <div className="manifest-body printable-content">
          <div className="manifest-print-header print-only">
            <h1>SEVKİYAT BUL — FİFO LİSTESİ VE HESAPLAMA MANİFESTİ</h1>
            <div className="manifest-print-meta">
              <span>Tarih: {new Date().toLocaleString('tr-TR')}</span>
              <span>Toplam Hedef: {totalRequested} adet</span>
              <span>Okutulan: {totalScanned} adet</span>
            </div>
          </div>

          {loading && manifests.length === 0 ? (
            <div className="manifest-loading">Yükleniyor...</div>
          ) : error ? (
            <div className="op-alert error">{error}</div>
          ) : manifests.length === 0 ? (
            <div className="manifest-empty">Henüz aktif bir sevkiyat hesaplaması yok.</div>
          ) : (
            manifests.map((m, idx) => (
              <div key={m.shipment_id} className="manifest-section">
                {idx > 0 && <div className="manifest-divider">- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -</div>}

                <div className="manifest-ref-header">
                  <div className="manifest-ref-info">
                    <span className="manifest-ref-title">{m.reference}</span>
                    <span className="manifest-mode-tag">
                      {m.hourly_fifo ? '⚡ SAAT+TARİH ÖNCELİKLİ (HH:MM)' : '📅 SADECE TARİH ÖNCELİKLİ'}
                    </span>
                  </div>
                  <div className="manifest-ref-stats">
                    <span>Hedef: <strong>{m.requested_quantity}</strong></span>
                    <span>Havuz: <strong>{m.pool_quantity}</strong></span>
                    <span>Okutulan: <strong style={{ color: m.is_complete ? '#10b981' : '#3b82f6' }}>{m.scanned_quantity} / {m.requested_quantity}</strong></span>
                    <span className={`manifest-status-chip ${m.is_complete ? 'done' : 'active'}`}>
                      {m.is_complete ? 'TAMAMLANDI' : 'DEVAM EDİYOR'}
                    </span>
                  </div>
                </div>

                <div className="manifest-table-wrapper">
                  <table className="manifest-table">
                    <thead>
                      <tr>
                        <th style={{ width: '40px' }}>✓</th>
                        <th>ETİKET NO</th>
                        <th>REFERANS</th>
                        <th style={{ textAlign: 'right' }}>MİKTAR</th>
                        <th>FİFO TARİHİ & SAATİ</th>
                        <th>FİFO HESAPLAMA GRUBU</th>
                        <th>DURUM</th>
                      </tr>
                    </thead>
                    <tbody>
                      {m.items.map((item, itemIdx) => (
                        <tr key={itemIdx} className={item.is_scanned ? 'scanned-row' : ''}>
                          <td style={{ textAlign: 'center' }}>
                            <span className={`check-mark ${item.is_scanned ? 'checked' : ''}`}>
                              {item.is_scanned ? '✓' : '○'}
                            </span>
                          </td>
                          <td className="font-mono label-cell">{item.label}</td>
                          <td>{item.reference}</td>
                          <td style={{ textAlign: 'right', fontWeight: 600 }}>{item.quantity}</td>
                          <td className="font-mono">{item.fifo_date}</td>
                          <td className="font-mono text-subtle">{item.fifo_group_date}</td>
                          <td>
                            <span className={`item-status-badge ${item.is_scanned ? 'scanned' : 'pending'}`}>
                              {item.is_scanned ? 'OKUTULDU ✓' : 'BEKLİYOR'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
