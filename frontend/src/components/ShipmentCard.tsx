import { useState, useRef, useEffect } from 'react';
import { ChevronDown, ChevronUp, Pencil, TriangleAlert } from 'lucide-react';
import { api, CandidateLabel, ShipmentGroup, ShipmentManifest, ShipmentProgress, ShipmentManifestItem } from '../api';

interface ShipmentCardProps {
  group: ShipmentGroup;
  index: number;
  isSelected?: boolean;
  onSelect?: () => void;
  onUndoScan: (shipmentId: number, label: string) => Promise<void>;
  onRenameGroup: (groupId: number, name: string) => void;
  onRemove: (groupId: number) => void;
}

export default function ShipmentCard({
  group: g,
  index,
  isSelected,
  onSelect,
  onUndoScan,
  onRenameGroup,
  onRemove,
}: ShipmentCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [expandedRefs, setExpandedRefs] = useState<Record<number, boolean>>({});
  const [manifestMap, setManifestMap] = useState<Record<number, ShipmentManifestItem[]>>({});
  const [loadingManifest, setLoadingManifest] = useState<Record<number, boolean>>({});
  const [openDate, setOpenDate] = useState<Record<number, string | null>>({});
  const [candidateMap, setCandidateMap] = useState<Record<string, CandidateLabel[]>>({});
  const [loadingDate, setLoadingDate] = useState<string | null>(null);

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

  const fetchManifest = () => {
    if (!manifestFlight.current) {
      manifestFlight.current = api.getManifest().finally(() => {
        manifestFlight.current = null;
      });
    }
    return manifestFlight.current;
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
      const all = await fetchManifest();
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
    const ids = Object.entries(expandedRefsRef.current)
      .filter(([, open]) => open)
      .map(([id]) => Number(id));
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
    <article className={`shipment-card-v2 ${isDone ? 'sc-done' : 'sc-active'} ${isSelected ? 'sc-selected' : ''} ${livePulse ? 'sc-pulse' : ''}`}>
      <div className="sc-line" onClick={() => setExpanded(v => !v)}>
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
        <span className="sc-line-track" aria-hidden>
          <span className={`sc-progress-fill ${isDone ? 'fill-done' : 'fill-active'}`} style={{ width: `${progress}%` }} />
        </span>
        <span className="sc-line-qty">{g.scanned_quantity}/{g.requested_quantity}</span>
        <span className={`sc-status-pill ${isDone ? 'pill-done' : 'pill-active'}`}>{isDone ? 'Tamam' : 'Açık'}</span>
        <span className="sc-line-actions" onClick={e => e.stopPropagation()}>
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
        <span className="sc-chevron">{expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</span>
      </div>

      {expanded && (
        <div className="sc-nest">
          {g.items.map((item: ShipmentProgress) => {
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

            return (
              <div key={item.shipment_id} className={`sc-ref-frame${isItemExpanded ? ' is-open' : ''}${fullyShort ? ' is-stockout' : ''}${shortText && !fullyShort ? ' is-short' : ''}`}>
                <button
                  type="button"
                  className={`sc-nest-ref${fullyShort ? ' is-stockout' : ''}`}
                  onClick={() => { if (!fullyShort) toggleRefItem(item.shipment_id); }}
                >
                  <span className="sc-ref-main">
                    <span className="sc-ref-code">
                      {shortText && <TriangleAlert size={12} aria-hidden />}
                      {item.reference}
                    </span>
                    {shortText && <span className="sc-ref-note">{shortText}</span>}
                  </span>
                  <span className="sc-line-qty">{item.scanned_quantity}/{item.requested_quantity}</span>
                  <span className={`sc-status-pill ${fullyShort ? 'pill-stockout' : itemDone ? 'pill-done' : 'pill-active'}`}>
                    {fullyShort ? 'Eksik' : itemDone ? 'Tamam' : `%${Math.round(itemPct)}`}
                  </span>
                  <span className="sc-chevron">
                    {!fullyShort && (isItemExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />)}
                  </span>
                </button>

                {isItemExpanded && !fullyShort && (
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
                            <span className="sc-date-label">{m.fifo_group_date}</span>
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
                                <span key={read.label} className={`sc-chip${read.outside_fifo ? ' sc-chip-outside' : ' sc-chip-read'}`}>
                                  {read.outside_fifo && <TriangleAlert size={11} aria-hidden />}
                                  <span>{read.label}</span>
                                  <em>{read.quantity}</em>
                                  <button type="button" onClick={() => handleUndo(item.shipment_id, read.label)}>Geri al</button>
                                </span>
                              ))}
                              {loadingDate === dateKey && candidates.length === 0 ? (
                                <span className="sc-empty">Etiketler yükleniyor</span>
                              ) : candidates.map(label => (
                                <span key={label.label} className="sc-chip sc-chip-open" title={label.fifo_time}>
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
