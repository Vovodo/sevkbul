import { useCallback, useEffect, useMemo, useState } from 'react';
import { Globe, Layers, Lock, PackageSearch, Printer, Search, X } from 'lucide-react';
import { api, InventoryLabelItem, ShipmentManifest } from '../api';
import Logo from './Logo';

export type BlockedPrintMode = 'stock' | 'shipment';

interface BlockedPrintModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialMode?: BlockedPrintMode;
  initialGroupId?: number | 'all';
}

interface ShipmentBlockedGroup {
  groupId: number;
  groupName: string;
  rows: {
    shipmentId: number;
    reference: string;
    label: string;
    quantity: number;
    fifoTime: string;
    scanned: boolean;
  }[];
  totalQuantity: number;
}

export default function BlockedPrintModal({
  isOpen,
  onClose,
  initialMode = 'stock',
  initialGroupId = 'all',
}: BlockedPrintModalProps) {
  const [mode, setMode] = useState<BlockedPrintMode>(initialMode);
  const [selectedGroupId, setSelectedGroupId] = useState<number | 'all'>(initialGroupId);
  const [stockItems, setStockItems] = useState<InventoryLabelItem[]>([]);
  const [manifests, setManifests] = useState<ShipmentManifest[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    setMode(initialMode);
    setSelectedGroupId(initialGroupId);
  }, [isOpen, initialMode, initialGroupId]);

  const loadData = useCallback(async () => {
    if (!isOpen) return;
    setLoading(true);
    setError('');
    try {
      const [stockRes, manifestRes] = await Promise.all([
        api.getInventoryLabels('', 'blocked', 10000),
        api.getManifest().catch(() => [] as ShipmentManifest[]),
      ]);
      setStockItems(stockRes.items || []);
      setManifests(manifestRes || []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Blokajlı etiket verisi alınamadı');
    } finally {
      setLoading(false);
    }
  }, [isOpen]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Sevkiyat bazlı blokajlıları grupla
  const shipmentGroups = useMemo<ShipmentBlockedGroup[]>(() => {
    const map = new Map<number, ShipmentBlockedGroup>();
    const groupOrder: number[] = [];

    manifests.forEach((m) => {
      const gid = m.group_id || m.shipment_id;
      if (!map.has(gid)) {
        groupOrder.push(gid);
        const idx = groupOrder.length;
        const rawName = m.group_name?.trim();
        map.set(gid, {
          groupId: gid,
          groupName: rawName ? `${idx}. Sevkiyat (${rawName})` : `${idx}. Sevkiyat`,
          rows: [],
          totalQuantity: 0,
        });
      }
      const grp = map.get(gid)!;
      (m.blocked_labels || []).forEach((bl) => {
        grp.rows.push({
          shipmentId: m.shipment_id,
          reference: m.reference,
          label: bl.label,
          quantity: bl.quantity,
          fifoTime: bl.fifo_time,
          scanned: !!bl.scanned,
        });
        grp.totalQuantity += bl.quantity;
      });
    });

    return Array.from(map.values());
  }, [manifests]);

  const qNorm = searchQuery.trim().toLocaleLowerCase('tr-TR');

  const filteredStockItems = useMemo(() => {
    if (!qNorm) return stockItems;
    return stockItems.filter(
      it =>
        it.label.toLocaleLowerCase('tr-TR').includes(qNorm) ||
        it.reference.toLocaleLowerCase('tr-TR').includes(qNorm) ||
        it.fifo_date.toLocaleLowerCase('tr-TR').includes(qNorm)
    );
  }, [stockItems, qNorm]);

  const filteredShipmentGroups = useMemo(() => {
    const base =
      selectedGroupId === 'all'
        ? shipmentGroups
        : shipmentGroups.filter(g => g.groupId === selectedGroupId);

    return base
      .map(g => {
        const rows = !qNorm
          ? g.rows
          : g.rows.filter(
              r =>
                r.label.toLocaleLowerCase('tr-TR').includes(qNorm) ||
                r.reference.toLocaleLowerCase('tr-TR').includes(qNorm) ||
                r.fifoTime.toLocaleLowerCase('tr-TR').includes(qNorm)
            );
        return {
          ...g,
          rows,
          totalQuantity: rows.reduce((s, r) => s + r.quantity, 0),
        };
      })
      .filter(g => g.rows.length > 0 || selectedGroupId === g.groupId);
  }, [shipmentGroups, selectedGroupId, qNorm]);

  if (!isOpen) return null;

  const totalStockBlockedQty = filteredStockItems.reduce((s, i) => s + i.quantity, 0);
  const totalShipmentBlockedLabels = filteredShipmentGroups.reduce((s, g) => s + g.rows.length, 0);
  const totalShipmentBlockedQty = filteredShipmentGroups.reduce((s, g) => s + g.totalQuantity, 0);
  const allShipmentBlockedCount = shipmentGroups.reduce((s, g) => s + g.rows.length, 0);

  const fmtNum = (n: number) =>
    new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2 }).format(n);

  const printDocTitle =
    mode === 'stock'
      ? 'TÜM STOK LİSTESİ BLOKAJLI ETİKETLER RAPORU'
      : selectedGroupId === 'all'
        ? 'TÜM SEVKİYATLAR HESAPLANAN BLOKAJLI ETİKETLER RAPORU'
        : `${shipmentGroups.find(g => g.groupId === selectedGroupId)?.groupName?.toUpperCase() || 'SEVKİYAT'} BLOKAJLI ETİKETLER RAPORU`;

  return (
    <div className="manifest-overlay" onClick={onClose}>
      <div className="manifest-modal blocked-print-modal" onClick={e => e.stopPropagation()}>
        {/* Üst Başlık Çubuğu (Yazdırırken gizlenir) */}
        <div className="manifest-header no-print">
          <div className="manifest-title" style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <Logo size="sm" variant="icon" />
            <div>
              <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <Lock size={18} style={{ color: '#f59e0b' }} />
                <span>BLOKAJLI ETİKETLERİ YAZDIR</span>
              </h2>
              <div className="manifest-badges">
                <span
                  className="manifest-badge"
                  style={{
                    background: 'rgba(245, 158, 11, 0.16)',
                    border: '1px solid rgba(245, 158, 11, 0.45)',
                    color: '#fde68a',
                  }}
                >
                  Stoktaki Toplam Blokajlı: {stockItems.length} Etiket
                </span>
                {shipmentGroups.length > 0 && (
                  <span className="manifest-badge info">
                    Sevkiyatlardaki Blokajlı: {allShipmentBlockedCount} Etiket
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="manifest-actions">
            <button
              type="button"
              className="op-btn primary compact manifest-print-btn"
              onClick={() => window.print()}
              disabled={
                loading ||
                (mode === 'stock' ? filteredStockItems.length === 0 : totalShipmentBlockedLabels === 0)
              }
            >
              <Printer size={15} />
              <span>Yazdır (A4)</span>
            </button>
            <button type="button" className="manifest-close-btn" onClick={onClose} title="Kapat" aria-label="Kapat">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Mod Seçimi ve Sevkiyat Sekmeleri (Yazdırırken gizlenir) */}
        <div className="blocked-print-toolbar no-print">
          <div className="blocked-mode-tabs">
            <button
              type="button"
              className={`blocked-mode-tab ${mode === 'stock' ? 'active' : ''}`}
              onClick={() => setMode('stock')}
            >
              <PackageSearch size={15} />
              <span>Kayıtlı Stoktaki Tüm Blokajlılar ({stockItems.length})</span>
            </button>
            <button
              type="button"
              className={`blocked-mode-tab ${mode === 'shipment' ? 'active' : ''}`}
              onClick={() => setMode('shipment')}
            >
              <Layers size={15} />
              <span>Sevkiyat Bazlı Hesaplanan Blokajlılar ({allShipmentBlockedCount})</span>
            </button>
          </div>

          <div className="blocked-search-box">
            <Search size={14} style={{ color: '#94a3b8' }} />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Etiket no veya referans ara..."
            />
            {searchQuery && (
              <button
                type="button"
                className="stock-clear-btn"
                onClick={() => setSearchQuery('')}
                title="Aramayı temizle"
              >
                <X size={13} />
              </button>
            )}
          </div>
        </div>

        {mode === 'shipment' && shipmentGroups.length > 0 && (
          <div className="blocked-shipment-subtabs no-print">
            <button
              type="button"
              className={`blocked-subtab ${selectedGroupId === 'all' ? 'active' : ''}`}
              onClick={() => setSelectedGroupId('all')}
            >
              <Globe size={13} />
              <span>Tüm Sevkiyatlar ({allShipmentBlockedCount} Blokajlı)</span>
            </button>
            {shipmentGroups.map(grp => (
              <button
                key={grp.groupId}
                type="button"
                className={`blocked-subtab ${selectedGroupId === grp.groupId ? 'active' : ''}`}
                onClick={() => setSelectedGroupId(grp.groupId)}
              >
                <span>{grp.groupName}</span>
                <span className="blocked-subtab-count">{grp.rows.length}</span>
              </button>
            ))}
          </div>
        )}

        {/* Yazdırılabilir Rapor Gövdesi */}
        <div className="manifest-body printable-manifest">
          {/* Yazıcı Başlığı (Sadece kağıt üzerinde görünür) */}
          <div className="manifest-print-top-bar print-only">
            <div className="manifest-print-title-left">
              <strong className="manifest-doc-title">SEVKİYAT BUL — {printDocTitle}</strong>
              <span className="manifest-doc-date">Yazdırma Tarihi: {new Date().toLocaleString('tr-TR')}</span>
            </div>
            <div className="manifest-print-title-right">
              {mode === 'stock' ? (
                <>
                  <span className="manifest-doc-stat">
                    Blokajlı Etiket Sayısı: <strong>{filteredStockItems.length} Adet Etiket</strong>
                  </span>
                  <span className="manifest-doc-stat">
                    Toplam Blokajlı Miktar: <strong>{fmtNum(totalStockBlockedQty)} Adet</strong>
                  </span>
                </>
              ) : (
                <>
                  <span className="manifest-doc-stat">
                    Sevkiyat Blokajlı Etiket: <strong>{totalShipmentBlockedLabels} Adet Etiket</strong>
                  </span>
                  <span className="manifest-doc-stat">
                    Toplam Blokajlı Miktar: <strong>{fmtNum(totalShipmentBlockedQty)} Adet</strong>
                  </span>
                </>
              )}
            </div>
          </div>

          {loading ? (
            <div className="manifest-loading">Blokajlı etiketler yükleniyor...</div>
          ) : error ? (
            <div className="op-alert error">{error}</div>
          ) : mode === 'stock' ? (
            filteredStockItems.length === 0 ? (
              <div className="manifest-empty">
                Kayıtlı stok listesinde blokajlı etiket bulunmuyor.
              </div>
            ) : (
              <div className="manifest-compact-list">
                <div className="manifest-ref-block">
                  <div className="manifest-compact-ref-header">
                    <div className="ref-header-left">
                      <strong className="ref-code">KAYITLI STOK LİSTESİ — TÜM BLOKAJLI ETİKETLER</strong>
                      <span className="ref-filter-pill">FIFO TARİH SIRALI</span>
                    </div>
                    <div className="ref-header-right">
                      <span className="ref-qty-box">
                        Toplam: <strong>{filteredStockItems.length} Etiket • {fmtNum(totalStockBlockedQty)} Adet</strong>
                      </span>
                    </div>
                  </div>

                  <table className="manifest-dense-table">
                    <thead>
                      <tr>
                        <th style={{ width: '48px', textAlign: 'center' }}>SIRA</th>
                        <th style={{ width: '170px' }}>ETİKET NO</th>
                        <th>REFERANS KODU</th>
                        <th style={{ width: '110px', textAlign: 'right' }}>MİKTAR</th>
                        <th style={{ width: '150px' }}>FIFO TARİHİ</th>
                        <th style={{ width: '110px', textAlign: 'center' }}>DURUM</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredStockItems.map((item, idx) => (
                        <tr key={item.id}>
                          <td style={{ textAlign: 'center', fontWeight: 700 }}>{idx + 1}</td>
                          <td className="font-mono label-text" style={{ fontWeight: 700 }}>{item.label}</td>
                          <td className="ref-cell" style={{ fontWeight: 700 }}>{item.reference}</td>
                          <td className="qty-cell" style={{ textAlign: 'right', fontWeight: 700 }}>
                            {fmtNum(item.quantity)}
                          </td>
                          <td className="font-mono">{item.fifo_date}</td>
                          <td style={{ textAlign: 'center' }}>
                            <span className={`badge-pill ${item.scanned ? 'badge-scanned' : 'badge-pending'}`}>
                              {item.scanned ? 'OKUTULDU' : item.hidden ? 'GİZLİ' : 'BLOKAJLI'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          ) : shipmentGroups.length === 0 ? (
            <div className="manifest-empty">
              Henüz aktif sevkiyat oluşturulmamış. Önce sevkiyat oluşturun veya "Kayıtlı Stoktaki Tüm Blokajlılar" sekmesini kullanın.
            </div>
          ) : totalShipmentBlockedLabels === 0 ? (
            <div className="manifest-empty">
              Seçili sevkiyatın FIFO hesabında blokajlı etiket bulunmuyor.
            </div>
          ) : (
            <div className="manifest-compact-list">
              {filteredShipmentGroups.map(grp => (
                <div key={grp.groupId} className="manifest-ref-block">
                  <div className="manifest-compact-ref-header">
                    <div className="ref-header-left">
                      <strong className="ref-code">{grp.groupName}</strong>
                      <span className="ref-filter-pill">SEVKİYAT BLOKAJ LİSTESİ</span>
                    </div>
                    <div className="ref-header-right">
                      <span className="ref-qty-box">
                        Blokajlı: <strong>{grp.rows.length} Etiket • {fmtNum(grp.totalQuantity)} Adet</strong>
                      </span>
                    </div>
                  </div>

                  <table className="manifest-dense-table">
                    <thead>
                      <tr>
                        <th style={{ width: '48px', textAlign: 'center' }}>SIRA</th>
                        <th style={{ width: '170px' }}>ETİKET NO</th>
                        <th>REFERANS KODU</th>
                        <th style={{ width: '110px', textAlign: 'right' }}>MİKTAR</th>
                        <th style={{ width: '150px' }}>FIFO TARİHİ</th>
                        <th style={{ width: '110px', textAlign: 'center' }}>DURUM</th>
                      </tr>
                    </thead>
                    <tbody>
                      {grp.rows.map((row, rIdx) => (
                        <tr key={`${row.shipmentId}-${row.label}-${rIdx}`}>
                          <td style={{ textAlign: 'center', fontWeight: 700 }}>{rIdx + 1}</td>
                          <td className="font-mono label-text" style={{ fontWeight: 700 }}>{row.label}</td>
                          <td className="ref-cell" style={{ fontWeight: 700 }}>{row.reference}</td>
                          <td className="qty-cell" style={{ textAlign: 'right', fontWeight: 700 }}>
                            {fmtNum(row.quantity)}
                          </td>
                          <td className="font-mono">{row.fifoTime}</td>
                          <td style={{ textAlign: 'center' }}>
                            <span className={`badge-pill ${row.scanned ? 'badge-scanned' : 'badge-pending'}`}>
                              {row.scanned ? 'OKUTULDU' : 'BEKLİYOR'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
