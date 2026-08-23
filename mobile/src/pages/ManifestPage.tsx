import { useState, useMemo } from 'react';
import { Search, RefreshCw, CheckCircle2, Clock } from 'lucide-react';
import { ShipmentManifest } from '../api';
import { triggerTapHaptic } from '../audio/audioEngine';

interface ManifestPageProps {
  manifests: ShipmentManifest[];
  onRefresh: () => void;
}

type FilterMode = 'all' | 'scanned' | 'pending';

export default function ManifestPage({ manifests, onRefresh }: ManifestPageProps) {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [filterMode, setFilterMode] = useState<FilterMode>('all');
  const [selectedRef, setSelectedRef] = useState<string>('all');
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  const handleRefresh = async () => {
    void triggerTapHaptic();
    setIsRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setIsRefreshing(false);
    }
  };

  const totalRequested = manifests.reduce((sum, m) => sum + m.requested_quantity, 0);
  const totalScanned = manifests.reduce((sum, m) => sum + m.scanned_quantity, 0);
  const totalLabels = manifests.reduce((sum, m) => sum + m.items.length, 0);

  const referencesList = useMemo(() => {
    return Array.from(new Set(manifests.map((m) => m.reference)));
  }, [manifests]);

  // Flatten items with reference info for high-speed mobile listing
  const filteredManifests = useMemo(() => {
    return manifests
      .filter((m) => selectedRef === 'all' || m.reference === selectedRef)
      .map((m) => {
        const filteredItems = m.items.filter((item) => {
          // Status filter
          if (filterMode === 'scanned' && !item.is_scanned) return false;
          if (filterMode === 'pending' && item.is_scanned) return false;

          // Search query
          if (searchQuery.trim()) {
            const q = searchQuery.toLowerCase().trim();
            return item.label.toLowerCase().includes(q) || item.reference.toLowerCase().includes(q);
          }
          return true;
        });

        return {
          ...m,
          items: filteredItems,
        };
      })
      .filter((m) => m.items.length > 0 || (searchQuery === '' && filterMode === 'all'));
  }, [manifests, selectedRef, filterMode, searchQuery]);

  return (
    <div className="mobile-page manifest-page">
      <div className="page-section-header">
        <div>
          <h2>FİFO Manifesti</h2>
          <span className="page-section-desc">Aday etiket havuzu ve durum raporu</span>
        </div>
        <button
          type="button"
          className="icon-action-btn"
          onClick={handleRefresh}
          disabled={isRefreshing}
          title="Yenile"
        >
          <RefreshCw size={18} className={isRefreshing ? 'spin-anim' : ''} />
        </button>
      </div>

      {/* Stats Summary Bar */}
      <div className="manifest-stats-card">
        <div className="stat-box">
          <span className="stat-key">İlerleme</span>
          <strong className="stat-val text-primary">{totalScanned} / {totalRequested}</strong>
        </div>
        <div className="stat-divider" />
        <div className="stat-box">
          <span className="stat-key">Aday Havuz</span>
          <strong className="stat-val">{totalLabels} Etiket</strong>
        </div>
        <div className="stat-divider" />
        <div className="stat-box">
          <span className="stat-key">Lejant</span>
          <div className="stat-legend">
            <span><span className="compact-dot filled">●</span> Bulundu</span>
            <span><span className="compact-dot empty">○</span> Bekliyor</span>
          </div>
        </div>
      </div>

      {/* Search & Filter Toolbar */}
      <div className="manifest-toolbar">
        <div className="search-bar">
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="search-input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Etiket veya referans ara..."
          />
          {searchQuery && (
            <button type="button" className="search-clear" onClick={() => setSearchQuery('')}>
              ✕
            </button>
          )}
        </div>

        {/* Filter Pills */}
        <div className="filter-pills-row">
          <button
            type="button"
            className={`filter-pill ${filterMode === 'all' ? 'active' : ''}`}
            onClick={() => {
              void triggerTapHaptic();
              setFilterMode('all');
            }}
          >
            Tümü
          </button>
          <button
            type="button"
            className={`filter-pill ${filterMode === 'scanned' ? 'active' : ''}`}
            onClick={() => {
              void triggerTapHaptic();
              setFilterMode('scanned');
            }}
          >
            <span className="compact-dot filled" style={{ fontSize: '0.8rem' }}>●</span>
            <span>Bulunanlar</span>
          </button>
          <button
            type="button"
            className={`filter-pill ${filterMode === 'pending' ? 'active' : ''}`}
            onClick={() => {
              void triggerTapHaptic();
              setFilterMode('pending');
            }}
          >
            <span className="compact-dot empty" style={{ fontSize: '0.8rem' }}>○</span>
            <span>Bekleyenler</span>
          </button>

          {referencesList.length > 1 && (
            <select
              className="ref-filter-select"
              value={selectedRef}
              onChange={(e) => setSelectedRef(e.target.value)}
            >
              <option value="all">Tüm Referanslar ({referencesList.length})</option>
              {referencesList.map((ref) => (
                <option key={ref} value={ref}>
                  {ref}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* Manifest List */}
      {filteredManifests.length === 0 ? (
        <div className="empty-state-card">
          <p>Kriterlere uygun etiket kaydı bulunamadı.</p>
        </div>
      ) : (
        <div className="manifest-blocks-list">
          {filteredManifests.map((m) => {
            const isComplete = m.is_complete || m.scanned_quantity >= m.requested_quantity;
            return (
              <div key={m.shipment_id} className={`manifest-block-card ${isComplete ? 'is-complete' : ''}`}>
                <div className="block-header">
                  <div className="block-title">
                    <strong className="block-ref font-mono">{m.reference}</strong>
                    <span className="block-mode">{m.hourly_fifo ? 'SAAT ÖNCELİKLİ' : 'GÜN ÖNCELİKLİ'}</span>
                  </div>

                  <div className="block-progress-badge">
                    <span>{m.scanned_quantity} / {m.requested_quantity} Adet</span>
                    {isComplete ? <CheckCircle2 size={14} className="text-success" /> : <Clock size={14} className="text-primary" />}
                  </div>
                </div>

                <div className="block-table-wrapper">
                  <table className="mobile-manifest-table">
                    <thead>
                      <tr>
                        <th style={{ width: '28px', textAlign: 'center' }}>DURUM</th>
                        <th>ETİKET NO</th>
                        <th style={{ textAlign: 'right' }}>MİKTAR</th>
                        <th>FİFO TARİH & SAAT</th>
                      </tr>
                    </thead>
                    <tbody>
                      {m.items.map((item, idx) => (
                        <tr key={idx} className={item.is_scanned ? 'row-scanned' : 'row-pending'}>
                          <td style={{ textAlign: 'center' }}>
                            {item.is_scanned ? (
                              <span className="compact-dot filled">●</span>
                            ) : (
                              <span className="compact-dot empty">○</span>
                            )}
                          </td>
                          <td className="font-mono label-cell">{item.label}</td>
                          <td className="qty-cell" style={{ textAlign: 'right' }}>{item.quantity}</td>
                          <td className="font-mono date-cell">{item.fifo_date}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
