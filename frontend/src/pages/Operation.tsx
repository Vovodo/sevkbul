import { useState, useRef, useEffect, useCallback } from 'react';
import { Check, ClipboardList, Copy, Crosshair, Layers, Lock, LockOpen, Maximize2, PackageSearch, Radio, RefreshCw, RotateCcw, SlidersHorizontal, Smartphone, TriangleAlert, X } from 'lucide-react';
import { api, ShipmentGroup, ShipmentProgress, ScanResponse, ShipmentTarget, RecentScan, RecalculateStatus } from '../api';
import { playScanSound, initAudio, ScanResultType } from '../audio';
import SoundSettings from '../components/SoundSettings';
import ManifestModal from '../components/ManifestModal';
import StockModal from '../components/StockModal';
import MobileDownloadModal from '../components/MobileDownloadModal';
import ShipmentCard from '../components/ShipmentCard';
import Logo from '../components/Logo';
import { ScanMark, ScanNotice } from '../components/ScanNotice';
import { useLiveUpdates, WsMessage } from '../useLiveUpdates';


type Phase = 'setup' | 'scanning';

export default function OperationPage() {
  const [phase, setPhase] = useState<Phase>('setup');
  const [showSetup, setShowSetup] = useState(true);
  const [showManifestModal, setShowManifestModal] = useState(false);
  const [showStockModal, setShowStockModal] = useState(false);
  const [showDownloadModal, setShowDownloadModal] = useState(false);
  const [stockLoaded, setStockLoaded] = useState(false);
  const [stockCount, setStockCount] = useState(0);
  const [targets, setTargets] = useState<ShipmentTarget[]>([]);
  const [groups, setGroups] = useState<ShipmentGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [manualRef, setManualRef] = useState('');
  const [manualQty, setManualQty] = useState('');
  const [scanValue, setScanValue] = useState('');
  const [lastScan, setLastScan] = useState<ScanResponse | null>(null);
  const [noticeKey, setNoticeKey] = useState(0);
  const [noticeLeaving, setNoticeLeaving] = useState(false);
  const [recentScans, setRecentScans] = useState<RecentScan[]>([]);
  const [loading, setLoading] = useState('');
  const [recalc, setRecalc] = useState<RecalculateStatus | null>(null);
  const [removeAsk, setRemoveAsk] = useState<
    { kind: 'remove'; groupId: number; label: string } | { kind: 'reset' } | null
  >(null);
  const [removeText, setRemoveText] = useState('');
  const [error, setError] = useState('');
  const [dropNote, setDropNote] = useState('');
  const [dragGroupId, setDragGroupId] = useState<number | null>(null);
  const [dropGroupId, setDropGroupId] = useState<number | null>(null);
  const [fileDrag, setFileDrag] = useState(false);
  const [hourlyFifo, setHourlyFifo] = useState<boolean>(() => {
    return localStorage.getItem('hourlyFifo') === 'true';
  });
  const [blockedOnly, setBlockedOnly] = useState<boolean>(false);
  const [copiedShortage, setCopiedShortage] = useState<boolean>(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const lastPresented = useRef<{ key: string; at: number } | null>(null);
  const liveRef = useRef(false);
  const recalcPoll = useRef<ReturnType<typeof setInterval> | null>(null);
  const recalcJob = useRef<number | null>(null);
  const recalcHide = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Aktif seçili sevkiyat grubunu otomatik belirle
  useEffect(() => {
    if (groups.length > 0) {
      if (selectedGroupId == null || !groups.some(g => g.group_id === selectedGroupId)) {
        const firstIncomplete = groups.find(g => !g.is_complete && g.scanned_quantity < g.requested_quantity) || groups[0];
        setSelectedGroupId(firstIncomplete.group_id);
      }
    } else {
      setSelectedGroupId(null);
    }
  }, [groups, selectedGroupId]);

  const handleSelectGroup = useCallback((gid: number) => {
    setSelectedGroupId(gid);
    api.selectActiveGroup(gid).catch(() => {});
  }, []);

  const isScanning = phase === 'scanning' && groups.length > 0;

  const focusScanInput = useCallback(() => {
    if (!isScanning || showSetup) return;
    setTimeout(() => inputRef.current?.focus({ preventScroll: true }), 30);
  }, [isScanning, showSetup]);

  const lockLandscape = useCallback(async () => {
    try {
      const orientation = screen.orientation as ScreenOrientation & {
        lock?: (type: 'landscape' | 'landscape-primary' | 'landscape-secondary') => Promise<void>;
      };
      if (orientation?.lock) {
        await orientation.lock('landscape');
      }
    } catch {
      // iOS / bazı tarayıcılarda desteklenmeyebilir
    }
  }, []);

  const unlockOrientation = useCallback(() => {
    try {
      screen.orientation?.unlock();
    } catch {
      // ignore
    }
  }, []);

  const exitFullscreen = useCallback(() => {
    setIsFullscreen(false);
    unlockOrientation();
    if (document.fullscreenElement && document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    }
  }, [unlockOrientation]);

  const enterFullscreen = useCallback(async () => {
    setIsFullscreen(true);
    try {
      if (document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen();
      }
      await lockLandscape();
    } catch {
      // Tam ekran / yön kilidi desteklenmese de overlay çalışır
    }
    focusScanInput();
  }, [lockLandscape, focusScanInput]);

  useEffect(() => {
    const onFullscreenChange = () => {
      if (!document.fullscreenElement) {
        setIsFullscreen(false);
        unlockOrientation();
      }
    };
    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, [unlockOrientation]);

  useEffect(() => {
    if (isFullscreen) {
      document.body.classList.add('fs-active');
      focusScanInput();
    } else {
      document.body.classList.remove('fs-active');
      focusScanInput();
    }
    return () => document.body.classList.remove('fs-active');
  }, [isFullscreen, focusScanInput]);

  useEffect(() => {
    initAudio();
    api.healthCheck()
      .then(h => {
        if (!h.features?.includes('shipment_targets')) {
          setError('Backend sürümü güncel değil.');
        } else if (!h.features?.includes('shipment_reset')) {
          setError('Sıfırlama servisi için backend güncellemesi gerekiyor.');
        }
      })
      .catch(() => setError('Backend bağlantısı kurulamadı.'));
    api.getInventoryStats().then(s => {
      setStockLoaded(s.total_labels > 0);
      setStockCount(s.total_labels);
    }).catch(() => {});
    api.getTargets().then(setTargets).catch(() => {});
    api.getGroups().then(g => {
      if (g.length > 0) {
        setGroups(g);
        setPhase('scanning');
        setShowSetup(false);
      }
    }).catch(() => {});
    api.getActiveGroup().then(res => {
      if (res.selected_group_id != null) {
        setSelectedGroupId(res.selected_group_id);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => () => {
    if (recalcPoll.current) window.clearInterval(recalcPoll.current);
  }, []);

  useEffect(() => { focusScanInput(); }, [isScanning, focusScanInput]);

  useEffect(() => {
    if (!lastScan || !noticeKey) {
      setNoticeLeaving(false);
      return;
    }
    setNoticeLeaving(false);
    const fade = window.setTimeout(() => setNoticeLeaving(true), 3000);
    const clear = window.setTimeout(() => setLastScan(null), 3280);
    return () => {
      window.clearTimeout(fade);
      window.clearTimeout(clear);
    };
  }, [noticeKey, lastScan]);

  const presentScan = useCallback((scan: ScanResponse) => {
    const key = `${scan.label}|${scan.result}`;
    const now = Date.now();
    const prev = lastPresented.current;
    if (prev && prev.key === key && now - prev.at < 700) return;
    lastPresented.current = { key, at: now };
    setNoticeKey(now);
    setLastScan(scan);
    try {
      if (scan.is_complete && scan.success) {
        playScanSound(scan.result as ScanResultType);
        setTimeout(() => playScanSound('COMPLETE'), 280);
      } else {
        playScanSound(scan.result as ScanResultType);
      }
    } catch {
      // audio context user interaction needed
    }
    setRecentScans(list => [{
      label: scan.label,
      reference: scan.reference,
      quantity: scan.quantity,
      result: scan.result,
      time: new Date().toLocaleTimeString('tr-TR'),
    }, ...list].slice(0, 30));
  }, []);

  const hideRecalc = useCallback((job?: number) => {
    if (recalcHide.current) window.clearTimeout(recalcHide.current);
    recalcHide.current = window.setTimeout(() => {
      if (job != null && recalcJob.current != null && recalcJob.current !== job) return;
      recalcJob.current = null;
      setRecalc(current => (current && current.phase === 'running' ? current : null));
    }, 900);
  }, []);

  // ─── Gerçek Zamanlı Canlı Güncelleme (WebSocket) ───
  const handleWsMessage = useCallback((msg: WsMessage) => {
    const d = msg.data;

    if (d?.selected_group_id !== undefined) {
      setSelectedGroupId(d.selected_group_id);
    }

    if (msg.event === 'recalculate_progress') {
      const status = d as RecalculateStatus;
      if (status?.phase === 'done') {
        api.getGroups().then(setGroups).catch(() => {});
      }
      if (status?.phase === 'error' && status.error) {
        setError(status.error);
      }
      if (recalcJob.current == null || status?.job !== recalcJob.current) return;
      setRecalc(status);
      if (status.phase === 'done' || status.phase === 'error') hideRecalc(status.job);
      return;
    }

    if (msg.event === 'stock_import') {
      // Başka bir kullanıcı stok yükledi
      if (d?.total_labels != null) {
        setStockLoaded(d.total_labels > 0);
        setStockCount(d.total_labels);
      }
      return;
    }

    if (msg.event === 'reset') {
      // Başka bir kullanıcı sevkiyatı sıfırladı
      setGroups([]);
      setSelectedGroupId(null);
      setPhase('setup');
      setShowSetup(true);
      setRecentScans([]);
      setLastScan(null);
      if (d?.targets) {
        setTargets(d.targets);
      }
      return;
    }

    // Tüm diğer olaylarda (scan, undo, find, target_add, target_import, target_clear)
    // Backend her zaman güncel groups ve targets listesini gönderir
    if (d?.groups) {
      setGroups(d.groups);
      if (d.groups.length === 0) {
        setPhase('setup');
        setSelectedGroupId(null);
      } else if (phase === 'setup') {
        setPhase('scanning');
        setShowSetup(false);
      }
    }

    if (d?.targets) {
      setTargets(d.targets);
    }

    if (msg.event === 'scan' && d?.scan) {
      presentScan(d.scan as ScanResponse);
    }
  }, [phase, presentScan, hideRecalc]);

  const live = useLiveUpdates(handleWsMessage);
  liveRef.current = live;

  const handleStockUpload = async (file: File, replace: boolean = true) => {
    setLoading(replace ? 'stock' : 'stock-append');
    setError('');
    setDropNote('');
    try {
      const r = await api.importStock(file, replace);
      setStockLoaded(true);
      setStockCount(r.successful);
      if (!replace && groups.length > 0) {
        setDropNote(`Stok güncellendi (${r.successful.toLocaleString('tr-TR')} etiket). Sevkiyatlar yeni stokla yeniden hesaplanıyor...`);
        await triggerRecalculateQuiet();
      } else if (!replace) {
        setDropNote(`Stok güncellendi (${r.successful.toLocaleString('tr-TR')} etiket).`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Stok yüklenemedi');
    } finally {
      setLoading('');
    }
  };

  const handleShipmentExcel = async (file: File) => {
    setLoading('shipment');
    setError('');
    setDropNote('');
    try {
      const r = await api.importTargetsExcel(file);
      setTargets(r.targets);
      if (r.successful > 0) {
        setDropNote(`${r.successful} hedef hazır. Sevkiyatı oluşturmak için alttaki butonu kullan.`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sevkiyat Exceli yüklenemedi');
    } finally {
      setLoading('');
    }
  };

  const handleShipmentExcelRef = useRef(handleShipmentExcel);
  handleShipmentExcelRef.current = handleShipmentExcel;

  useEffect(() => {
    let depth = 0;
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types || []).includes('Files');
    const onEnter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth += 1;
      setFileDrag(true);
    };
    const onOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    };
    const onLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setFileDrag(false);
    };
    const onDrop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      setFileDrag(false);
      setShowSetup(true);
      const file = Array.from(e.dataTransfer?.files || []).find(item => /\.xlsx?$/i.test(item.name));
      if (!file) {
        setDropNote('');
        setError('Bu dosya sevkiyat formatına uygun değil. Excel dosyası bırak (.xlsx).');
        return;
      }
      void handleShipmentExcelRef.current(file);
    };
    window.addEventListener('dragenter', onEnter);
    window.addEventListener('dragover', onOver);
    window.addEventListener('dragleave', onLeave);
    window.addEventListener('drop', onDrop);
    return () => {
      window.removeEventListener('dragenter', onEnter);
      window.removeEventListener('dragover', onOver);
      window.removeEventListener('dragleave', onLeave);
      window.removeEventListener('drop', onDrop);
    };
  }, []);

  const handleAddTarget = async () => {
    if (!manualRef.trim() || !manualQty || loading === 'add') return;
    setLoading('add');
    setError('');
    try {
      const t = await api.addTarget(manualRef.trim(), parseFloat(manualQty));
      setTargets(prev => (prev.some(item => item.id === t.id) ? prev : [...prev, t]));
      setManualRef('');
      setManualQty('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Hedef eklenemedi');
    } finally {
      setLoading('');
    }
  };

  const handleRemoveTarget = async (id: number) => {
    setError('');
    try {
      await api.deleteTarget(id);
      setTargets(prev => prev.filter(item => item.id !== id));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Hedef silinemedi');
    }
  };

  const handleDiscardTargets = async () => {
    if (targets.length === 0) {
      if (groups.length > 0) setShowSetup(false);
      return;
    }
    if (!window.confirm('Yüklenen sevkiyat hedefleri silinecek. Sevkiyat yayınlanmayacak. Emin misiniz?')) return;
    setLoading('clear');
    setError('');
    try {
      await api.clearTargets();
      setTargets([]);
      setManualRef('');
      setManualQty('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Hedefler temizlenemedi');
    } finally {
      setLoading('');
    }
  };

  const triggerRecalculateQuiet = async () => {
    if (recalc?.phase === 'running') return;
    setError('');
    recalcJob.current = null;
    setRecalc({
      phase: 'running',
      percent: 0,
      done: 0,
      total: 0,
      message: 'Hazırlanıyor',
      error: null,
      updated: 0,
    });
    if (recalcPoll.current) window.clearInterval(recalcPoll.current);
    if (recalcHide.current) window.clearTimeout(recalcHide.current);
    const stopPoll = () => {
      if (recalcPoll.current) {
        window.clearInterval(recalcPoll.current);
        recalcPoll.current = null;
      }
    };
    const finish = (status: RecalculateStatus) => {
      stopPoll();
      if (status.job != null) recalcJob.current = status.job;
      setRecalc(status);
      if (status.phase === 'error') {
        setError(status.error || 'Hesaplama yenilenemedi');
      } else if (status.phase === 'done') {
        api.getGroups().then(setGroups).catch(() => {});
      }
      hideRecalc(status.job);
    };
    try {
      await api.recalculate();
      const first = await api.recalculateStatus();
      if (first.phase === 'idle' || first.job == null) {
        stopPoll();
        recalcJob.current = null;
        setRecalc(null);
        return;
      }
      recalcJob.current = first.job;
      setRecalc(first);
      if (first.phase === 'done' || first.phase === 'error') {
        finish(first);
        return;
      }
      recalcPoll.current = window.setInterval(async () => {
        try {
          const status = await api.recalculateStatus();
          if (recalcJob.current == null || status.job !== recalcJob.current) return;
          if (status.phase === 'idle') {
            stopPoll();
            recalcJob.current = null;
            setRecalc(null);
            return;
          }
          setRecalc(status);
          if (status.phase === 'done' || status.phase === 'error') finish(status);
        } catch {
          // Sunucu meşgulken bir tur atlanır, çubuk ekranda kalır.
        }
      }, 400);
    } catch (e: unknown) {
      finish({
        phase: 'error',
        percent: 0,
        done: 0,
        total: 0,
        message: '',
        error: e instanceof Error ? e.message : 'Hesaplama yenilenemedi',
        updated: 0,
      });
    }
  };

  const handleRecalculate = async () => {
    if (groups.length === 0 || recalc?.phase === 'running') return;
    if (!window.confirm('Güncel stok ve mevcut okutmalara göre FIFO tarihleri yeniden hesaplanacak. Okutmalar silinmez.')) return;
    await triggerRecalculateQuiet();
  };

  const handleFind = async () => {
    setLoading('find');
    setError('');
    try {
      const r = await api.findShipments(hourlyFifo);
      const updatedGroups = await api.getGroups();
      setGroups(updatedGroups);
      setTargets([]);
      if (updatedGroups.length > 0) {
        setPhase('scanning');
        setShowSetup(false);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sevkiyat bulunamadı');
    } finally {
      setLoading('');
    }
  };

  const handleReset = () => {
    setRemoveAsk({ kind: 'reset' });
    setRemoveText('');
  };

  const handleUndoScan = async (shipmentId: number, label: string) => {
    if (!window.confirm(`${label} okutmasını kaldırmak istiyor musunuz?`)) return;
    setError('');
    try {
      await api.undoScan(shipmentId, label);
      const updated = await api.getGroups();
      setGroups(updated);
      setRecentScans(prev => prev.filter(s => !(s.label === label && s.result === 'SEVKİYAT ÜRÜNÜ')));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Okutma kaldırılamadı');
    }
  };

  const askRemoveGroup = (groupId: number) => {
    const group = groups.find(g => g.group_id === groupId);
    const index = groups.findIndex(g => g.group_id === groupId);
    setRemoveAsk({ kind: 'remove', groupId, label: group?.name || `${index + 1}. Sevkiyat` });
    setRemoveText('');
  };

  const confirmTyped = removeText.trim().toLocaleLowerCase('tr-TR') === 'evet';

  const confirmRemoveGroup = async () => {
    if (!removeAsk || !confirmTyped || loading === 'remove' || loading === 'reset') return;
    setError('');
    if (removeAsk.kind === 'reset') {
      setLoading('reset');
      try {
        await api.resetShipments();
        setGroups([]);
        setPhase('setup');
        setShowSetup(true);
        setSelectedGroupId(null);
        setRecentScans([]);
        setLastScan(null);
        setRemoveAsk(null);
        setRemoveText('');
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Sıfırlama hatası');
      } finally {
        setLoading('');
      }
      return;
    }
    const groupId = removeAsk.groupId;
    setLoading('remove');
    try {
      await api.deleteShipmentGroup(groupId);
      const updated = await api.getGroups();
      setGroups(updated);
      setRemoveAsk(null);
      setRemoveText('');
      if (updated.length === 0) {
        setPhase('setup');
        setSelectedGroupId(null);
        setRecentScans([]);
        setLastScan(null);
      } else if (selectedGroupId === groupId) {
        setSelectedGroupId(updated[0].group_id);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sevkiyat kaldırılamadı');
    } finally {
      setLoading('');
    }
  };

  const reorderGroups = async (sourceId: number, targetId: number) => {
    if (sourceId === targetId) return;
    const from = groups.findIndex(g => g.group_id === sourceId);
    const to = groups.findIndex(g => g.group_id === targetId);
    if (from < 0 || to < 0) return;
    const next = [...groups];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    const ordered = next.map((g, i) => ({ ...g, index: i + 1 }));
    setGroups(ordered);
    try {
      const saved = await api.reorderGroups(ordered.map(g => g.group_id));
      setGroups(saved);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sıra kaydedilemedi');
      api.getGroups().then(setGroups).catch(() => {});
    }
  };

  const handleRenameGroup = (groupId: number, name: string) => {
    setGroups(prev => prev.map(g =>
      g.group_id === groupId ? { ...g, name: name || `${g.index}. Sevkiyat` } : g
    ));
  };

  const handleScan = useCallback(async (label: string) => {
    const trimmed = label.trim();
    if (!trimmed) return;

    // Barkod okuyucu arka arkaya hızlı okuttuğunda kutu anında temizlensin
    setScanValue('');
    focusScanInput();

    try {
      const result = await api.scan(trimmed, null, selectedGroupId, blockedOnly);
      presentScan(result);
      // WebSocket paketi gelene kadar seçili sevkiyat ilerlemesini 0ms'de anında güncelle
      if (result.success && result.shipment_id != null && result.scanned_quantity != null) {
        setGroups(prev => prev.map(g => {
          if (!g.items.some(it => it.shipment_id === result.shipment_id)) return g;
          const items = g.items.map(it =>
            it.shipment_id === result.shipment_id
              ? {
                  ...it,
                  scanned_quantity: result.scanned_quantity ?? it.scanned_quantity,
                  remaining_quantity: result.remaining_quantity ?? it.remaining_quantity,
                  progress_percent: result.progress_percent ?? it.progress_percent,
                  is_complete: result.is_complete ?? it.is_complete,
                  status: result.is_complete ? 'completed' : it.status,
                }
              : it
          );
          const totReq = items.reduce((s, i) => s + i.requested_quantity, 0);
          const totScan = items.reduce((s, i) => s + i.scanned_quantity, 0);
          const totRem = Math.max(0, totReq - totScan);
          const pct = totReq > 0 ? Math.min(100, Math.round((totScan / totReq) * 1000) / 10) : 0;
          const allDone = items.length > 0 && items.every(i => i.is_complete);
          return {
            ...g,
            items,
            scanned_quantity: totScan,
            remaining_quantity: totRem,
            progress_percent: pct,
            is_complete: allDone,
            status: allDone ? 'completed' : 'active',
          };
        }));
      }
      if (!liveRef.current) {
        const updated = await api.getGroups();
        setGroups(updated);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Okutma hatası');
    } finally {
      focusScanInput();
    }
  }, [focusScanInput, presentScan, selectedGroupId, blockedOnly]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      void handleScan(e.currentTarget.value || scanValue);
    }
  };

  return (
    <div className="op-page">
      <header className="op-header">
        <div className="op-header-brand">
          <Logo size="md" variant="full" />
          <div className="op-header-status">
            {stockLoaded && <span className="op-badge ok">{stockCount.toLocaleString('tr-TR')} etiket yüklü</span>}
            <span className={`op-live ${live ? 'is-on' : 'is-off'}`}>
              <Radio size={13} />
              {live ? 'Canlı' : 'Bağlantı yok'}
            </span>
          </div>
        </div>

        <nav className="op-header-actions" aria-label="Üst araç çubuğu">
          <div className="op-header-group">
            {groups.length > 0 && (
              <button
                type="button"
                className="op-nav-btn is-primary"
                onClick={() => setShowManifestModal(true)}
              >
                <ClipboardList size={14} />
                <span>FIFO Listesi</span>
              </button>
            )}
            {stockLoaded && (
              <button
                type="button"
                className="op-nav-btn"
                onClick={() => setShowStockModal(true)}
              >
                <PackageSearch size={14} />
                <span>Stok Listesi</span>
              </button>
            )}
            {isScanning && (
              <button
                type="button"
                className={`op-nav-btn ${showSetup ? 'is-active' : ''}`}
                onClick={() => setShowSetup(v => !v)}
              >
                <SlidersHorizontal size={14} />
                <span>{showSetup ? 'Formu Gizle' : 'Formu Göster'}</span>
              </button>
            )}
          </div>

          <span className="op-header-divider" aria-hidden />

          <div className="op-header-group">
            <button
              type="button"
              className="op-nav-btn"
              onClick={() => setShowDownloadModal(true)}
            >
              <Smartphone size={14} />
              <span>Mobil / QR</span>
            </button>
            <SoundSettings />
          </div>

          {isScanning && (
            <>
              <span className="op-header-divider" aria-hidden />
              <button
                type="button"
                className="op-nav-btn is-danger"
                onClick={handleReset}
                disabled={loading === 'reset'}
              >
                <RotateCcw size={14} />
                <span>{loading === 'reset' ? 'Sıfırlanıyor...' : 'Sevkiyatı Sıfırla'}</span>
              </button>
            </>
          )}
        </nav>
      </header>

      <ManifestModal isOpen={showManifestModal} onClose={() => setShowManifestModal(false)} />
      <StockModal
        isOpen={showStockModal}
        onClose={() => setShowStockModal(false)}
        onStockChanged={() => {
          api.getGroups().then(setGroups).catch(() => {});
        }}
      />
      <MobileDownloadModal isOpen={showDownloadModal} onClose={() => setShowDownloadModal(false)} />

      {error && <div className="op-alert error">{error}</div>}
      {fileDrag && (
        <div className="op-drop-overlay" role="status">
          <strong>Excel'i bırak</strong>
          <span>Uygunsa hedeflere eklenir. Sevkiyatı sen oluşturursun.</span>
        </div>
      )}

      <div className="op-workspace">
      <div className="op-main">
      {showSetup && (
        <section className="op-section">
          <div className="op-setup-top">
            <span>Kurulum</span>
            <button type="button" className="op-btn secondary compact" onClick={() => setShowSetup(false)}>
              Geri
            </button>
          </div>
          <div className="op-row">
            <div className="op-field">
              <label>STOK EXCELİ</label>
              <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                <label className="op-file-btn" style={{ flex: 1 }}>
                  {loading === 'stock' ? 'Yükleniyor...' : stockLoaded ? <><Check size={15} /> Yüklendi — Sıfırdan Değiştir</> : 'Dosya Seç'}
                  <input type="file" accept=".xlsx,.xls" hidden onChange={e => {
                    const f = e.target.files?.[0];
                    e.target.value = '';
                    if (f) handleStockUpload(f, true);
                  }} />
                </label>
                {stockLoaded && (
                  <label
                    className="op-file-btn"
                    style={{ flex: 1, borderColor: '#3b82f6', color: '#93c5fd', background: 'rgba(59, 130, 246, 0.1)' }}
                    title="Mevcut sevkiyatları ve okutmaları bozmadan yeni stok etiketlerini ekler / günceller"
                  >
                    {loading === 'stock-append' ? 'Ekleniyor...' : '+ Stok Güncelle / Ekle'}
                    <input type="file" accept=".xlsx,.xls" hidden onChange={e => {
                      const f = e.target.files?.[0];
                      e.target.value = '';
                      if (f) handleStockUpload(f, false);
                    }} />
                  </label>
                )}
              </div>
            </div>
            <div className="op-field">
              <label>SEVKİYAT EXCELİ</label>
              <label className="op-file-btn">
                {loading === 'shipment' ? 'Yükleniyor...' : 'Dosya Seç'}
                <input type="file" accept=".xlsx,.xls" hidden onChange={e => {
                  const f = e.target.files?.[0];
                  if (f) handleShipmentExcel(f);
                }} />
              </label>
            </div>
          </div>
          <p className="op-file-hint">Excel'i bu ekrana da sürükleyebilirsin. Başlık gerekmez. Soldaki sütun referans, sağdaki miktar (sayı) olmalı. Dosya adı sevkiyatın adı olur.</p>
          {dropNote && <div className="op-alert ok">{dropNote}</div>}

          <div className="op-divider">Manuel hedef</div>

          <div className="op-row">
            <div className="op-field flex-2">
              <label>REFERANS</label>
              <input value={manualRef} onChange={e => setManualRef(e.target.value)} placeholder="6681378-HZN-1" />
            </div>
            <div className="op-field flex-1">
              <label>MİKTAR</label>
              <input type="number" value={manualQty} onChange={e => setManualQty(e.target.value)} placeholder="240" />
            </div>
            <button className="op-btn secondary" onClick={handleAddTarget} disabled={loading === 'add'}>
              {loading === 'add' ? 'Ekleniyor...' : 'HEDEF EKLE'}
            </button>
          </div>

          {targets.length > 0 && (
            <>
              <div className="op-target-toolbar">
                <span>Tanımlı hedefler ({targets.length})</span>
                <button
                  type="button"
                  className="op-btn danger compact"
                  onClick={handleDiscardTargets}
                  disabled={loading === 'clear'}
                >
                  {loading === 'clear' ? 'Temizleniyor...' : 'Hedefleri temizle'}
                </button>
              </div>
              <div className="op-target-list">
                {targets.map(t => (
                  <div key={t.id} className="op-target-item">
                    <span>{t.reference}</span>
                    <span className="op-target-qty">{t.target_quantity} adet</span>
                    <button
                      type="button"
                      className="op-target-remove"
                      onClick={() => handleRemoveTarget(t.id)}
                      title="Bu hedefi sil"
                      aria-label={`${t.reference} hedefini sil`}
                    >
                      <X size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}

          <div style={{ marginTop: '1rem', marginBottom: '0.75rem', display: 'flex', justifyContent: 'center' }}>
            <button
              type="button"
              className={`op-btn compact ${hourlyFifo ? 'primary' : 'secondary'}`}
              onClick={() => setHourlyFifo(prev => {
                const next = !prev;
                localStorage.setItem('hourlyFifo', String(next));
                return next;
              })}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.5rem 1rem',
                fontSize: '0.85rem',
                fontWeight: 600,
                borderRadius: '8px',
                border: hourlyFifo ? '1px solid #3b82f6' : '1px solid #374151',
                background: hourlyFifo ? 'rgba(59, 130, 246, 0.15)' : 'rgba(31, 41, 55, 0.5)',
                color: hourlyFifo ? '#60a5fa' : '#9ca3af',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
              }}
            >
              <span>Saat filtresi</span>
              <strong>
                {hourlyFifo ? 'Açık — aynı saat' : 'Kapalı — aynı gün'}
              </strong>
            </button>
          </div>

          {groups.length > 0 && (
            <div style={{
              background: 'rgba(59, 130, 246, 0.08)',
              border: '1px solid rgba(59, 130, 246, 0.25)',
              borderRadius: '8px',
              padding: '0.6rem 0.9rem',
              fontSize: '0.8rem',
              color: '#93c5fd',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              marginBottom: '0.5rem',
            }}>
              <span>Yeni sevkiyat, önceki sevkiyatların tarih kotasından devam eder. Hepsini silmek için üstteki sıfırlamayı kullan.</span>
            </div>
          )}

          <button
            className="op-btn primary large"
            onClick={handleFind}
            disabled={loading === 'find' || !stockLoaded || targets.length === 0}
          >
            {loading === 'find' ? 'Hesaplanıyor...' : groups.length > 0 ? 'Yeni sevkiyat ekle' : 'Sevkiyatı yayınla'}
          </button>
        </section>
      )}

      {!showSetup && groups.length === 0 && (
        <section className="op-section op-empty-setup">
          <h2>Aktif sevkiyat yok</h2>
          <p>
            {targets.length > 0
              ? `${targets.length} hedef kayıtlı. Kuruluma dönüp sevkiyatı yayınlayabilir veya listeyi temizleyebilirsin.`
              : 'Stok ve sevkiyat hedefi ekleyerek başla.'}
          </p>
          <button type="button" className="op-btn primary" onClick={() => setShowSetup(true)}>
            Kuruluma dön
          </button>
        </section>
      )}

      {groups.length > 0 && (() => {
        const allItems = groups.flatMap(g => g.items);
        const totReq = groups.reduce((s, g) => s + g.requested_quantity, 0);
        const totScan = groups.reduce((s, g) => s + g.scanned_quantity, 0);
        const totPct = totReq > 0 ? Math.min(100, Math.round((totScan / totReq) * 1000) / 10) : 0;
        const doneRefs = allItems.filter(it => it.is_complete || it.scanned_quantity >= it.requested_quantity).length;
        const shortRefs = allItems.filter(it => Number(it.short_quantity || 0) > 0).length;
        const totShortQty = allItems.reduce((s, it) => s + Number(it.short_quantity || 0), 0);
        const blockedRefs = allItems.filter(it => Number(it.blocked_label_count || 0) > 0).length;
        const totBlockedLbls = allItems.reduce((s, it) => s + Number(it.blocked_label_count || 0), 0);
        const fmt = (n: number) => new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2 }).format(n);

        const copyShortageToClipboard = async () => {
          if (shortRefs <= 0) return;
          const lines: string[] = [
            `EKSİK STOK LİSTESİ (${shortRefs} Referans - Toplam ${fmt(totShortQty)} Adet Eksik)`,
            '------------------------------------------------------------',
          ];
          groups.forEach((g, idx) => {
            const gTitle = g.name || `${idx + 1}. Sevkiyat`;
            const shorts = g.items.filter(it => Number(it.short_quantity || 0) > 0);
            if (shorts.length === 0) return;
            shorts.forEach(it => {
              const sq = Number(it.short_quantity || 0);
              lines.push(`${gTitle}\t${it.reference}\tEksik: ${fmt(sq)} adet (İstenen: ${fmt(it.requested_quantity)})`);
            });
          });
          const text = lines.join('\n');
          (window as unknown as { __lastCopiedShortageText?: string }).__lastCopiedShortageText = text;
          try {
            if (navigator.clipboard?.writeText) {
              await navigator.clipboard.writeText(text);
            } else {
              throw new Error('Clipboard API unavailable');
            }
          } catch {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
          }
          setCopiedShortage(true);
          window.setTimeout(() => setCopiedShortage(false), 2200);
        };

        return (
        <section className="op-section">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.65rem' }}>
            <h2 style={{ margin: 0 }}>Sevkiyatlar <span className="op-count">{groups.length}</span></h2>
            <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
              <button
                className="op-btn secondary compact"
                type="button"
                onClick={handleRecalculate}
                disabled={recalc?.phase === 'running'}
              >
                <RefreshCw size={14} />
                {recalc?.phase === 'running' ? 'Hesaplanıyor...' : 'Hesaplamayı yenile'}
              </button>
              <button
                className="op-btn secondary compact"
                type="button"
                onClick={() => setShowSetup(v => !v)}
              >
                {showSetup ? 'Kurulumu gizle' : 'Yeni sevkiyat'}
              </button>
            </div>
          </div>

          <div className="op-shipments-overview">
            <div className="op-ov-pill is-progress">
              <Layers size={13} />
              <span>Toplam: <strong>{fmt(totScan)} / {fmt(totReq)}</strong> adet (%{totPct})</span>
            </div>
            <div className="op-ov-pill is-refs">
              <Check size={13} />
              <span>Referans: <strong>{doneRefs} / {allItems.length}</strong> tamamlandı</span>
            </div>
            {shortRefs > 0 ? (
              <button
                type="button"
                className={`op-ov-pill is-short is-clickable ${copiedShortage ? 'is-copied' : ''}`}
                onClick={() => void copyShortageToClipboard()}
                title="Tıkla ve eksik stok listesini panoya kopyala"
              >
                {copiedShortage ? <Check size={13} /> : <TriangleAlert size={13} />}
                <span>
                  {copiedShortage ? (
                    <strong>Panoya Kopyalandı! ({shortRefs} Ref)</strong>
                  ) : (
                    <>Eksik Stok: <strong>{shortRefs} Ref ({fmt(totShortQty)} adet)</strong></>
                  )}
                </span>
                {!copiedShortage && <Copy size={12} className="op-ov-copy-icon" />}
              </button>
            ) : (
              <div className="op-ov-pill is-ok">
                <Check size={13} />
                <span>Eksik Stok: <strong>Yok</strong></span>
              </div>
            )}
            <div className={`op-ov-pill ${totBlockedLbls > 0 ? 'is-blocked' : 'is-neutral'}`}>
              <Lock size={13} />
              <span>
                {totBlockedLbls > 0
                  ? <>Blokaj: <strong>{blockedRefs} Ref • {totBlockedLbls} Etiket</strong></>
                  : <>Blokaj: <strong>Yok</strong></>}
              </span>
            </div>
          </div>

          <div className="op-shipment-table">
            {groups.map((g, idx) => (
              <ShipmentCard
                key={g.group_id}
                group={g}
                index={idx + 1}
                totalGroups={groups.length}
                isSelected={selectedGroupId === g.group_id}
                onSelect={() => {
                  handleSelectGroup(g.group_id);
                  focusScanInput();
                }}
                onUndoScan={handleUndoScan}
                onRenameGroup={handleRenameGroup}
                onRemove={askRemoveGroup}
                dragging={dragGroupId === g.group_id}
                dropTarget={dropGroupId === g.group_id && dragGroupId !== g.group_id}
                onDragStart={setDragGroupId}
                onDragOver={setDropGroupId}
                onDrop={(targetId, srcId) => {
                  const source = srcId ?? dragGroupId;
                  if (source != null) void reorderGroups(source, targetId);
                  setDragGroupId(null);
                  setDropGroupId(null);
                }}
                onDragEnd={() => {
                  setDragGroupId(null);
                  setDropGroupId(null);
                }}
                onMoveUp={idx > 0 ? () => void reorderGroups(g.group_id, groups[idx - 1].group_id) : undefined}
                onMoveDown={idx < groups.length - 1 ? () => void reorderGroups(g.group_id, groups[idx + 1].group_id) : undefined}
              />
            ))}
          </div>
        </section>
        );
      })()}
      </div>

      {isScanning && (
        <section className="op-section scan-section scan-dock">
          {/* Aktif Okutulan Sevkiyat Hedefi Banner'ı */}
          {(() => {
            const curGroup = groups.find(g => g.group_id === selectedGroupId) || groups[0];
            const curIdx = groups.findIndex(g => g.group_id === curGroup?.group_id);
            const title = curGroup?.name || `${curIdx + 1}. Sevkiyat`;
            const isDone = curGroup ? (curGroup.is_complete || curGroup.scanned_quantity >= curGroup.requested_quantity) : false;

            return (
              <div className="op-target-banner">
                <div className="op-target-banner-content">
                  <div className="op-target-banner-left">
                    <span className="op-target-icon" aria-hidden><Crosshair size={16} /></span>
                    <span className="op-target-label">Okutulan sevkiyat</span>
                    <strong className="op-target-name">{title}</strong>
                    <span className="op-target-meta">
                      ({curGroup?.items.length || 0} Referans • {curGroup?.scanned_quantity || 0}/{curGroup?.requested_quantity || 0} adet)
                    </span>
                    {isDone && <span className="op-done-tag"><Check size={13} /> Tamamlandı</span>}
                  </div>

                  {groups.length > 1 && (
                    <div className="op-target-switch-group">
                      <span className="op-switch-label">Hedef</span>
                      {groups.map((g, idx) => {
                        const gTitle = g.name || `${idx + 1}. Sevkiyat`;
                        const isSel = selectedGroupId === g.group_id;
                        return (
                          <button
                            key={g.group_id}
                            type="button"
                            className={`op-target-switch-btn ${isSel ? 'active' : ''}`}
                            onClick={() => {
                              handleSelectGroup(g.group_id);
                              focusScanInput();
                            }}
                          >
                            {idx + 1}. {gTitle}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            );
          })()}

          <div className="op-scan-head">
            <h2>Etiket okut</h2>
            <button
              type="button"
              className={`op-blokaj-mode-btn ${blockedOnly ? 'is-on' : ''}`}
              onClick={() => {
                setBlockedOnly(v => !v);
                focusScanInput();
              }}
              title={blockedOnly
                ? 'Açık: Sadece seçili sevkiyattaki BLOKAJLI (DOĞRU) etiketleri okur'
                : 'Kapalı: Normal FIFO etiketlerini okur (Blokajlıları reddeder)'}
            >
              {blockedOnly ? <Lock size={13} /> : <LockOpen size={13} />}
              <span>{blockedOnly ? 'Sadece Blokajlıları Oku: Açık' : 'Sadece Blokajlıları Oku: Kapalı'}</span>
            </button>
          </div>
          <form
            className="op-scan-area"
            onSubmit={e => {
              e.preventDefault();
              void handleScan(inputRef.current?.value || scanValue);
            }}
          >
            <input
              ref={inputRef}
              className="op-scan-input"
              value={scanValue}
              onChange={e => setScanValue(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Etiket okutun veya yazın..."
              autoFocus
            />
            <button type="submit" className="op-btn primary">OKUT</button>
          </form>

          <div className="op-result-wrap">
            <button
              type="button"
              className="op-result-fs-btn"
              onMouseDown={e => e.preventDefault()}
              onTouchStart={e => e.preventDefault()}
              onClick={enterFullscreen}
              title="Tam Ekran / Büyüteç Modu"
              aria-label="Bildirimi tam ekranda göster"
            >
              <Maximize2 size={16} aria-hidden />
            </button>

            <ScanNotice scan={lastScan} noticeKey={noticeKey} leaving={noticeLeaving} />
          </div>

          {recentScans.length > 0 && (
            <div className="op-recent">
              <h3>Son okutmalar</h3>
              {recentScans.map((s, i) => (
                  <div key={`${s.label}-${s.time}-${i}`} className={`op-recent-item tone-${s.result === 'SEVKİYAT ÜRÜNÜ' ? 'ok' : s.result === 'ZATEN OKUTULDU' ? 'dup' : s.result === 'MİKTAR AŞILDI' ? 'over' : s.result === 'ETİKET BULUNAMADI' ? 'miss' : 'out'}`}>
                    <ScanMark result={s.result} />
                    <span>{s.label}</span>
                    <span>{s.reference || s.result}</span>
                    {s.quantity != null && <span>{s.quantity} adet</span>}
                    <span className="op-recent-time">{s.time}</span>
                  </div>
                ))}
            </div>
          )}
        </section>
      )}
      </div>

      {isFullscreen && (
        <div className="fs-overlay" role="dialog" aria-modal="true" aria-label="Tam ekran okutma bildirimi" onClick={focusScanInput}>
          {/* Floating close button in top right */}
          <button type="button" className="fs-close-btn" onClick={exitFullscreen}>
            <X size={16} /> Tam ekrandan çık
          </button>

          <div className="fs-card-container">
            <ScanNotice scan={lastScan} size="stage" noticeKey={noticeKey} leaving={noticeLeaving} />
          </div>
        </div>
      )}

      {removeAsk && (
        <div className="recalc-overlay" role="dialog" aria-modal="true" aria-label="Sevkiyatı kaldır">
          <form
            className="recalc-card"
            onSubmit={e => {
              e.preventDefault();
              confirmRemoveGroup();
            }}
          >
            <h3>{removeAsk.kind === 'reset' ? 'Tüm sevkiyatlar sıfırlansın mı?' : `${removeAsk.label} kaldırılsın mı?`}</h3>
            <p>
              {removeAsk.kind === 'reset'
                ? 'Aktif sevkiyatlar ve okutmalar silinir. Silmek için evet yazın.'
                : 'Okutmalarıyla birlikte silinir. Diğer sevkiyatlar aynı kalır. Silmek için evet yazın.'}
            </p>
            <input
              className="remove-confirm-input"
              value={removeText}
              onChange={e => setRemoveText(e.target.value)}
              placeholder="evet"
              autoFocus
              autoComplete="off"
            />
            <div className="remove-confirm-actions">
              <button type="button" className="op-btn secondary compact" onClick={() => setRemoveAsk(null)}>
                Vazgeç
              </button>
              <button
                type="submit"
                className="op-btn danger compact"
                disabled={!confirmTyped || loading === 'remove' || loading === 'reset'}
              >
                {loading === 'remove' || loading === 'reset' ? 'Siliniyor...' : 'Sil'}
              </button>
            </div>
          </form>
        </div>
      )}

      {recalc && recalc.phase !== 'idle' && (
        <div className="recalc-overlay" role="dialog" aria-modal="true" aria-label="FIFO hesaplanıyor">
          <div className="recalc-card">
            <h3>FIFO hesaplanıyor</h3>
            <p>{recalc.message || 'Hazırlanıyor'}</p>
            <div
              className="recalc-track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={recalc.percent}
            >
              <div className="recalc-fill" style={{ width: `${Math.max(recalc.percent, 8)}%` }} />
            </div>
            <div className="recalc-meta">
              <span>{recalc.total > 0 ? `${Math.min(recalc.done, recalc.total)} / ${recalc.total} sevkiyat` : 'Başlatılıyor'}</span>
              <strong>%{recalc.percent}</strong>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
