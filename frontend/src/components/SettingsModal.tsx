import { useEffect, useState } from 'react';
import { Check, Database, Download, FileSpreadsheet, HardDrive, RotateCcw, Save, Settings, Upload, X } from 'lucide-react';
import { api, ExcelHeaderInspectResult, ExcelHeaderSettings, StoredExcelFileItem } from '../api';

export const DEFAULT_EXCEL_HEADER_SETTINGS: ExcelHeaderSettings = {
  label_header: 'ETİKET',
  reference_header: 'REFERANS',
  quantity_header: 'MİKTAR',
  fifo_date_header: 'X98FIFO_TARIH',
  blocked_header: 'BLOKAJ',
  shipment_reference_header: 'REFERANS',
  shipment_quantity_header: 'MİKTAR',
};

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved?: (settings: ExcelHeaderSettings) => void;
}

export default function SettingsModal({ isOpen, onClose, onSaved }: SettingsModalProps) {
  const [form, setForm] = useState<ExcelHeaderSettings>(DEFAULT_EXCEL_HEADER_SETTINGS);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [inspected, setInspected] = useState<ExcelHeaderInspectResult | null>(null);
  const [inspectedFileName, setInspectedFileName] = useState('');
  const [storedFiles, setStoredFiles] = useState<StoredExcelFileItem[]>([]);

  useEffect(() => {
    if (!isOpen) return;
    setError('');
    setNotice('');
    setLoading(true);
    Promise.all([
      api.getExcelHeaders(),
      api.getStoredExcelFiles().catch(() => [] as StoredExcelFileItem[]),
    ])
      .then(([data, files]) => {
        setForm(data);
        setStoredFiles(files || []);
      })
      .catch(e => {
        setError(e instanceof Error ? e.message : 'Ayarlar yüklenemedi');
      })
      .finally(() => {
        setLoading(false);
      });
  }, [isOpen]);

  if (!isOpen) return null;

  const updateField = (key: keyof ExcelHeaderSettings, value: string) => {
    setForm(prev => ({ ...prev, [key]: value }));
    setNotice('');
    setError('');
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const saved = await api.updateExcelHeaders(form);
      setForm(saved);
      setNotice('Excel üst başlık ayarları kaydedildi. Yeni yüklenen Excel dosyaları bu başlıklara göre taranacak.');
      onSaved?.(saved);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ayarlar kaydedilemedi');
    } finally {
      setSaving(false);
    }
  };

  const handleResetDefaults = async () => {
    setResetting(true);
    setError('');
    setNotice('');
    try {
      const defaults = await api.resetExcelHeaders();
      setForm(defaults);
      setNotice('Varsayılan Excel üst başlık ayarlarına dönüldü.');
      onSaved?.(defaults);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Varsayılanlara dönülemedi');
    } finally {
      setResetting(false);
    }
  };

  const handleInspectFile = async (file: File) => {
    setInspecting(true);
    setError('');
    setNotice('');
    try {
      const res = await api.inspectExcelHeaders(file);
      setInspected(res);
      setInspectedFileName(file.name);
      setNotice(`"${file.name}" dosyasından ${res.headers.length} sütun üst başlığı okundu. Aşağıdaki seçim kutularından hızlıca eşleştirebilirsiniz.`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Örnek Excel okunamadı');
    } finally {
      setInspecting(false);
    }
  };

  const isCustom =
    form.label_header.trim().toUpperCase() !== DEFAULT_EXCEL_HEADER_SETTINGS.label_header ||
    form.reference_header.trim().toUpperCase() !== DEFAULT_EXCEL_HEADER_SETTINGS.reference_header ||
    form.quantity_header.trim().toUpperCase() !== DEFAULT_EXCEL_HEADER_SETTINGS.quantity_header ||
    form.fifo_date_header.trim().toUpperCase() !== DEFAULT_EXCEL_HEADER_SETTINGS.fifo_date_header ||
    form.blocked_header.trim().toUpperCase() !== DEFAULT_EXCEL_HEADER_SETTINGS.blocked_header ||
    form.shipment_reference_header.trim().toUpperCase() !== DEFAULT_EXCEL_HEADER_SETTINGS.shipment_reference_header ||
    form.shipment_quantity_header.trim().toUpperCase() !== DEFAULT_EXCEL_HEADER_SETTINGS.shipment_quantity_header;

  const stockFields: {
    key: keyof ExcelHeaderSettings;
    title: string;
    defaultVal: string;
    required: boolean;
    hint: string;
    placeholder: string;
  }[] = [
    {
      key: 'label_header',
      title: 'Etiket / Barkod Üst Başlığı',
      defaultVal: DEFAULT_EXCEL_HEADER_SETTINGS.label_header,
      required: true,
      hint: 'Stok Excel\'indeki benzersiz koli / etiket / barkod sütunu (Örn: ETİKET, BARKOD, KOLI_NO)',
      placeholder: 'ETİKET',
    },
    {
      key: 'reference_header',
      title: 'Referans / Ürün Kodu Üst Başlığı',
      defaultVal: DEFAULT_EXCEL_HEADER_SETTINGS.reference_header,
      required: true,
      hint: 'Stok Excel\'indeki ürün / malzeme / referans kodu sütunu (Örn: REFERANS, STOK_KODU, MALZEME)',
      placeholder: 'REFERANS',
    },
    {
      key: 'quantity_header',
      title: 'Miktar / Adet Üst Başlığı',
      defaultVal: DEFAULT_EXCEL_HEADER_SETTINGS.quantity_header,
      required: true,
      hint: 'Stok Excel\'indeki koli içi miktar / adet sütunu (Örn: MİKTAR, ADET, QUANTITY)',
      placeholder: 'MİKTAR',
    },
    {
      key: 'fifo_date_header',
      title: 'FIFO Tarihi Üst Başlığı',
      defaultVal: DEFAULT_EXCEL_HEADER_SETTINGS.fifo_date_header,
      required: true,
      hint: 'FIFO sıralamasının yapılacağı tarih/saat sütunu (Örn: X98FIFO_TARIH, OLUSTURMATARIHI, URETIM_TARIHI)',
      placeholder: 'X98FIFO_TARIH',
    },
    {
      key: 'blocked_header',
      title: 'Blokaj Durumu Üst Başlığı (Opsiyonel)',
      defaultVal: DEFAULT_EXCEL_HEADER_SETTINGS.blocked_header,
      required: false,
      hint: 'Blokajlı (DOĞRU/YANLIŞ) kontrolü için sütun başlığı. Excel\'de yoksa boş bırakabilirsiniz.',
      placeholder: 'BLOKAJ (Opsiyonel)',
    },
  ];

  return (
    <div className="manifest-overlay" onClick={onClose}>
      <div className="manifest-modal settings-modal" onClick={e => e.stopPropagation()}>
        <div className="manifest-header">
          <div className="manifest-title" style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap' }}>
            <Settings size={18} style={{ color: '#60a5fa' }} />
            <h2>AYARLAR — EXCEL ÜST BAŞLIK EŞLEŞTİRME</h2>
            <span className={`settings-mode-badge ${isCustom ? 'is-custom' : 'is-default'}`}>
              {isCustom ? 'Özel Başlık Ayarı Aktif' : 'Varsayılan Başlıklar Aktif'}
            </span>
          </div>
          <div className="manifest-actions">
            <button type="button" className="manifest-close-btn" onClick={onClose} title="Kapat" aria-label="Kapat">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="settings-modal-body">
          <div className="settings-intro-box">
            <div className="settings-intro-text">
              <strong>Firma & ERP Bağımsız Excel Üst Başlık Tanımlama</strong>
              <p>
                Yüklediğiniz Excel dosyalarında sistemin hangi sütun üst başlığını (1. satır) arayacağını buradan
                dilediğiniz gibi değiştirebilirsiniz. Birden fazla alternatif başlık tanımlamak isterseniz virgülle
                ayırarak yazabilirsiniz (Örn: <code>X98FIFO_TARIH, OLUSTURMATARIHI</code>).
              </p>
            </div>
            <label className="op-btn secondary compact settings-inspect-btn">
              <Upload size={14} />
              <span>{inspecting ? 'Okunuyor...' : 'Örnek Excel\'den Başlıkları Gör'}</span>
              <input
                type="file"
                accept=".xlsx,.xls"
                hidden
                onChange={e => {
                  const f = e.target.files?.[0];
                  e.target.value = '';
                  if (f) void handleInspectFile(f);
                }}
              />
            </label>
          </div>

          {error && <div className="op-alert error" style={{ margin: 0 }}>{error}</div>}
          {notice && (
            <div className="op-alert ok" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
              <Check size={15} />
              <span>{notice}</span>
            </div>
          )}

          {/* Canlı Excel Üst Başlık Şeridi Önizlemesi */}
          <div className="settings-excel-preview-card">
            <div className="settings-preview-title">
              <FileSpreadsheet size={14} />
              <span>Sistemin Stok Excel'inde Arayacağı Üst Başlık Şeridi (Canlı Önizleme)</span>
            </div>
            <div className="settings-excel-strip" role="region" aria-label="Excel üst başlık önizlemesi">
              <div className="settings-excel-cell">
                <span className="settings-excel-role">ETİKET / BARKOD</span>
                <strong>{form.label_header.trim() || '—'}</strong>
              </div>
              <div className="settings-excel-cell">
                <span className="settings-excel-role">REFERANS KODU</span>
                <strong>{form.reference_header.trim() || '—'}</strong>
              </div>
              <div className="settings-excel-cell">
                <span className="settings-excel-role">MİKTAR / ADET</span>
                <strong>{form.quantity_header.trim() || '—'}</strong>
              </div>
              <div className="settings-excel-cell is-fifo">
                <span className="settings-excel-role">FIFO TARİHİ</span>
                <strong>{form.fifo_date_header.trim() || '—'}</strong>
              </div>
              <div className="settings-excel-cell is-optional">
                <span className="settings-excel-role">BLOKAJ (OPSİYONEL)</span>
                <strong>{form.blocked_header.trim() || '(Kapalı)'}</strong>
              </div>
            </div>
          </div>

          {inspected && inspected.headers.length > 0 && (
            <div className="settings-inspected-box">
              <div className="settings-inspected-top">
                <span>
                  <strong>{inspectedFileName}</strong> içindeki üst başlıklar ({inspected.headers.length} sütun):
                </span>
                <button
                  type="button"
                  className="settings-clear-inspect"
                  onClick={() => {
                    setInspected(null);
                    setInspectedFileName('');
                  }}
                >
                  Gizle
                </button>
              </div>
              <div className="settings-header-chips">
                {inspected.headers.map(h => (
                  <span key={h} className="settings-header-chip" title="Aşağıdaki alanlardan birine seçebilirsiniz">
                    {h}
                  </span>
                ))}
              </div>
            </div>
          )}

          {loading ? (
            <div className="sc-empty">Ayarlar yükleniyor...</div>
          ) : (
            <div className="settings-sections-grid">
              <section className="settings-section-card">
                <div className="settings-section-head">
                  <h3>1. Stok (Etiket) Exceli Üst Başlıkları</h3>
                  <span>Stok listesi yüklenirken aranan sütun isimleri</span>
                </div>

                <div className="settings-fields-list">
                  {stockFields.map(field => (
                    <div key={field.key} className="settings-field-row">
                      <div className="settings-field-info">
                        <label htmlFor={`hdr-${field.key}`}>
                          {field.title}
                          {field.required ? (
                            <span className="settings-req-badge">Zorunlu</span>
                          ) : (
                            <span className="settings-opt-badge">Opsiyonel</span>
                          )}
                        </label>
                        <small>{field.hint}</small>
                      </div>
                      <div className="settings-field-controls">
                        <input
                          id={`hdr-${field.key}`}
                          type="text"
                          className="settings-header-input"
                          value={form[field.key]}
                          onChange={e => updateField(field.key, e.target.value)}
                          placeholder={field.placeholder}
                        />
                        {inspected && inspected.headers.length > 0 && (
                          <select
                            className="settings-header-select"
                            aria-label={`${field.title} için örnek Excel'den başlık seç`}
                            value={inspected.headers.includes(form[field.key]) ? form[field.key] : ''}
                            onChange={e => {
                              if (e.target.value) updateField(field.key, e.target.value);
                            }}
                          >
                            <option value="">Excel'den Seç...</option>
                            {inspected.headers.map(h => (
                              <option key={h} value={h}>
                                {h}
                              </option>
                            ))}
                          </select>
                        )}
                        <span className="settings-default-note">
                          Varsayılan: <code>{field.defaultVal}</code>
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="settings-section-card">
                <div className="settings-section-head">
                  <h3>2. Sevkiyat Hedef Exceli Üst Başlıkları</h3>
                  <span>Sevkiyat Excel'i yüklenirken aranan sütun isimleri (Başlıksız 2 sütunlu Excel desteği de devam eder)</span>
                </div>

                <div className="settings-fields-list">
                  <div className="settings-field-row">
                    <div className="settings-field-info">
                      <label htmlFor="hdr-shipment_reference_header">
                        Sevkiyat Referans Üst Başlığı
                        <span className="settings-req-badge">Zorunlu</span>
                      </label>
                      <small>Sevkiyat Excel'indeki referans/ürün kodu sütunu (Örn: REFERANS, STOK_KODU)</small>
                    </div>
                    <div className="settings-field-controls">
                      <input
                        id="hdr-shipment_reference_header"
                        type="text"
                        className="settings-header-input"
                        value={form.shipment_reference_header}
                        onChange={e => updateField('shipment_reference_header', e.target.value)}
                        placeholder="REFERANS"
                      />
                      {inspected && inspected.headers.length > 0 && (
                        <select
                          className="settings-header-select"
                          aria-label="Sevkiyat Referans için örnek Excel'den başlık seç"
                          value={inspected.headers.includes(form.shipment_reference_header) ? form.shipment_reference_header : ''}
                          onChange={e => {
                            if (e.target.value) updateField('shipment_reference_header', e.target.value);
                          }}
                        >
                          <option value="">Excel'den Seç...</option>
                          {inspected.headers.map(h => (
                            <option key={h} value={h}>
                              {h}
                            </option>
                          ))}
                        </select>
                      )}
                      <span className="settings-default-note">
                        Varsayılan: <code>{DEFAULT_EXCEL_HEADER_SETTINGS.shipment_reference_header}</code>
                      </span>
                    </div>
                  </div>

                  <div className="settings-field-row">
                    <div className="settings-field-info">
                      <label htmlFor="hdr-shipment_quantity_header">
                        Sevkiyat Miktar Üst Başlığı
                        <span className="settings-req-badge">Zorunlu</span>
                      </label>
                      <small>Sevkiyat Excel'indeki istenen adet/miktar sütunu (Örn: MİKTAR, SEVK_ADET, ADET)</small>
                    </div>
                    <div className="settings-field-controls">
                      <input
                        id="hdr-shipment_quantity_header"
                        type="text"
                        className="settings-header-input"
                        value={form.shipment_quantity_header}
                        onChange={e => updateField('shipment_quantity_header', e.target.value)}
                        placeholder="MİKTAR"
                      />
                      {inspected && inspected.headers.length > 0 && (
                        <select
                          className="settings-header-select"
                          aria-label="Sevkiyat Miktar için örnek Excel'den başlık seç"
                          value={inspected.headers.includes(form.shipment_quantity_header) ? form.shipment_quantity_header : ''}
                          onChange={e => {
                            if (e.target.value) updateField('shipment_quantity_header', e.target.value);
                          }}
                        >
                          <option value="">Excel'den Seç...</option>
                          {inspected.headers.map(h => (
                            <option key={h} value={h}>
                              {h}
                            </option>
                          ))}
                        </select>
                      )}
                      <span className="settings-default-note">
                        Varsayılan: <code>{DEFAULT_EXCEL_HEADER_SETTINGS.shipment_quantity_header}</code>
                      </span>
                    </div>
                  </div>
                </div>
              </section>

              <section className="settings-section-card">
                <div className="settings-section-head">
                  <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                    <HardDrive size={15} style={{ color: '#38bdf8' }} />
                    <span>3. Mini S3 Sunucu Depolama & PostgreSQL Kalıcı Excel Kayıtları</span>
                  </h3>
                  <span>Yeni Excel yüklendiğinde eski dosya otomatik silinir; sunucu restart yediğinde sıfırlanmaz</span>
                </div>

                {storedFiles.length === 0 ? (
                  <div style={{ fontSize: '0.78rem', color: '#94a3b8', padding: '0.35rem 0' }}>
                    Henüz Mini S3 depolama alanına yüklenmiş Excel dosyası bulunmuyor.
                  </div>
                ) : (
                  <div className="settings-fields-list">
                    {storedFiles.map(sf => {
                      const kb = Math.max(1, Math.round(sf.size_bytes / 1024));
                      const slotTitle = sf.slot === 'stock' ? 'Aktif Stok (Etiket) Exceli' : 'Son Sevkiyat Hedef Exceli';
                      return (
                        <div key={sf.slot} className="settings-field-row">
                          <div className="settings-field-info">
                            <label>
                              <Database size={13} style={{ color: '#60a5fa' }} />
                              <span>{slotTitle}</span>
                              <span className="settings-req-badge">{sf.original_filename}</span>
                            </label>
                            <small>
                              Konum: <code>{sf.storage_key}</code> ({sf.local_path}) • Boyut: <strong>{kb} KB</strong> • Kayıt: <strong>{sf.row_count.toLocaleString('tr-TR')} satır</strong> • Tarih: {sf.uploaded_at}
                            </small>
                          </div>
                          <div className="settings-field-controls" style={{ alignItems: 'flex-end' }}>
                            <a
                              href={api.storedExcelDownloadUrl(sf.slot)}
                              download
                              className="op-btn secondary compact"
                              style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', textDecoration: 'none' }}
                            >
                              <Download size={14} />
                              <span>Sunucudan İndir (.xlsx)</span>
                            </a>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </section>
            </div>
          )}
        </div>

        <div className="settings-modal-footer">
          <button
            type="button"
            className="op-btn secondary compact"
            onClick={handleResetDefaults}
            disabled={resetting || saving}
            title="Tüm başlıkları fabrika varsayılanlarına (ETİKET, REFERANS, MİKTAR, X98FIFO_TARIH, BLOKAJ) döndürür"
          >
            <RotateCcw size={14} />
            <span>{resetting ? 'Sıfırlanıyor...' : 'Varsayılanlara Dön'}</span>
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
            <button type="button" className="op-btn secondary compact" onClick={onClose}>
              Kapat
            </button>
            <button
              type="button"
              className="op-btn primary compact"
              onClick={handleSave}
              disabled={saving || resetting}
            >
              <Save size={14} />
              <span>{saving ? 'Kaydediliyor...' : 'Ayarları Kaydet'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
