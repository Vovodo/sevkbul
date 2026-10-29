import { useState, useRef, useEffect } from 'react';
import { ArrowDown, ArrowUp, Check, ChevronDown, ChevronUp, GripVertical, Layers, Lock, Pencil, Search, TriangleAlert } from 'lucide-react';
import { api, CandidateLabel, ShipmentGroup, ShipmentManifest, ShipmentProgress, ShipmentManifestItem } from '../api';

type RefFilterMode = 'all' | 'open' | 'short' | 'blocked' | 'done';

interface ShipmentCardProps {
  group: ShipmentGroup;
  index: number;
  totalGroups?: number;
  isSelected?: boolean;
  onSelect?: () => void;
  onUndoScan: (shipmentId: number, label: string) => Promise<void>;
  onRenameGroup: (groupId: number, name: string) => void;
  onRemove: (groupId: number) => void;
  dragging?: boolean;
  dropTarget?: boolean;
  onDragStart?: (groupId: number) => void;
  onDragOver?: (groupId: number) => void;
  onDrop?: (groupId: number, sourceId?: number) => void;
  onDragEnd?: () => void;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}

export default function ShipmentCard({
  group: g,
  index,
  totalGroups = 1,
  isSelected,
  onSelect,
  onUndoScan,
  onRenameGroup,
  onRemove,
  dragging,
  dropTarget,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onMoveUp,
  onMoveDown,
}: ShipmentCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [expandedRefs, setExpandedRefs] = useState<Record<number, boolean>>({});
  const [manifestMap, setManifestMap] = useState<Record<number, ShipmentManifestItem[]>>({});
  const [loadingManifest, setLoadingManifest] = useState<Record<number, boolean>>({});
  const [openDate, setOpenDate] = useState<Record<number, string | null>>({});
  const [candidateMap, setCandidateMap] = useState<Record<string, CandidateLabel[]>>({});
  const [loadingDate, setLoadingDate] = useState<string | null>(null);
  const [refQuery, setRefQuery] = useState('');
  const [refFilter, setRefFilter] = useState<RefFilterMode>('all');

  const [editing, setEditing] = useState(false);
  const [nameInput, setNameInput] = useState(g.name || '');
  const [savingName, setSavingName] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const prevQty = useRef(g.scanned_quantity);
  const [livePulse, setLivePulse] = useState(false);
  const manifestMapRef = useRef(manifestMap);
  const candidateMapRef = useRef(candidateMap);
  const expandedRefsRef = useRef(expandedRefs);
  const openDateRef = useRef(openDate);
  const manifestFlight = useRef<Promise<ShipmentManifest[]> | null>(null);
  manifestMapRef.current = manifestMap;
  candidateMapRef.current = candidateMap;
  expandedRefsRef.current = expandedRefs;
  openDateRef.current = openDate;

  const isDone = g.is_complete || g.status === 'completed';
  const progress = Math.min(g.progress_percent, 100);
  const displayName = g.name || `${index}. Sevkiyat`;

  // Dışarıdan bakıldığında eksik ve blokaj özet bilgileri
  const totalRefCount = g.items.length;
  const doneRefCount = g.items.filter(it => it.is_complete || it.scanned_quantity >= it.requested_quantity).length;
  const shortRefCount = g.items.filter(it => Number(it.short_quantity || 0) > 0).length;
  const totalShortQty = g.items.reduce((sum, it) => sum + Number(it.short_quantity || 0), 0);
  const blockedRefCount = g.items.filter(it => Number(it.blocked_label_count || 0) > 0).length;
  const totalBlockedLabels = g.items.reduce((sum, it) => sum + Number(it.blocked_label_count || 0), 0);
  const fmtNum = (n: number) => new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2 }).format(n);

  const openWithFilter = (mode: RefFilterMode, e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    setRefFilter(mode);
    setExpanded(true);
  };

  useEffect(() => {
    setNameInput(g.name || '');
  }, [g.name]);

  useEffect(() => {
    if (prevQty.current === g.scanned_quantity) return;
    prevQty.current = g.scanned_quantity;
    setLivePulse(true);
    const timer = window.setTimeout(() => setLivePulse(false), 700);
    return () => window.clearTimeout(timer);
  }, [g.scanned_quantity]);

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

  const applyManifest = async (ids: number[]) => {
    if (!ids.length) return;
    const pending = ids.filter(id => manifestMapRef.current[id] == null);
    if (pending.length) {
      setLoadingManifest(prev => {
        const next = { ...prev };
        pending.forEach(id => { next[id] = true; });
        return next;
      });
    }
    try {
      const all =
        ids.length === 1
          ? await api.getManifest({ shipmentId: ids[0] })
          : await api.getManifest({ groupId: g.group_id });
      setManifestMap(prev => {
        const next = { ...prev };
        ids.forEach(id => {
          next[id] = all.find(m => m.shipment_id === id)?.items || [];
        });
        return next;
      });
    } catch {
      setManifestMap(prev => {
        const next = { ...prev };
        ids.forEach(id => {
          if (next[id] == null) next[id] = [];
        });
        return next;
      });
    } finally {
      if (pending.length) {
        setLoadingManifest(prev => {
          const next = { ...prev };
          pending.forEach(id => { next[id] = false; });
          return next;
        });
      }
    }
  };

  const loadCandidates = async (shipmentId: number, fifoGroup: string, quiet = false) => {
    const key = `${shipmentId}|${fifoGroup}`;
    const known = candidateMapRef.current[key] != null;
    if (!quiet && !known) setLoadingDate(key);
    try {
      const res = await api.getCandidates(shipmentId, fifoGroup);
      setCandidateMap(prev => ({ ...prev, [key]: res.labels }));
    } catch {
      if (!known) setCandidateMap(prev => ({ ...prev, [key]: [] }));
    } finally {
      setLoadingDate(current => (current === key ? null : current));
    }
  };

  useEffect(() => {
    const ids = Object.keys(manifestMapRef.current).map(Number);
    if (ids.length) void applyManifest(ids);
    Object.entries(openDateRef.current).forEach(([sid, date]) => {
      if (date) void loadCandidates(Number(sid), date, true);
    });
  }, [g]);

  const toggleRefItem = (shipmentId: number) => {
    const opening = !expandedRefs[shipmentId];
    setExpandedRefs(prev => ({ ...prev, [shipmentId]: opening }));
    if (opening) void applyManifest([shipmentId]);
  };

  const toggleDate = (shipmentId: number, fifoGroup: string) => {
    const opening = openDate[shipmentId] !== fifoGroup;
    setOpenDate(prev => ({
      ...prev,
      [shipmentId]: opening ? fifoGroup : null,
    }));
    if (opening) {
      const key = `${shipmentId}|${fifoGroup}`;
      void loadCandidates(shipmentId, fifoGroup, candidateMapRef.current[key] != null);
    }
  };

  const handleUndo = async (shipmentId: number, label: string) => {
    await onUndoScan(shipmentId, label);
    await applyManifest([shipmentId]);
    const date = openDate[shipmentId];
    if (date) await loadCandidates(shipmentId, date, true);
  };

  return (
    <article
      className={`shipment-card-v2 ${isDone ? 'sc-done' : 'sc-active'} ${isSelected ? 'sc-selected' : ''} ${shortRefCount > 0 ? 'has-shortage' : ''} ${blockedRefCount > 0 ? 'has-blocked' : ''} ${livePulse ? 'sc-pulse' : ''} ${dragging ? 'is-dragging' : ''} ${dropTarget ? 'is-drop' : ''}`}
      onDragOver={e => {
        if (!onDrop) return;
        e.preventDefault();
        onDragOver?.(g.group_id);
      }}
      onDrop={e => {
        if (!onDrop) return;
        e.preventDefault();
        const raw = e.dataTransfer?.getData('text/plain');
        const parsed = raw ? Number(raw) : undefined;
        onDrop(g.group_id, Number.isFinite(parsed) ? parsed : undefined);
      }}
    >
      <div className="sc-card-outer" onClick={() => setExpanded(v => !v)}>
        <div className="sc-card-top">
          <div className="sc-card-identity">
            <button
              type="button"
              className="sc-drag"
              draggable
              title="Sırayı değiştirmek için sürükle"
              aria-label="Sırayı değiştir"
              onClick={e => e.stopPropagation()}
              onDragStart={e => {
                e.stopPropagation();
                e.dataTransfer.setData('text/plain', String(g.group_id));
                e.dataTransfer.effectAllowed = 'move';
                onDragStart?.(g.group_id);
              }}
              onDragEnd={() => onDragEnd?.()}
            >
              <GripVertical size={14} />
            </button>
            {totalGroups > 1 && (onMoveUp || onMoveDown) && (
              <span className="sc-move-btns" onClick={e => e.stopPropagation()}>
                <button
                  type="button"
                  className="sc-move-btn"
                  onClick={onMoveUp}
                  disabled={index <= 1 || !onMoveUp}
                  title="Yukarı taşı"
                  aria-label="Yukarı taşı"
                >
                  <ArrowUp size={12} />
                </button>
                <button
                  type="button"
                  className="sc-move-btn"
                  onClick={onMoveDown}
                  disabled={index >= totalGroups || !onMoveDown}
                  title="Aşağı taşı"
                  aria-label="Aşağı taşı"
                >
                  <ArrowDown size={12} />
                </button>
              </span>
            )}
            <span className="sc-index">{index}</span>
            <div className="sc-name-wrap" onClick={e => e.stopPropagation()}>
              {editing ? (
                <input
                  ref={nameRef}
                  className="sc-name-input"
                  value={nameInput}
                  onChange={e => setNameInput(e.target.value)}
                  onBlur={saveName}
                  onKeyDown={handleNameKeyDown}
                  placeholder={`${index}. Sevkiyat`}
                  maxLength={80}
                  disabled={savingName}
                />
              ) : (
                <span className="sc-name" onClick={() => setExpanded(v => !v)}>{displayName}</span>
              )}
              <button className="sc-edit-btn" onClick={startEditing} title="İsim Düzenle" type="button">
                <Pencil size={12} />
              </button>
            </div>
          </div>

          <div className="sc-card-right" onClick={e => e.stopPropagation()}>
            <div className="sc-qty-summary" onClick={() => setExpanded(v => !v)}>
              <strong className="sc-qty-numbers">
                {fmtNum(g.scanned_quantity)} <span>/ {fmtNum(g.requested_quantity)}</span>
              </strong>
              <span className={`sc-pct-badge ${isDone ? 'is-done' : ''}`}>%{Math.round(progress)}</span>
            </div>
            <span className="sc-line-actions">
              {onSelect && (
                <button
                  type="button"
                  className={`sc-select-btn ${isSelected ? 'is-selected' : ''}`}
                  onClick={onSelect}
                  title={isSelected ? 'Şu an bu sevkiyat okutuluyor' : 'Okutmak için bu sevkiyatı seç'}
                >
                  {isSelected ? 'Seçili' : 'Seç'}
                </button>
              )}
              <button type="button" className="sc-remove-btn" onClick={() => onRemove(g.group_id)} title="Bu sevkiyatı kaldır">
                Kaldır
              </button>
            </span>
            <span className="sc-chevron" onClick={() => setExpanded(v => !v)}>
              {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
            </span>
          </div>
        </div>

        <div className="sc-card-bottom">
          <div className="sc-summary-chips">
            <button
              type="button"
              className="sc-meta-chip is-refs"
              onClick={e => openWithFilter('all', e)}
              title="Referans listesini aç"
            >
              <Layers size={11} />
              <span>
                {totalRefCount === 1
                  ? g.items[0]?.reference || '1 Referans'
                  : `${totalRefCount} Referans (${doneRefCount}/${totalRefCount} Tamam)`}
              </span>
            </button>

            {shortRefCount > 0 ? (
              <button
                type="button"
                className="sc-meta-chip is-shortage"
                onClick={e => openWithFilter('short', e)}
                title="Eksik stoğu olan referansları göster"
              >
                <TriangleAlert size={11} />
                <span>
                  {totalRefCount === 1
                    ? `${fmtNum(totalShortQty)} Adet Eksik`
                    : `${shortRefCount} Ref Eksik (${fmtNum(totalShortQty)} adet)`}
                </span>
              </button>
            ) : (
              <span className="sc-meta-chip is-ok" title="Tüm referanslar için stok yeterli">
                <Check size={11} />
                <span>Stok Tam</span>
              </span>
            )}

            {totalBlockedLabels > 0 && (
              <button
                type="button"
                className="sc-meta-chip is-blocked"
                onClick={e => openWithFilter('blocked', e)}
                title="Blokajlı etiketi olan referansları göster"
              >
                <Lock size={11} />
                <span>
                  {totalRefCount === 1
                    ? `${totalBlockedLabels} Blokajlı Etiket`
                    : `${blockedRefCount} Ref • ${totalBlockedLabels} Blokajlı`}
                </span>
              </button>
            )}
          </div>

          <span className="sc-line-track" aria-hidden>
            <span
              className={`sc-progress-fill ${isDone ? 'fill-done' : shortRefCount > 0 ? 'fill-short' : 'fill-active'}`}
              style={{ width: `${progress}%` }}
            />
          </span>
        </div>
      </div>

      {expanded && (
        <div className="sc-nest">
          {g.items.length > 1 && (() => {
            const totalCnt = g.items.length;
            const doneCnt = g.items.filter(it => it.is_complete || it.scanned_quantity >= it.requested_quantity).length;
            const shortCnt = g.items.filter(it => Number(it.short_quantity || 0) > 0).length;
            const blockedRefCnt = g.items.filter(it => Number(it.blocked_label_count || 0) > 0).length;
            const openCnt = g.items.filter(it => !(it.is_complete || it.scanned_quantity >= it.requested_quantity)).length;
            return (
              <div className="sc-filter-bar" onClick={e => e.stopPropagation()}>
                <div className="sc-search-wrap">
                  <Search size={12} aria-hidden />
                  <input
                    type="text"
                    className="sc-search-input"
                    value={refQuery}
                    onChange={e => setRefQuery(e.target.value)}
                    placeholder="Referans ara..."
                  />
                </div>
                <div className="sc-filter-pills">
                  <button
                    type="button"
                    className={`sc-filter-pill ${refFilter === 'all' ? 'active' : ''}`}
                    onClick={() => setRefFilter('all')}
                  >
                    Tümü ({totalCnt})
                  </button>
                  <button
                    type="button"
                    className={`sc-filter-pill ${refFilter === 'open' ? 'active' : ''}`}
                    onClick={() => setRefFilter('open')}
                  >
                    Açık ({openCnt})
                  </button>
                  {shortCnt > 0 && (
                    <button
                      type="button"
                      className={`sc-filter-pill is-short ${refFilter === 'short' ? 'active' : ''}`}
                      onClick={() => setRefFilter('short')}
                    >
                      Eksik ({shortCnt})
                    </button>
                  )}
                  {blockedRefCnt > 0 && (
                    <button
                      type="button"
                      className={`sc-filter-pill is-blocked ${refFilter === 'blocked' ? 'active' : ''}`}
                      onClick={() => setRefFilter('blocked')}
                    >
                      Blokajlı ({blockedRefCnt})
                    </button>
                  )}
                  <button
                    type="button"
                    className={`sc-filter-pill ${refFilter === 'done' ? 'active' : ''}`}
                    onClick={() => setRefFilter('done')}
                  >
                    Tamam ({doneCnt})
                  </button>
                </div>
              </div>
            );
          })()}

          {g.items.filter((item: ShipmentProgress) => {
            const q = refQuery.trim().toLocaleLowerCase('tr-TR');
            if (q && !item.reference.toLocaleLowerCase('tr-TR').includes(q)) return false;
            const itemDone = item.is_complete || item.scanned_quantity >= item.requested_quantity;
            const short = Number(item.short_quantity || 0);
            const blockedCnt = Number(item.blocked_label_count || 0);
            if (refFilter === 'open') return !itemDone;
            if (refFilter === 'short') return short > 0;
            if (refFilter === 'blocked') return blockedCnt > 0;
            if (refFilter === 'done') return itemDone;
            return true;
          }).map((item: ShipmentProgress) => {
            const itemDone = item.is_complete || item.scanned_quantity >= item.requested_quantity;
            const itemPct = item.requested_quantity > 0 ? (item.scanned_quantity / item.requested_quantity) * 100 : 0;
            const isItemExpanded = !!expandedRefs[item.shipment_id];
            const manifestList = manifestMap[item.shipment_id] || [];
            const activeDate = openDate[item.shipment_id];

            const short = Number(item.short_quantity || 0);
            const fullyShort = short > 0 && short + 0.001 >= item.requested_quantity;
            const shortText = fullyShort
              ? 'Eksik'
              : short > 0
                ? `${new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2 }).format(short)} eksik`
                : '';
            const blockedCnt = Number(item.blocked_label_count || 0);
            const unblockedCnt = Number(item.unblocked_label_count || 0);
            const canExpand = !fullyShort || blockedCnt > 0;

            return (
              <div key={item.shipment_id} className={`sc-ref-frame${isItemExpanded ? ' is-open' : ''}${fullyShort ? ' is-stockout' : ''}${shortText && !fullyShort ? ' is-short' : ''}`}>
                <button
                  type="button"
                  className={`sc-nest-ref${fullyShort && !canExpand ? ' is-stockout' : ''}`}
                  onClick={() => { if (canExpand) toggleRefItem(item.shipment_id); }}
                >
                  <span className="sc-ref-main">
                    <span className="sc-ref-code">
                      {shortText && <TriangleAlert size={12} aria-hidden />}
                      {item.reference}
                    </span>
                    <span className="sc-ref-subrow">
                      {shortText && <span className="sc-ref-note">{shortText}</span>}
                      <span className="sc-blokaj-badges">
                        <span className="sc-blokaj-pill is-unblocked" title="Stoktaki blokajsız (YANLIŞ) etiket sayısı">
                          Blokajsız: {unblockedCnt}
                        </span>
                        <span className={`sc-blokaj-pill ${blockedCnt > 0 ? 'is-blocked' : 'is-zero'}`} title="Stoktaki blokajlı (DOĞRU) etiket sayısı">
                          Blokajlı: {blockedCnt}
                        </span>
                      </span>
                    </span>
                  </span>
                  <span className="sc-line-qty">{item.scanned_quantity}/{item.requested_quantity}</span>
                  <span className={`sc-status-pill ${fullyShort ? 'pill-stockout' : itemDone ? 'pill-done' : 'pill-active'}`}>
                    {fullyShort ? 'Eksik' : itemDone ? 'Tamam' : `%${Math.round(itemPct)}`}
                  </span>
                  <span className="sc-chevron">
                    {canExpand && (isItemExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />)}
                  </span>
                </button>

                {isItemExpanded && canExpand && (
                  <div className="sc-nest-dates">
                    {loadingManifest[item.shipment_id] && manifestList.length === 0 ? (
                      <div className="sc-empty">Tarihler yükleniyor</div>
                    ) : manifestList.length === 0 ? (
                      <div className="sc-empty">FIFO tarihi yok</div>
                    ) : manifestList.map(m => {
                      const scannedQty = m.scanned_quantity ?? 0;
                      const filled = m.is_scanned || scannedQty >= m.quantity;
                      const started = scannedQty > 0 && !filled;
                      const state = filled ? 'filled' : started ? 'partial' : 'open';
                      const stateLabel = m.outside_fifo ? 'FIFO dışı' : filled ? 'Doldu' : started ? 'Devam' : 'Açık';
                      const dateOpen = activeDate === m.fifo_group_date;
                      const dateKey = `${item.shipment_id}|${m.fifo_group_date}`;
                      const reads = m.scanned_labels || [];
                      const candidates = candidateMap[dateKey] || [];
                      const pct = m.quantity > 0 ? Math.min(100, (scannedQty / m.quantity) * 100) : 0;

                      return (
                        <div key={m.fifo_group_date} className={m.outside_fifo ? 'is-outside' : ''}>
                          <button
                            type="button"
                            className={`sc-nest-date${dateOpen ? ' is-open' : ''}`}
                            onClick={() => toggleDate(item.shipment_id, m.fifo_group_date)}
                          >
                            <span className="sc-date-label">
                              <span>{m.fifo_group_date}</span>
                              {m.has_blocked && (
                                <span
                                  className="sc-date-blocked-warn"
                                  title={`Bu FIFO tarihinde ${m.blocked_count || 1} adet blokajlı etiket var`}
                                >
                                  <TriangleAlert size={13} aria-label="Blokajlı etiket içerir" />
                                </span>
                              )}
                            </span>
                            <span className="sc-mini-track" aria-hidden>
                              <span className={`sc-date-fill${m.outside_fifo ? ' is-outside' : ''}`} style={{ width: `${pct}%` }} />
                            </span>
                            <span className="sc-line-qty">{scannedQty}/{m.quantity}</span>
                            <span className={`sc-date-state state-${m.outside_fifo ? 'outside' : state}`}>
                              {m.outside_fifo && <TriangleAlert size={11} aria-hidden />}
                              {stateLabel}
                            </span>
                            <span className="sc-chevron">{dateOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</span>
                          </button>

                          {dateOpen && (
                            <div className="sc-nest-labels">
                              {m.outside_fifo && (
                                <span className="sc-date-flag">Bu tarihin önüne yeni FIFO geçti. Okutma duruyor.</span>
                              )}
                              {reads.map(read => (
                                <span key={read.label} className={`sc-chip${read.outside_fifo ? ' sc-chip-outside' : read.blocked ? ' sc-chip-blocked' : ' sc-chip-read'}`}>
                                  {read.outside_fifo && <TriangleAlert size={11} aria-hidden />}
                                  <span>{read.label}</span>
                                  <em>{read.quantity}</em>
                                  <button type="button" onClick={() => handleUndo(item.shipment_id, read.label)}>Geri al</button>
                                </span>
                              ))}
                              {loadingDate === dateKey && candidates.length === 0 ? (
                                <span className="sc-empty">Etiketler yükleniyor</span>
                              ) : candidates.map(label => (
                                <span
                                  key={label.label}
                                  className={`sc-chip ${label.blocked ? 'sc-chip-blocked' : 'sc-chip-open'}`}
                                  title={label.blocked ? `Blokajlı • ${label.fifo_time}` : label.fifo_time}
                                >
                                  <span>{label.label}</span>
                                  <em>{label.quantity}</em>
                                </span>
                              ))}
                              {loadingDate !== dateKey && reads.length === 0 && candidates.length === 0 && (
                                <span className="sc-empty">Bu tarihte okutulacak etiket yok</span>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </article>
  );
}
