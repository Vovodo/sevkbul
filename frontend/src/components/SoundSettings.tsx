import { useState, useEffect } from 'react';
import {
  AudioSettings,
  DEFAULT_AUDIO_SETTINGS,
  FAILURE_SOUND_OPTIONS,
  SUCCESS_SOUND_OPTIONS,
  FailureSoundId,
  SuccessSoundId,
  loadAudioSettings,
  subscribeAudioSettings,
  updateAudioSettings,
} from '../audioSettings';
import { previewFailureSound, previewSuccessSound, warmupAudioEngine } from '../audioEngine';

export default function SoundSettings() {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<AudioSettings>(loadAudioSettings);

  useEffect(() => subscribeAudioSettings(setSettings), []);

  const patch = (partial: Partial<AudioSettings>) => {
    setSettings(updateAudioSettings(partial));
  };

  const handleOpen = () => {
    warmupAudioEngine();
    setOpen(v => !v);
  };

  const previewSuccess = (id: SuccessSoundId) => {
    warmupAudioEngine();
    previewSuccessSound(id, settings);
  };

  const previewFailure = (id: FailureSoundId) => {
    warmupAudioEngine();
    previewFailureSound(id, settings);
  };

  return (
    <div className="sound-settings">
      <button type="button" className="sound-toggle-btn" onClick={handleOpen} aria-expanded={open}>
        🔊 SES AYARLARI
      </button>

      {open && (
        <section className="sound-panel">
          <div className="sound-panel-header">
            <h2>SES AYARLARI</h2>
            <label className="sound-switch">
              <input
                type="checkbox"
                checked={settings.enabled}
                onChange={e => patch({ enabled: e.target.checked })}
              />
              <span>Ses {settings.enabled ? 'Açık' : 'Kapalı'}</span>
            </label>
          </div>

          <div className="sound-sliders">
            <label className="sound-slider-row">
              <span>Ses Seviyesi</span>
              <input
                type="range"
                min={0.4}
                max={1}
                step={0.05}
                value={settings.volume}
                onChange={e => patch({ volume: parseFloat(e.target.value) })}
              />
              <strong>{Math.round(settings.volume * 100)}%</strong>
            </label>
            <label className="sound-slider-row">
              <span>Bas Güçlendirme</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={settings.bassBoost}
                onChange={e => patch({ bassBoost: parseFloat(e.target.value) })}
              />
              <strong>{Math.round(settings.bassBoost * 100)}%</strong>
            </label>
          </div>

          <div className="sound-group">
            <h3>Başarılı Ses</h3>
            <p className="sound-hint">Yükselen melodi = sevkiyat ürünü ✓ — depoda uzaktan duyulur</p>
            <div className="sound-options">
              {SUCCESS_SOUND_OPTIONS.map(opt => (
                <div
                  key={opt.id}
                  className={`sound-option ${settings.successSound === opt.id ? 'selected' : ''}`}
                >
                  <label className="sound-option-label">
                    <input
                      type="radio"
                      name="successSound"
                      checked={settings.successSound === opt.id}
                      onChange={() => patch({ successSound: opt.id })}
                    />
                    <div>
                      <strong>{opt.label}</strong>
                      <span>{opt.desc}</span>
                    </div>
                  </label>
                  <button
                    type="button"
                    className="sound-preview-btn"
                    onClick={() => previewSuccess(opt.id)}
                    disabled={!settings.enabled}
                  >
                    DİNLE
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="sound-group">
            <h3>Başarısız Ses</h3>
            <p className="sound-hint">BONK-BONK + alçalan buzz = sevkiyat dışı ✕ — başarılı sesten tamamen farklı</p>
            <div className="sound-options">
              {FAILURE_SOUND_OPTIONS.map(opt => (
                <div
                  key={opt.id}
                  className={`sound-option ${settings.failureSound === opt.id ? 'selected' : ''}`}
                >
                  <label className="sound-option-label">
                    <input
                      type="radio"
                      name="failureSound"
                      checked={settings.failureSound === opt.id}
                      onChange={() => patch({ failureSound: opt.id })}
                    />
                    <div>
                      <strong>{opt.label}</strong>
                      <span>{opt.desc}</span>
                    </div>
                  </label>
                  <button
                    type="button"
                    className="sound-preview-btn"
                    onClick={() => previewFailure(opt.id)}
                    disabled={!settings.enabled}
                  >
                    DİNLE
                  </button>
                </div>
              ))}
            </div>
          </div>

          <button
            type="button"
            className="op-btn secondary sound-reset"
            onClick={() => setSettings(updateAudioSettings({ ...DEFAULT_AUDIO_SETTINGS }))}
          >
            Varsayılana Sıfırla
          </button>
        </section>
      )}
    </div>
  );
}
