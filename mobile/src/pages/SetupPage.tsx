import { useState } from 'react';
import { Upload, Plus, Clock, Calendar, CheckCircle, AlertCircle, Play } from 'lucide-react';
import { api, ShipmentTarget } from '../api';
import { triggerTapHaptic } from '../audio/audioEngine';

interface SetupPageProps {
  targets: ShipmentTarget[];
  onRefreshTargets: () => void;
  onShipmentsFound: () => void;
  stockLoaded: boolean;
  stockCount: number;
}

export default function SetupPage({
  targets,
  onRefreshTargets,
  onShipmentsFound,
  stockLoaded,
  stockCount,
}: SetupPageProps) {
  const [manualRef, setManualRef] = useState<string>('');
  const [manualQty, setManualQty] = useState<string>('');
  const [hourlyFifo, setHourlyFifo] = useState<boolean>(() => localStorage.getItem('hourlyFifo') === 'true');
  const [loadingAction, setLoadingAction] = useState<string>('');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [successMsg, setSuccessMsg] = useState<string>('');

  const handleStockUpload = async (file: File) => {
    setLoadingAction('stock');
    setErrorMsg('');
    setSuccessMsg('');
    try {
      const res = await api.importStock(file);
      setSuccessMsg(`✓ Stok başarıyla yüklendi: ${res.successful.toLocaleString('tr-TR')} etiket kaydedildi.`);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Stok Exceli yüklenemedi');
    } finally {
      setLoadingAction('');
    }
  };

  const handleShipmentExcel = async (file: File) => {
    setLoadingAction('shipment');
    setErrorMsg('');
    setSuccessMsg('');
    try {
      const res = await api.importTargetsExcel(file);
      setSuccessMsg(`✓ Sevkiyat hedefleri yüklendi: ${res.successful} hedef eklendi.`);
      onRefreshTargets();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Sevkiyat Exceli yüklenemedi');
    } finally {
      setLoadingAction('');
    }
  };

  const handleAddManualTarget = async (e: React.FormEvent) => {
    e.preventDefault();
    const ref = manualRef.trim();
    const qty = parseFloat(manualQty);
    if (!ref || isNaN(qty) || qty <= 0) {
      setErrorMsg('Lütfen geçerli bir referans ve miktar girin.');
      return;
    }

    void triggerTapHaptic();
    setLoadingAction('add_target');
    setErrorMsg('');
    try {
      await api.addTarget(ref, qty);
      setManualRef('');
      setManualQty('');
      setSuccessMsg(`✓ "${ref}" (${qty} adet) hedef olarak eklendi.`);
      onRefreshTargets();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Hedef eklenemedi');
    } finally {
      setLoadingAction('');
    }
  };

  const handleFindShipments = async () => {
    void triggerTapHaptic();
    setLoadingAction('find');
    setErrorMsg('');
    try {
      await api.findShipments(hourlyFifo);
      onShipmentsFound();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Sevkiyat havuzu hesaplanamadı');
    } finally {
      setLoadingAction('');
    }
  };

  const toggleHourly = () => {
    void triggerTapHaptic();
    setHourlyFifo((prev) => {
      const next = !prev;
      localStorage.setItem('hourlyFifo', String(next));
      return next;
    });
  };

  return (
    <div className="mobile-page setup-page">
      <div className="page-section-header">
        <div>
          <h2>Sevkiyat Kurulumu</h2>
          <span className="page-section-desc">Stok ve sevkiyat hedeflerini tanımlayın</span>
        </div>
      </div>

      {errorMsg && (
        <div className="mobile-alert error">
          <AlertCircle size={16} />
          <span>{errorMsg}</span>
        </div>
      )}

      {successMsg && (
        <div className="mobile-alert success">
          <CheckCircle size={16} />
          <span>{successMsg}</span>
        </div>
      )}

      {/* 1. Excel Upload Cards */}
      <div className="setup-grid">
        {/* Stock Excel Card */}
        <div className="setup-card">
          <div className="card-header-compact">
            <span className="card-icon">📊</span>
            <div>
              <h4>STOK EXCELİ</h4>
              <span className="card-sub">ETİKET, REFERANS, MİKTAR, X98FIFO</span>
            </div>
          </div>

          <div className="card-body-compact">
            {stockLoaded ? (
              <div className="loaded-badge-row">
                <span className="stock-badge">✓ {stockCount.toLocaleString('tr-TR')} Etiket Yüklü</span>
              </div>
            ) : (
              <span className="unloaded-hint">Henüz stok yüklenmedi</span>
            )}

            <label className="mobile-file-btn">
              <Upload size={16} />
              <span>{loadingAction === 'stock' ? 'Yükleniyor...' : stockLoaded ? 'Stoku Güncelle' : 'Dosya Seç (.xlsx)'}</span>
              <input
                type="file"
                accept=".xlsx,.xls"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void handleStockUpload(f);
                }}
              />
            </label>
          </div>
        </div>

        {/* Shipment Targets Excel Card */}
        <div className="setup-card">
          <div className="card-header-compact">
            <span className="card-icon">📋</span>
            <div>
              <h4>SEVKİYAT HEDEF EXCELİ</h4>
              <span className="card-sub">Toplu referans ve adet listesi</span>
            </div>
          </div>

          <div className="card-body-compact">
            <label className="mobile-file-btn">
              <Upload size={16} />
              <span>{loadingAction === 'shipment' ? 'Yükleniyor...' : 'Hedef Exceli Seç (.xlsx)'}</span>
              <input
                type="file"
                accept=".xlsx,.xls"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void handleShipmentExcel(f);
                }}
              />
            </label>
          </div>
        </div>
      </div>

      {/* 2. Manual Target Addition */}
      <div className="manual-target-card">
        <h4>Veya Manuel Hedef Ekle</h4>
        <form onSubmit={handleAddManualTarget} className="manual-target-form">
          <div className="form-row">
            <div className="form-field flex-2">
              <label>Referans Kodu</label>
              <input
                type="text"
                value={manualRef}
                onChange={(e) => setManualRef(e.target.value)}
                placeholder="Örn: 6681369-HZN-1"
                className="mobile-input"
              />
            </div>

            <div className="form-field flex-1">
              <label>Hedef Adet</label>
              <input
                type="number"
                value={manualQty}
                onChange={(e) => setManualQty(e.target.value)}
                placeholder="240"
                className="mobile-input"
              />
            </div>
          </div>

          <button
            type="submit"
            className="mobile-btn secondary full"
            disabled={loadingAction === 'add_target' || !manualRef.trim() || !manualQty}
          >
            <Plus size={16} />
            <span>Hedef Ekle</span>
          </button>
        </form>
      </div>

      {/* 3. Defined Targets List */}
      {targets.length > 0 && (
        <div className="defined-targets-section">
          <div className="section-title-row">
            <h4>Tanımlı Hedefler ({targets.length})</h4>
          </div>

          <div className="targets-chip-list">
            {targets.map((t) => (
              <div key={t.id} className="target-chip">
                <span className="target-ref font-mono">{t.reference}</span>
                <span className="target-qty">{t.target_quantity} Adet</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4. FIFO Time Filter Toggle */}
      <div className="fifo-toggle-card">
        <div className="toggle-info">
          <div className="toggle-icon-wrap">
            {hourlyFifo ? <Clock size={20} className="text-primary" /> : <Calendar size={20} className="text-muted" />}
          </div>
          <div>
            <strong className="toggle-title">FİFO Saat Önceliği Filtresi</strong>
            <p className="toggle-desc">
              {hourlyFifo
                ? '⚡ AÇIK: Aynı gün üretilenlerde saat:dakika sırasına göre dağıtır.'
                : '📅 KAPALI: Gün bazında gruplar (Saat önemsiz).'}
            </p>
          </div>
        </div>

        <button
          type="button"
          className={`mobile-switch ${hourlyFifo ? 'active' : ''}`}
          onClick={toggleHourly}
        >
          <span className="switch-knob" />
        </button>
      </div>

      {/* 5. Main Action Button: SEVKİYATI BUL */}
      <div className="find-action-wrapper">
        <button
          type="button"
          className="mobile-btn primary large full pulse-glow"
          onClick={handleFindShipments}
          disabled={loadingAction === 'find' || targets.length === 0}
        >
          <Play size={20} />
          <span>{loadingAction === 'find' ? 'FİFO Hesaplanıyor...' : 'SEVKİYATI BUL & BAŞLAT'}</span>
        </button>
        {targets.length === 0 && (
          <span className="find-hint">Sevkiyatı başlatmak için en az 1 hedef tanımlayın.</span>
        )}
      </div>
    </div>
  );
}
