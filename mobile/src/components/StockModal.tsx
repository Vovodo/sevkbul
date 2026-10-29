import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, Eye, EyeOff, Filter, RotateCcw, Search, TriangleAlert, X } from 'lucide-react';
import { api, InventoryLabelItem, InventoryListResponse } from '../api';
import Logo from './Logo';

interface StockModalProps {
  isOpen: boolean;
  onClose: () => void;
  onStockChanged?: () => void;
}

type StockFilter = 'all' | 'active' | 'hidden' | 'blocked';
type SortField = 'label' | 'reference' | 'quantity' | 'fifo_date' | 'blocked' | 'status';
type SortDir = 'asc' | 'desc';
type OpenMenuType = 'label' | 'reference' | 'quantity' | 'fifo_date' | null;

function parseTrDate(str: string): number {
  const m = str.match(/^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
  if (!m) return 0;
  const [, d, mo, y, h = '00', mi = '00'] = m;
  return new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi)).getTime();
}

function itemStatusText(item: InventoryLabelItem): 'OKUTULDU' | 'GİZLİ' | 'AKTİF' {
  if (item.scanned) return 'OKUTULDU';
  if (item.hidden) return 'GİZLİ';
  return 'AKTİF';
}

export default function StockModal({ isOpen, onClose, onStockChanged }: StockModalProps) {
  const [data, setData] = useState<InventoryListResponse | null>(null);
  const [query, setQuery] = useState('');
  const [filterMode, setFilterMode] = useState<StockFilter>('all');
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [error, setError] = useState('');

  // Excel tarzı sütun bazlı filtreler
  const [colLabel, setColLabel] = useState('');
  const [selectedLabels, setSelectedLabels] = useState<Set<string> | null>(null);
  const [colRefText, setColRefText] = useState('');
  const [selectedRefs, setSelectedRefs] = useState<Set<string> | null>(null);
  const [selectedQtys, setSelectedQtys] = useState<Set<number> | null>(null);
  const [colDateText, setColDateText] = useState('');
  const [selectedDates, setSelectedDates] = useState<Set<string> | null>(null);
  const [colBlocked, setColBlocked] = useState<'ALL' | 'YANLIŞ' | 'DOĞRU'>('ALL');
  const [colStatus, setColStatus] = useState<'ALL' | 'AKTİF' | 'OKUTULDU' | 'GİZLİ'>('ALL');

  // Açılır Excel filtre menüsü
  const [openMenu, setOpenMenu] = useState<OpenMenuType>(null);
  const [menuSearch, setMenuSearch] = useState('');
  const menuWrapRef = useRef<HTMLTableSectionElement | null>(null);

  // Sıralama
  const [sortField, setSortField] = useState<SortField | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.getInventoryLabels('', 'all', 10000);
      setData(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Stok listesi alınamadı');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    void fetchList();
  }, [isOpen, fetchList]);

  useEffect(() => {
    if (!openMenu) return;
    const onDocClick = (e: MouseEvent) => {
      if (menuWrapRef.current && !menuWrapRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [openMenu]);

  const allItems = data?.items || [];

  // Belirli bir sütun hariç diğer tüm aktif filtreleri uygulayan yardımcı (Excel cascading dropdown mantığı)
  const matchesExcept = useCallback(
    (item: InventoryLabelItem, ignoreCol?: 'label' | 'reference' | 'quantity' | 'fifo_date') => {
      if (filterMode === 'active' && item.hidden) return false;
      if (filterMode === 'hidden' && !item.hidden) return false;
      if (filterMode === 'blocked' && !item.blocked) return false;

      const qGlobal = query.trim().toLocaleLowerCase('tr-TR');
      if (qGlobal) {
        const hay = `${item.label} ${item.reference} ${item.fifo_date} ${item.quantity}`.toLocaleLowerCase('tr-TR');
        if (!hay.includes(qGlobal)) return false;
      }

      if (ignoreCol !== 'label') {
        const qLbl = colLabel.trim().toLocaleLowerCase('tr-TR');
        if (qLbl && !item.label.toLocaleLowerCase('tr-TR').includes(qLbl)) return false;
        if (selectedLabels !== null && !selectedLabels.has(item.label)) return false;
      }
      if (ignoreCol !== 'reference') {
        const qRef = colRefText.trim().toLocaleLowerCase('tr-TR');
        if (qRef && !item.reference.toLocaleLowerCase('tr-TR').includes(qRef)) return false;
        if (selectedRefs !== null && !selectedRefs.has(item.reference)) return false;
      }
      if (ignoreCol !== 'quantity') {
        if (selectedQtys !== null && !selectedQtys.has(item.quantity)) return false;
      }
      if (ignoreCol !== 'fifo_date') {
        const qDate = colDateText.trim().toLocaleLowerCase('tr-TR');
        if (qDate && !item.fifo_date.toLocaleLowerCase('tr-TR').includes(qDate)) return false;
        if (selectedDates !== null && !selectedDates.has(item.fifo_date.slice(0, 10))) return false;
      }

      if (colBlocked === 'DOĞRU' && !item.blocked) return false;
      if (colBlocked === 'YANLIŞ' && item.blocked) return false;

      const st = itemStatusText(item);
      if (colStatus !== 'ALL' && st !== colStatus) return false;

      return true;
    },
    [
      filterMode,
      query,
      colLabel,
      selectedLabels,
      colRefText,
      selectedRefs,
      selectedQtys,
      colDateText,
      selectedDates,
      colBlocked,
      colStatus,
    ]
  );

  // Her sütunun açılır menüsü, diğer aktif filtrelere göre bağlamsal (cascading) benzersiz değerleri gösterir
  const uniqueLabels = useMemo(() => {
    const set = new Set<string>();
    allItems.forEach(i => {
      if (matchesExcept(i, 'label')) set.add(i.label);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'tr-TR', { numeric: true }));
  }, [allItems, matchesExcept]);

  const uniqueRefs = useMemo(() => {
    const set = new Set<string>();
    allItems.forEach(i => {
      if (matchesExcept(i, 'reference')) set.add(i.reference);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'tr-TR'));
  }, [allItems, matchesExcept]);

  const uniqueQtys = useMemo(() => {
    const set = new Set<number>();
    allItems.forEach(i => {
      if (matchesExcept(i, 'quantity')) set.add(i.quantity);
    });
    return Array.from(set).sort((a, b) => a - b);
  }, [allItems, matchesExcept]);

  const uniqueDates = useMemo(() => {
    const set = new Set<string>();
    allItems.forEach(i => {
      if (matchesExcept(i, 'fifo_date')) set.add(i.fifo_date.slice(0, 10));
    });
    return Array.from(set).sort((a, b) => parseTrDate(a) - parseTrDate(b));
  }, [allItems, matchesExcept]);

  const hasActiveColumnFilters =
    query.trim() !== '' ||
    filterMode !== 'all' ||
    colLabel.trim() !== '' ||
    selectedLabels !== null ||
    colRefText.trim() !== '' ||
    selectedRefs !== null ||
    selectedQtys !== null ||
    colDateText.trim() !== '' ||
    selectedDates !== null ||
    colBlocked !== 'ALL' ||
    colStatus !== 'ALL' ||
    sortField !== null;

  const resetAllFilters = () => {
    setQuery('');
    setFilterMode('all');
    setColLabel('');
    setSelectedLabels(null);
    setColRefText('');
    setSelectedRefs(null);
    setSelectedQtys(null);
    setColDateText('');
    setSelectedDates(null);
    setColBlocked('ALL');
    setColStatus('ALL');
    setSortField(null);
    setOpenMenu(null);
  };

  const filteredItems = useMemo(() => {
    const list = allItems.filter(item => matchesExcept(item));
    if (!sortField) return list;

    const sorted = [...list].sort((a, b) => {
      let cmp = 0;
      if (sortField === 'label') {
        cmp = a.label.localeCompare(b.label, 'tr-TR', { numeric: true });
      } else if (sortField === 'reference') {
        cmp = a.reference.localeCompare(b.reference, 'tr-TR');
      } else if (sortField === 'quantity') {
        cmp = a.quantity - b.quantity;
      } else if (sortField === 'fifo_date') {
        cmp = parseTrDate(a.fifo_date) - parseTrDate(b.fifo_date);
      } else if (sortField === 'blocked') {
        cmp = Number(a.blocked) - Number(b.blocked);
      } else if (sortField === 'status') {
        cmp = itemStatusText(a).localeCompare(itemStatusText(b), 'tr-TR');
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return sorted;
  }, [allItems, matchesExcept, sortField, sortDir]);

  const toggleSort = (field: SortField) => {
    if (sortField !== field) {
      setSortField(field);
      setSortDir('asc');
    } else if (sortDir === 'asc') {
      setSortDir('desc');
    } else {
      setSortField(null);
    }
  };

  const renderSortIcon = (field: SortField) => {
    if (sortField !== field) return <ArrowUpDown size={12} style={{ opacity: 0.45 }} />;
    return sortDir === 'asc' ? <ArrowUp size={12} style={{ color: '#60a5fa' }} /> : <ArrowDown size={12} style={{ color: '#60a5fa' }} />;
  };

  const handleToggleHidden = async (item: InventoryLabelItem) => {
    if (busyId != null || bulkBusy) return;
    setBusyId(item.id);
    setError('');
    try {
      const updated = await api.setInventoryLabelHidden(item.id, !item.hidden);
      setData(prev => {
        if (!prev) return prev;
        const deltaHidden = updated.hidden ? 1 : -1;
        return {
          ...prev,
          active_count: Math.max(0, prev.active_count - deltaHidden),
          hidden_count: Math.max(0, prev.hidden_count + deltaHidden),
          items: prev.items.map(row => (row.id === updated.id ? updated : row)),
        };
      });
      onStockChanged?.();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Etiket durumu güncellenemedi');
    } finally {
      setBusyId(null);
    }
  };

  const handleBulkHidden = async (targetHidden: boolean) => {
    if (bulkBusy || busyId != null) return;
    const candidates = filteredItems.filter(i => !i.scanned && i.hidden !== targetHidden);
    if (candidates.length === 0) return;

    setBulkBusy(true);
    setError('');
    const targetIds = new Set(candidates.map(i => i.id));
    try {
      await api.setInventoryLabelsBulkHidden(Array.from(targetIds), targetHidden);
      setData(prev => {
        if (!prev) return prev;
        const nextItems = prev.items.map(row =>
          targetIds.has(row.id) ? { ...row, hidden: targetHidden } : row
        );
        const hiddenCnt = nextItems.filter(r => r.hidden).length;
        return {
          ...prev,
          active_count: Math.max(0, prev.total - hiddenCnt),
          hidden_count: hiddenCnt,
          items: nextItems,
        };
      });
      onStockChanged?.();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Toplu işlem tamamlanamadı');
    } finally {
      setBulkBusy(false);
    }
  };

  if (!isOpen) return null;

  const filteredTotalQty = filteredItems.reduce((sum, i) => sum + i.quantity, 0);
  const canHideCount = filteredItems.filter(i => !i.scanned && !i.hidden).length;
  const canUnhideCount = filteredItems.filter(i => !i.scanned && i.hidden).length;

  return (
    <div className="manifest-overlay" onClick={onClose}>
      <div className="manifest-modal stock-modal" onClick={e => e.stopPropagation()}>
        <div className="manifest-header no-print">
          <div className="manifest-title" style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <Logo size="sm" variant="icon" />
            <div>
              <h2>STOK ETİKET YÖNETİMİ</h2>
              <div className="manifest-badges">
                <span className="manifest-badge info">Toplam: {data?.total ?? 0} Etiket</span>
                <span className="manifest-badge ok">Aktif: {data?.active_count ?? 0}</span>
                <span
                  className="manifest-badge"
                  style={{
                    background: 'rgba(239, 68, 68, 0.16)',
                    border: '1px solid rgba(239, 68, 68, 0.45)',
                    color: '#fca5a5',
                  }}
                >
                  Gizlenen: {data?.hidden_count ?? 0}
                </span>
                <span
                  className="manifest-badge"
                  style={{
                    background: 'rgba(245, 158, 11, 0.16)',
                    border: '1px solid rgba(245, 158, 11, 0.45)',
                    color: '#fde68a',
                  }}
                >
                  Blokajlı: {data?.blocked_count ?? 0}
                </span>
                <span className="manifest-badge pool">
                  Gösterilen: {filteredItems.length} Etiket ({filteredTotalQty.toLocaleString('tr-TR')} Adet)
                </span>
              </div>
            </div>
          </div>
          <div className="manifest-actions">
            {canHideCount > 0 && (
              <button
                type="button"
                className="op-btn secondary compact stock-bulk-hide-btn"
                disabled={bulkBusy || busyId != null}
                onClick={() => void handleBulkHidden(true)}
                title={`Ekranda listelenen ${canHideCount} adet aktif etiketi tek seferde gizliye al`}
              >
                <EyeOff size={14} />
                <span>{bulkBusy ? 'İşleniyor...' : `Toplu Gizle (${canHideCount})`}</span>
              </button>
            )}
            {canUnhideCount > 0 && (
              <button
                type="button"
                className="op-btn primary compact stock-bulk-unhide-btn"
                disabled={bulkBusy || busyId != null}
                onClick={() => void handleBulkHidden(false)}
                title={`Ekranda listelenen ${canUnhideCount} adet gizli etiketi tek seferde aktif et`}
              >
                <Eye size={14} />
                <span>{bulkBusy ? 'İşleniyor...' : `Toplu Aktif Et (${canUnhideCount})`}</span>
              </button>
            )}
            {hasActiveColumnFilters && (
              <button
                type="button"
                className="op-btn secondary compact"
                onClick={resetAllFilters}
                title="Tüm sütun filtrelerini ve sıralamayı sıfırla"
              >
                <RotateCcw size={14} /> Filtreleri Temizle
              </button>
            )}
            <button type="button" className="op-btn danger compact" onClick={onClose}>
              <X size={15} /> Kapat
            </button>
          </div>
        </div>

        <div
          className="stock-modal-toolbar"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '0.65rem',
            flexWrap: 'wrap',
            padding: '0.65rem 1.25rem',
            background: '#0d1527',
            borderBottom: '1px solid #1e293b',
          }}
        >
          <div className="sc-search-wrap" style={{ maxWidth: '320px', flex: '1 1 220px' }}>
            <Search size={14} aria-hidden />
            <input
              type="text"
              className="sc-search-input"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Hızlı genel arama (etiket, referans, tarih)..."
              autoFocus
            />
          </div>

          <div className="sc-filter-pills">
            <button
              type="button"
              className={`sc-filter-pill ${filterMode === 'all' ? 'active' : ''}`}
              onClick={() => setFilterMode('all')}
            >
              Tümü ({data?.total ?? 0})
            </button>
            <button
              type="button"
              className={`sc-filter-pill ${filterMode === 'active' ? 'active' : ''}`}
              onClick={() => setFilterMode('active')}
            >
              Aktif ({data?.active_count ?? 0})
            </button>
            <button
              type="button"
              className={`sc-filter-pill is-short ${filterMode === 'hidden' ? 'active' : ''}`}
              onClick={() => setFilterMode('hidden')}
            >
              Gizlenen ({data?.hidden_count ?? 0})
            </button>
            <button
              type="button"
              className={`sc-filter-pill is-blocked ${filterMode === 'blocked' ? 'active' : ''}`}
              onClick={() => setFilterMode('blocked')}
            >
              Blokajlı ({data?.blocked_count ?? 0})
            </button>
          </div>
        </div>

        <div className="manifest-body">
          <p className="op-file-hint" style={{ margin: '0 0 0.65rem' }}>
            Sütun başlıklarına tıklayarak sıralayabilir, altlarındaki kutulardan veya filtre ikonundan (<Filter size={11} style={{ display: 'inline', verticalAlign: 'middle' }} />) tıpkı Excel'deki gibi istediğiniz etiket, referans, miktar, tarih, blokaj ve durumu filtreleyebilirsiniz.
          </p>

          {error && <div className="op-alert error">{error}</div>}

          {loading && !data ? (
            <div className="manifest-loading">Stok etiketleri yükleniyor...</div>
          ) : (
            <div className="manifest-ref-block" style={{ overflow: 'visible' }}>
              <table className="manifest-dense-table stock-excel-table">
                <thead ref={menuWrapRef}>
                  <tr>
                    <th style={{ width: '175px' }}>
                      <div className="excel-th-wrap">
                        <button type="button" className="excel-th-btn" onClick={() => toggleSort('label')}>
                          <span>ETİKET NO</span>
                          {renderSortIcon('label')}
                        </button>
                        <button
                          type="button"
                          className={`excel-filter-trigger ${selectedLabels !== null ? 'is-filtered' : ''}`}
                          onClick={() => {
                            setMenuSearch('');
                            setOpenMenu(m => (m === 'label' ? null : 'label'));
                          }}
                          title="Excel Etiket No Filtresi"
                        >
                          <Filter size={12} />
                        </button>
                        {openMenu === 'label' && (
                          <div className="excel-dropdown" onClick={e => e.stopPropagation()}>
                            <div className="excel-dropdown-search">
                              <Search size={12} />
                              <input
                                type="text"
                                value={menuSearch}
                                onChange={e => setMenuSearch(e.target.value)}
                                placeholder="Etiket listesinde ara..."
                                autoFocus
                              />
                            </div>
                            <div className="excel-dropdown-actions">
                              <button
                                type="button"
                                onClick={() => {
                                  const q = menuSearch.trim().toLocaleLowerCase('tr-TR');
                                  if (!q) {
                                    setSelectedLabels(null);
                                  } else {
                                    const matching = uniqueLabels.filter(l => l.toLocaleLowerCase('tr-TR').includes(q));
                                    setSelectedLabels(new Set(matching));
                                  }
                                }}
                              >
                                {menuSearch.trim() ? 'Arananları Seç' : 'Tümünü Seç'}
                              </button>
                              <button type="button" onClick={() => setSelectedLabels(new Set())}>Temizle</button>
                            </div>
                            <div className="excel-dropdown-list">
                              {uniqueLabels
                                .filter(l => !menuSearch.trim() || l.toLocaleLowerCase('tr-TR').includes(menuSearch.trim().toLocaleLowerCase('tr-TR')))
                                .slice(0, 300)
                                .map(lbl => {
                                  const checked = selectedLabels === null || selectedLabels.has(lbl);
                                  return (
                                    <label key={lbl} className="excel-dropdown-item">
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={() => {
                                          setSelectedLabels(prev => {
                                            const base = prev === null ? new Set(uniqueLabels) : new Set(prev);
                                            if (base.has(lbl)) base.delete(lbl);
                                            else base.add(lbl);
                                            return base.size === uniqueLabels.length ? null : base;
                                          });
                                        }}
                                      />
                                      <span>{lbl}</span>
                                    </label>
                                  );
                                })}
                            </div>
                          </div>
                        )}
                      </div>
                    </th>
                    <th>
                      <div className="excel-th-wrap">
                        <button type="button" className="excel-th-btn" onClick={() => toggleSort('reference')}>
                          <span>REFERANS</span>
                          {renderSortIcon('reference')}
                        </button>
                        <button
                          type="button"
                          className={`excel-filter-trigger ${selectedRefs !== null ? 'is-filtered' : ''}`}
                          onClick={() => {
                            setMenuSearch('');
                            setOpenMenu(m => (m === 'reference' ? null : 'reference'));
                          }}
                          title="Excel Referans Filtresi"
                        >
                          <Filter size={12} />
                        </button>
                        {openMenu === 'reference' && (
                          <div className="excel-dropdown" onClick={e => e.stopPropagation()}>
                            <div className="excel-dropdown-search">
                              <Search size={12} />
                              <input
                                type="text"
                                value={menuSearch}
                                onChange={e => setMenuSearch(e.target.value)}
                                placeholder="Referans listesinde ara..."
                                autoFocus
                              />
                            </div>
                            <div className="excel-dropdown-actions">
                              <button
                                type="button"
                                onClick={() => {
                                  const q = menuSearch.trim().toLocaleLowerCase('tr-TR');
                                  if (!q) {
                                    setSelectedRefs(null);
                                  } else {
                                    const matching = uniqueRefs.filter(r => r.toLocaleLowerCase('tr-TR').includes(q));
                                    setSelectedRefs(new Set(matching));
                                  }
                                }}
                              >
                                {menuSearch.trim() ? 'Arananları Seç' : 'Tümünü Seç'}
                              </button>
                              <button type="button" onClick={() => setSelectedRefs(new Set())}>Temizle</button>
                            </div>
                            <div className="excel-dropdown-list">
                              {uniqueRefs
                                .filter(r => !menuSearch.trim() || r.toLocaleLowerCase('tr-TR').includes(menuSearch.trim().toLocaleLowerCase('tr-TR')))
                                .map(ref => {
                                  const checked = selectedRefs === null || selectedRefs.has(ref);
                                  return (
                                    <label key={ref} className="excel-dropdown-item">
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={() => {
                                          setSelectedRefs(prev => {
                                            const base = prev === null ? new Set(uniqueRefs) : new Set(prev);
                                            if (base.has(ref)) base.delete(ref);
                                            else base.add(ref);
                                            return base.size === uniqueRefs.length ? null : base;
                                          });
                                        }}
                                      />
                                      <span>{ref}</span>
                                    </label>
                                  );
                                })}
                            </div>
                          </div>
                        )}
                      </div>
                    </th>
                    <th style={{ width: '115px', textAlign: 'right' }}>
                      <div className="excel-th-wrap" style={{ justifyContent: 'flex-end' }}>
                        <button type="button" className="excel-th-btn" onClick={() => toggleSort('quantity')}>
                          <span>MİKTAR</span>
                          {renderSortIcon('quantity')}
                        </button>
                        <button
                          type="button"
                          className={`excel-filter-trigger ${selectedQtys !== null ? 'is-filtered' : ''}`}
                          onClick={() => {
                            setMenuSearch('');
                            setOpenMenu(m => (m === 'quantity' ? null : 'quantity'));
                          }}
                          title="Excel Miktar Filtresi"
                        >
                          <Filter size={12} />
                        </button>
                        {openMenu === 'quantity' && (
                          <div className="excel-dropdown" style={{ right: 0, left: 'auto' }} onClick={e => e.stopPropagation()}>
                            <div className="excel-dropdown-actions">
                              <button type="button" onClick={() => setSelectedQtys(null)}>Tümünü Seç</button>
                              <button type="button" onClick={() => setSelectedQtys(new Set())}>Temizle</button>
                            </div>
                            <div className="excel-dropdown-list">
                              {uniqueQtys.map(qVal => {
                                const checked = selectedQtys === null || selectedQtys.has(qVal);
                                return (
                                  <label key={qVal} className="excel-dropdown-item">
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      onChange={() => {
                                        setSelectedQtys(prev => {
                                          const base = prev === null ? new Set(uniqueQtys) : new Set(prev);
                                          if (base.has(qVal)) base.delete(qVal);
                                          else base.add(qVal);
                                          return base.size === uniqueQtys.length ? null : base;
                                        });
                                      }}
                                    />
                                    <span>{qVal} Adet</span>
                                  </label>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    </th>
                    <th style={{ width: '175px' }}>
                      <div className="excel-th-wrap">
                        <button type="button" className="excel-th-btn" onClick={() => toggleSort('fifo_date')}>
                          <span>FIFO TARİHİ</span>
                          {renderSortIcon('fifo_date')}
                        </button>
                        <button
                          type="button"
                          className={`excel-filter-trigger ${selectedDates !== null ? 'is-filtered' : ''}`}
                          onClick={() => {
                            setMenuSearch('');
                            setOpenMenu(m => (m === 'fifo_date' ? null : 'fifo_date'));
                          }}
                          title="Excel Tarih Filtresi"
                        >
                          <Filter size={12} />
                        </button>
                        {openMenu === 'fifo_date' && (
                          <div className="excel-dropdown" onClick={e => e.stopPropagation()}>
                            <div className="excel-dropdown-search">
                              <Search size={12} />
                              <input
                                type="text"
                                value={menuSearch}
                                onChange={e => setMenuSearch(e.target.value)}
                                placeholder="Tarih ara (GG.AA.YYYY)..."
                                autoFocus
                              />
                            </div>
                            <div className="excel-dropdown-actions">
                              <button
                                type="button"
                                onClick={() => {
                                  const q = menuSearch.trim();
                                  if (!q) {
                                    setSelectedDates(null);
                                  } else {
                                    const matching = uniqueDates.filter(d => d.includes(q));
                                    setSelectedDates(new Set(matching));
                                  }
                                }}
                              >
                                {menuSearch.trim() ? 'Arananları Seç' : 'Tümünü Seç'}
                              </button>
                              <button type="button" onClick={() => setSelectedDates(new Set())}>Temizle</button>
                            </div>
                            <div className="excel-dropdown-list">
                              {uniqueDates
                                .filter(d => !menuSearch.trim() || d.includes(menuSearch.trim()))
                                .map(dtStr => {
                                  const checked = selectedDates === null || selectedDates.has(dtStr);
                                  return (
                                    <label key={dtStr} className="excel-dropdown-item">
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={() => {
                                          setSelectedDates(prev => {
                                            const base = prev === null ? new Set(uniqueDates) : new Set(prev);
                                            if (base.has(dtStr)) base.delete(dtStr);
                                            else base.add(dtStr);
                                            return base.size === uniqueDates.length ? null : base;
                                          });
                                        }}
                                      />
                                      <span>{dtStr}</span>
                                    </label>
                                  );
                                })}
                            </div>
                          </div>
                        )}
                      </div>
                    </th>
                    <th style={{ width: '115px', textAlign: 'center' }}>
                      <button type="button" className="excel-th-btn" style={{ justifyContent: 'center' }} onClick={() => toggleSort('blocked')}>
                        <span>BLOKAJ</span>
                        {renderSortIcon('blocked')}
                      </button>
                    </th>
                    <th style={{ width: '125px', textAlign: 'center' }}>
                      <button type="button" className="excel-th-btn" style={{ justifyContent: 'center' }} onClick={() => toggleSort('status')}>
                        <span>DURUM</span>
                        {renderSortIcon('status')}
                      </button>
                    </th>
                    <th style={{ width: '135px', textAlign: 'right' }}>İŞLEM</th>
                  </tr>

                  {/* Excel tarzı sütun altı hızlı filtre satırı */}
                  <tr className="excel-filter-row">
                    <th>
                      <input
                        type="text"
                        className="excel-col-input"
                        value={colLabel}
                        onChange={e => setColLabel(e.target.value)}
                        placeholder={selectedLabels ? `${selectedLabels.size} etiket seçili...` : 'Etiket filtrele...'}
                      />
                    </th>
                    <th>
                      <input
                        type="text"
                        className="excel-col-input"
                        value={colRefText}
                        onChange={e => setColRefText(e.target.value)}
                        placeholder={selectedRefs ? `${selectedRefs.size} referans seçili...` : 'Referans filtrele...'}
                      />
                    </th>
                    <th>
                      <select
                        className="excel-col-select"
                        value={selectedQtys && selectedQtys.size === 1 ? String(Array.from(selectedQtys)[0]) : 'ALL'}
                        onChange={e => {
                          if (e.target.value === 'ALL') setSelectedQtys(null);
                          else setSelectedQtys(new Set([Number(e.target.value)]));
                        }}
                      >
                        <option value="ALL">Tüm Miktarlar</option>
                        {uniqueQtys.map(qVal => (
                          <option key={qVal} value={qVal}>{qVal}</option>
                        ))}
                      </select>
                    </th>
                    <th>
                      <input
                        type="text"
                        className="excel-col-input"
                        value={colDateText}
                        onChange={e => setColDateText(e.target.value)}
                        placeholder={selectedDates ? `${selectedDates.size} gün seçili...` : 'GG.AA.YYYY...'}
                      />
                    </th>
                    <th>
                      <select
                        className="excel-col-select"
                        value={colBlocked}
                        onChange={e => setColBlocked(e.target.value as 'ALL' | 'YANLIŞ' | 'DOĞRU')}
                      >
                        <option value="ALL">Tümü</option>
                        <option value="YANLIŞ">YANLIŞ</option>
                        <option value="DOĞRU">DOĞRU</option>
                      </select>
                    </th>
                    <th>
                      <select
                        className="excel-col-select"
                        value={colStatus}
                        onChange={e => setColStatus(e.target.value as 'ALL' | 'AKTİF' | 'OKUTULDU' | 'GİZLİ')}
                      >
                        <option value="ALL">Tümü</option>
                        <option value="AKTİF">AKTİF</option>
                        <option value="OKUTULDU">OKUTULDU</option>
                        <option value="GİZLİ">GİZLİ</option>
                      </select>
                    </th>
                    <th style={{ textAlign: 'right', fontSize: '0.7rem', color: '#94a3b8' }}>
                      {filteredItems.length} kayıt
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.length === 0 ? (
                    <tr className="stock-empty-row">
                      <td colSpan={7} className="stock-empty-cell">
                        Seçilen filtrelere uygun stok etiketi bulunamadı.
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map(item => (
                      <tr
                        key={item.id}
                        className={item.hidden ? 'stock-row-hidden' : 'pending-item-row'}
                        style={item.hidden ? { opacity: 0.6, background: 'rgba(239, 68, 68, 0.06)' } : undefined}
                      >
                        <td className="font-mono label-text">{item.label}</td>
                        <td className="ref-cell">{item.reference}</td>
                        <td className="qty-cell" style={{ textAlign: 'right' }}>{item.quantity}</td>
                        <td className="font-mono">{item.fifo_date}</td>
                        <td style={{ textAlign: 'center' }}>
                          {item.blocked ? (
                            <span className="sc-blokaj-pill is-blocked" style={{ display: 'inline-flex', gap: '0.2rem' }}>
                              <TriangleAlert size={11} /> DOĞRU
                            </span>
                          ) : (
                            <span className="sc-blokaj-pill is-unblocked">YANLIŞ</span>
                          )}
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          {item.scanned ? (
                            <span className="badge-pill badge-scanned">OKUTULDU</span>
                          ) : item.hidden ? (
                            <span
                              className="badge-pill"
                              style={{ background: 'rgba(239, 68, 68, 0.2)', color: '#fca5a5', border: '1px solid rgba(239, 68, 68, 0.45)' }}
                            >
                              GİZLİ
                            </span>
                          ) : (
                            <span className="badge-pill badge-pending">AKTİF</span>
                          )}
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <button
                            type="button"
                            className={`op-btn compact ${item.hidden ? 'primary' : 'secondary'}`}
                            disabled={busyId === item.id || item.scanned}
                            onClick={() => void handleToggleHidden(item)}
                            title={
                              item.scanned
                                ? 'Okutulmuş etiket gizlenemez (önce okutmayı geri alın)'
                                : item.hidden
                                  ? 'Etiketi tekrar aktif et ve FIFO hesabına dahil et'
                                  : 'Etiketi gizle (FIFO hesabından çıkar)'
                            }
                            style={{ padding: '0.24rem 0.55rem', fontSize: '0.72rem' }}
                          >
                            {item.hidden ? (
                              <>
                                <Eye size={13} /> Aktif Et
                              </>
                            ) : (
                              <>
                                <EyeOff size={13} /> Gizliye Al
                              </>
                            )}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
