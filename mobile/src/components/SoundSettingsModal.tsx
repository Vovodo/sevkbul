import { useState } from 'react';
import { Volume2, VolumeX, Smartphone, Play, Check, X } from 'lucide-react';
import {
  MobileAudioSettings,
  SuccessSoundId,
  FailureSoundId,
  loadMobileAudioSettings,
  saveMobileAudioSettings,
} from '../audio/audioSettings';
import { playMobileSound, triggerTapHaptic } from '../audio/audioEngine';

interface SoundSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const SUCCESS_OPTIONS: { id: SuccessSoundId; name: string }[] = [
  { id: 'minecraft_levelup', name: '🎮 Minecraft Level Up (Tavsiye Edilen)' },
  { id: 'cyber_chime', name: '🎵 Siber Melodi (Klasik Çan)' },
  { id: 'industrial_laser', name: '⚡ Endüstriyel Lazer' },
  { id: 'hyper_beep', name: '📟 Hiper El Terminali Bip' },
];

const FAILURE_OPTIONS: { id: FailureSoundId; name: string }[] = [
  { id: 'warehouse_alarm', name: '🚨 Depo İkaz Sireni' },
  { id: 'hyper_error', name: '🚫 Hiper Red İkazı' },
  { id: 'metal_strike', name: '💥 Metalik Sert İptal' },
  { id: 'emergency_buzz', name: '⚠️ Acil İkaz Hörnü' },
];

export default function SoundSettingsModal({ isOpen, onClose }: SoundSettingsModalProps) {
  const [settings, setSettings] = useState<MobileAudioSettings>(() => loadMobileAudioSettings());

  if (!isOpen) return null;

  const handleUpdate = (updater: (prev: MobileAudioSettings) => MobileAudioSettings) => {
    setSettings((prev) => {
      const next = updater(prev);
      saveMobileAudioSettings(next);
      return next;
    });
  };

  const handlePreviewSuccess = (id: SuccessSoundId) => {
    void triggerTapHaptic();
    playMobileSound('success', { ...settings, enabled: true, successSound: id });
  };

  const handlePreviewFailure = (id: FailureSoundId) => {
    void triggerTapHaptic();
    playMobileSound('failure', { ...settings, enabled: true, failureSound: id });
  };

  const handlePreviewExceeded = () => {
    void triggerTapHaptic();
    playMobileSound('exceeded', { ...settings, enabled: true });
  };

  const handlePreviewCompletion = () => {
    void triggerTapHaptic();
    playMobileSound('completion', { ...settings, enabled: true });
  };

  return (
    <div className="bottom-sheet-overlay" onClick={onClose}>
      <div className="bottom-sheet-content" onClick={(e) => e.stopPropagation()}>
        <div className="bottom-sheet-handle" />

        <div className="bottom-sheet-header">
          <div className="sheet-title-wrap">
            <Volume2 size={20} className="text-primary" />
            <h3>Ses ve Titreşim Ayarları</h3>
          </div>
          <button type="button" className="sheet-close-btn" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="bottom-sheet-body">
          {/* Master Toggles */}
          <div className="settings-card">
            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Ses Efektleri</span>
                <span className="setting-desc">Okutma ve bildirim sesleri</span>
              </div>
              <button
                type="button"
                className={`mobile-switch ${settings.enabled ? 'active' : ''}`}
                onClick={() => handleUpdate((s) => ({ ...s, enabled: !s.enabled }))}
              >
                <span className="switch-knob">
                  {settings.enabled ? <Volume2 size={12} /> : <VolumeX size={12} />}
                </span>
              </button>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Titreşim (Haptic)</span>
                <span className="setting-desc">Okutma anında dokunsal geri bildirim</span>
              </div>
              <button
                type="button"
                className={`mobile-switch ${settings.hapticsEnabled ? 'active' : ''}`}
                onClick={() => {
                  void triggerTapHaptic();
                  handleUpdate((s) => ({ ...s, hapticsEnabled: !s.hapticsEnabled }));
                }}
              >
                <span className="switch-knob">
                  <Smartphone size={12} />
                </span>
              </button>
            </div>

            {/* Volume Slider */}
            {settings.enabled && (
              <div className="setting-slider-row">
                <div className="slider-label-wrap">
                  <span>Ses Seviyesi</span>
                  <strong>%{Math.round(settings.volume * 100)}</strong>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value={settings.volume}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value);
                    handleUpdate((s) => ({ ...s, volume: val }));
                  }}
                  className="mobile-range-slider"
                />
              </div>
            )}
          </div>

          {/* Preset Sound Selections */}
          {settings.enabled && (
            <>
              {/* Success Sound Picker */}
              <div className="settings-section">
                <h4 className="section-subtitle">Başarılı Okutma Sesi</h4>
                <div className="options-list">
                  {SUCCESS_OPTIONS.map((opt) => {
                    const selected = settings.successSound === opt.id;
                    return (
                      <div
                        key={opt.id}
                        className={`option-card ${selected ? 'selected' : ''}`}
                        onClick={() => handleUpdate((s) => ({ ...s, successSound: opt.id }))}
                      >
                        <div className="option-title">
                          <span className="radio-dot">{selected && <Check size={12} />}</span>
                          <span>{opt.name}</span>
                        </div>
                        <button
                          type="button"
                          className="preview-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            handlePreviewSuccess(opt.id);
                          }}
                          title="Önizle"
                        >
                          <Play size={14} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Failure Sound Picker */}
              <div className="settings-section">
                <h4 className="section-subtitle">Hatalı Okutma Sesi</h4>
                <div className="options-list">
                  {FAILURE_OPTIONS.map((opt) => {
                    const selected = settings.failureSound === opt.id;
                    return (
                      <div
                        key={opt.id}
                        className={`option-card ${selected ? 'selected' : ''}`}
                        onClick={() => handleUpdate((s) => ({ ...s, failureSound: opt.id }))}
                      >
                        <div className="option-title">
                          <span className="radio-dot">{selected && <Check size={12} />}</span>
                          <span>{opt.name}</span>
                        </div>
                        <button
                          type="button"
                          className="preview-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            handlePreviewFailure(opt.id);
                          }}
                          title="Önizle"
                        >
                          <Play size={14} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Special Event Previews */}
              <div className="settings-section">
                <h4 className="section-subtitle">Özel Olay Testleri</h4>
                <div className="special-preview-grid">
                  <button type="button" className="special-btn orange" onClick={handlePreviewExceeded}>
                    <span>🚫 Miktar Aşıldı</span>
                    <Play size={13} />
                  </button>
                  <button type="button" className="special-btn green" onClick={handlePreviewCompletion}>
                    <span>🏆 Tamamlanma</span>
                    <Play size={13} />
                  </button>
                </div>
              </div>
            </>
          )}

          <div className="sheet-actions">
            <button type="button" className="mobile-btn primary full" onClick={onClose}>
              Tamamla ve Kapat
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
