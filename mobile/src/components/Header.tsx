import { Volume2, VolumeX, Wifi, WifiOff } from 'lucide-react';
import { loadMobileAudioSettings } from '../audio/audioSettings';

interface HeaderProps {
  wsConnected: boolean;
  activeShipmentCount: number;
  totalProgress: { scanned: number; target: number };
  onOpenSoundSettings: () => void;
}

export default function Header({
  wsConnected,
  activeShipmentCount,
  totalProgress,
  onOpenSoundSettings,
}: HeaderProps) {
  const audioSettings = loadMobileAudioSettings();

  return (
    <header className="mobile-header">
      <div className="header-left">
        <div className="header-logo-badge">
          <span className="logo-icon">📦</span>
          <div className="header-titles">
            <h1 className="app-title">SevkiyatBul</h1>
            <span className="app-subtitle">Mobil Operasyon</span>
          </div>
        </div>
      </div>

      <div className="header-right">
        {/* WebSocket Status Indicator */}
        <div className={`ws-status-badge ${wsConnected ? 'online' : 'offline'}`}>
          {wsConnected ? <Wifi size={13} className="pulse-icon" /> : <WifiOff size={13} />}
          <span>{wsConnected ? 'CANLI' : 'KOPUK'}</span>
        </div>

        {/* Active Progress Badge if shipments active */}
        {activeShipmentCount > 0 && (
          <div className="header-progress-chip">
            <span className="chip-label">Toplam:</span>
            <strong>{totalProgress.scanned}/{totalProgress.target}</strong>
          </div>
        )}

        {/* Audio / Haptics Toggle Button */}
        <button
          type="button"
          className="header-icon-btn"
          onClick={onOpenSoundSettings}
          aria-label="Ses ve Titreşim Ayarları"
        >
          {audioSettings.enabled ? <Volume2 size={18} /> : <VolumeX size={18} className="text-muted" />}
        </button>
      </div>
    </header>
  );
}
