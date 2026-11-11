import { useEffect, useState } from 'react';
import { Check, Edit2, Layers, Package, Plus, Radio, Trash2, UserCheck, Users, X } from 'lucide-react';
import { api, WorkSessionItem } from '../api';

interface SessionModalProps {
  isOpen: boolean;
  onClose: () => void;
  activeSessionId: number;
  sessions: WorkSessionItem[];
  onSessionsChange: (sessions: WorkSessionItem[]) => void;
  onSelectSession: (sessionId: number) => void;
}

export default function SessionModal({
  isOpen,
  onClose,
  activeSessionId,
  sessions,
  onSessionsChange,
  onSelectSession,
}: SessionModalProps) {
  const [name, setName] = useState('');
  const [staffName, setStaffName] = useState('');
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [editStaff, setEditStaff] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setError('');
    setLoading(true);
    api
      .getSessions()
      .then(list => {
        onSessionsChange(list);
      })
      .catch(e => {
        setError(e instanceof Error ? e.message : 'Oturum listesi alınamadı');
      })
      .finally(() => {
        setLoading(false);
      });
  }, [isOpen, onSessionsChange]);

  if (!isOpen) return null;

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || creating) return;
    setCreating(true);
    setError('');
    try {
      const created = await api.createSession({
        name: name.trim(),
        staff_name: staffName.trim() || undefined,
        description: description.trim() || undefined,
      });
      const updatedList = await api.getSessions();
      onSessionsChange(updatedList);
      setName('');
      setStaffName('');
      setDescription('');
      onSelectSession(created.id);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Oturum oluşturulamadı');
    } finally {
      setCreating(false);
    }
  };

  const startEdit = (item: WorkSessionItem) => {
    setEditingId(item.id);
    setEditName(item.name);
    setEditStaff(item.staff_name || '');
  };

  const saveEdit = async (id: number) => {
    if (!editName.trim() || savingEdit) return;
    setSavingEdit(true);
    setError('');
    try {
      await api.updateSession(id, {
        name: editName.trim(),
        staff_name: editStaff.trim(),
      });
      const updatedList = await api.getSessions();
      onSessionsChange(updatedList);
      setEditingId(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Oturum güncellenemedi');
    } finally {
      setSavingEdit(false);
    }
  };

  const handleDelete = async (item: WorkSessionItem) => {
    const confirmMsg =
      item.id === 1
        ? `"${item.name}" varsayılan oturumunun içindeki tüm stok ve sevkiyat verilerini temizlemek istiyor musunuz?`
        : `"${item.name}" oturumunu ve içindeki tüm stok/sevkiyat verilerini silmek istiyor musunuz?`;
    if (!window.confirm(confirmMsg)) return;

    setDeletingId(item.id);
    setError('');
    try {
      const res = await api.deleteSession(item.id);
      onSessionsChange(res.sessions);
      if (activeSessionId === item.id && item.id !== 1) {
        onSelectSession(1);
      } else if (activeSessionId === item.id && item.id === 1) {
        onSelectSession(1);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Oturum silinemedi');
    } finally {
      setDeletingId(null);
    }
  };

  const fmtNum = (n: number) => new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2 }).format(n);

  return (
    <div className="manifest-overlay" onClick={onClose}>
      <div className="manifest-modal session-modal" onClick={e => e.stopPropagation()}>
        <div className="manifest-header">
          <div className="manifest-title" style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap' }}>
            <Users size={18} style={{ color: '#38bdf8' }} />
            <h2>OTURUMLAR & PROJE ÇALIŞMA ALANLARI</h2>
            <span className="settings-mode-badge is-custom">
              {sessions.length} Aktif Oturum
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
              <strong>Çoklu Personel & Çoklu Proje İzolasyonu + Ortak Canlı Oturum (WebSocket Odası)</strong>
              <p>
                Her oturum kendi bağımsız <strong>Stok Excel'ine</strong>, <strong>Sevkiyatlarına</strong> ve{' '}
                <strong>Barkod Okutmalarına</strong> sahiptir. Bir personel <em>X Projesi</em> oturumunda çalışırken,
                diğer personel <em>Y Projesi</em> oturumunda kendi Excel'ini yükleyip bağımsız çalışabilir. Aynı oturuma
                katılan birden fazla cihaz ise birbirinin okutmalarını canlı olarak takip eder.
              </p>
            </div>
          </div>

          {error && <div className="op-alert error" style={{ margin: 0 }}>{error}</div>}

          {/* Yeni Oturum / Proje Oluşturma Formu */}
          <form className="session-create-card" onSubmit={handleCreate}>
            <div className="session-create-title">
              <Plus size={15} style={{ color: '#60a5fa' }} />
              <span>Yeni Oturum / Proje Çalışma Alanı Aç</span>
            </div>
            <div className="session-create-grid">
              <div className="session-input-group">
                <label htmlFor="new-session-name">Proje / Oturum Adı *</label>
                <input
                  id="new-session-name"
                  type="text"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Örn: X Projesi, Y Projesi, Ford Sevkiyat"
                  required
                  maxLength={120}
                />
              </div>
              <div className="session-input-group">
                <label htmlFor="new-session-staff">Personel / Sorumlu Adı</label>
                <input
                  id="new-session-staff"
                  type="text"
                  value={staffName}
                  onChange={e => setStaffName(e.target.value)}
                  placeholder="Örn: Personel 1, Ahmet, Vardiya A"
                  maxLength={100}
                />
              </div>
              <div className="session-input-group">
                <label htmlFor="new-session-desc">Açıklama / Not (Opsiyonel)</label>
                <input
                  id="new-session-desc"
                  type="text"
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  placeholder="Örn: 2. Hol FIFO Kontrolü"
                  maxLength={200}
                />
              </div>
              <button
                type="submit"
                className="op-btn primary compact session-create-submit"
                disabled={creating || !name.trim()}
              >
                <Plus size={15} />
                <span>{creating ? 'Açılıyor...' : 'Yeni Oturum Aç ve Geç'}</span>
              </button>
            </div>
          </form>

          {/* Mevcut Oturumlar Listesi */}
          <div className="session-list-section">
            <div className="session-list-header">
              <h3>Mevcut Çalışma Oturumları ({sessions.length})</h3>
              <span>Katılmak istediğiniz projenin / personelin oturumunu seçin</span>
            </div>

            {loading && sessions.length === 0 ? (
              <div className="sc-empty">Oturumlar yükleniyor...</div>
            ) : (
              <div className="session-cards-grid">
                {sessions.map(item => {
                  const isCurrent = item.id === activeSessionId;
                  const isEditing = editingId === item.id;
                  const pct =
                    item.requested_quantity > 0
                      ? Math.min(100, Math.round((item.scanned_quantity / item.requested_quantity) * 100))
                      : 0;

                  return (
                    <div
                      key={item.id}
                      className={`session-item-card ${isCurrent ? 'is-active' : ''}`}
                    >
                      <div className="session-card-top">
                        <div className="session-card-identity">
                          <span className="session-id-badge">#{item.id}</span>
                          {isEditing ? (
                            <div className="session-inline-edit">
                              <input
                                type="text"
                                value={editName}
                                onChange={e => setEditName(e.target.value)}
                                placeholder="Oturum adı"
                                aria-label="Oturum adını düzenle"
                              />
                              <input
                                type="text"
                                value={editStaff}
                                onChange={e => setEditStaff(e.target.value)}
                                placeholder="Personel adı"
                                aria-label="Personel adını düzenle"
                              />
                              <button
                                type="button"
                                className="op-btn primary compact"
                                onClick={() => void saveEdit(item.id)}
                                disabled={savingEdit}
                              >
                                Kaydet
                              </button>
                              <button
                                type="button"
                                className="op-btn secondary compact"
                                onClick={() => setEditingId(null)}
                              >
                                İptal
                              </button>
                            </div>
                          ) : (
                            <div>
                              <div className="session-title-row">
                                <strong className="session-card-name">{item.name}</strong>
                                {item.staff_name && (
                                  <span className="session-staff-pill">
                                    <UserCheck size={12} />
                                    <span>{item.staff_name}</span>
                                  </span>
                                )}
                              </div>
                              {item.description && (
                                <p className="session-card-desc">{item.description}</p>
                              )}
                            </div>
                          )}
                        </div>

                        <div className="session-card-live">
                          <span className={`session-device-pill ${item.connected_clients > 0 ? 'is-online' : ''}`}>
                            <Radio size={11} />
                            <span>
                              {item.connected_clients > 0
                                ? `${item.connected_clients} Cihaz Bağlı`
                                : 'Beklemede'}
                            </span>
                          </span>
                        </div>
                      </div>

                      <div className="session-card-stats">
                        <div className="session-stat-chip">
                          <Package size={13} />
                          <span>Stok: <strong>{item.total_labels.toLocaleString('tr-TR')} Etiket</strong></span>
                        </div>
                        <div className="session-stat-chip">
                          <Layers size={13} />
                          <span>Sevkiyat: <strong>{item.shipment_count} Grup</strong></span>
                        </div>
                        <div className="session-stat-chip">
                          <span>
                            Okutma: <strong>{fmtNum(item.scanned_quantity)} / {fmtNum(item.requested_quantity)}</strong> (%{pct})
                          </span>
                        </div>
                      </div>

                      <div className="session-card-actions">
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          {!isEditing && (
                            <button
                              type="button"
                              className="session-icon-btn"
                              onClick={() => startEdit(item)}
                              title="Oturum / Personel adını düzenle"
                            >
                              <Edit2 size={13} />
                              <span>Düzenle</span>
                            </button>
                          )}
                          <button
                            type="button"
                            className="session-icon-btn is-danger"
                            onClick={() => void handleDelete(item)}
                            disabled={deletingId === item.id}
                            title={item.id === 1 ? 'Varsayılan oturum verilerini sıfırla' : 'Bu oturumu sil'}
                          >
                            <Trash2 size={13} />
                            <span>{item.id === 1 ? 'Temizle' : 'Sil'}</span>
                          </button>
                        </div>

                        {isCurrent ? (
                          <span className="session-current-badge">
                            <Check size={14} />
                            <span>Şu An Bu Oturumdasınız</span>
                          </span>
                        ) : (
                          <button
                            type="button"
                            className="op-btn primary compact session-join-btn"
                            onClick={() => {
                              onSelectSession(item.id);
                              onClose();
                            }}
                          >
                            <Users size={14} />
                            <span>Bu Oturuma Katıl / Geç</span>
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div className="settings-modal-footer">
          <span style={{ fontSize: '0.76rem', color: '#94a3b8' }}>
            Aktif Oturum ID: <strong>#{activeSessionId}</strong> — Aynı oturuma katılan tüm personel canlı olarak ortak çalışır.
          </span>
          <button type="button" className="op-btn secondary compact" onClick={onClose}>
            Kapat
          </button>
        </div>
      </div>
    </div>
  );
}
