import { QrCode, Layers, SlidersHorizontal, FileSpreadsheet } from 'lucide-react';
import { triggerTapHaptic } from '../audio/audioEngine';

export type MobileTab = 'scan' | 'shipments' | 'setup' | 'manifest';

interface BottomNavProps {
  activeTab: MobileTab;
  onChangeTab: (tab: MobileTab) => void;
  shipmentCount: number;
  unfulfilledCount: number;
}

export default function BottomNav({
  activeTab,
  onChangeTab,
  shipmentCount,
  unfulfilledCount,
}: BottomNavProps) {
  const handleTabClick = (tab: MobileTab) => {
    void triggerTapHaptic();
    onChangeTab(tab);
  };

  return (
    <nav className="bottom-nav">
      <button
        type="button"
        className={`nav-item ${activeTab === 'scan' ? 'active' : ''}`}
        onClick={() => handleTabClick('scan')}
      >
        <div className="nav-icon-wrap">
          <QrCode size={22} />
        </div>
        <span className="nav-label">Okut</span>
      </button>

      <button
        type="button"
        className={`nav-item ${activeTab === 'shipments' ? 'active' : ''}`}
        onClick={() => handleTabClick('shipments')}
      >
        <div className="nav-icon-wrap">
          <Layers size={22} />
          {shipmentCount > 0 && (
            <span className={`nav-badge ${unfulfilledCount === 0 ? 'badge-done' : ''}`}>
              {unfulfilledCount > 0 ? unfulfilledCount : '✓'}
            </span>
          )}
        </div>
        <span className="nav-label">Sevkiyat</span>
      </button>

      <button
        type="button"
        className={`nav-item ${activeTab === 'setup' ? 'active' : ''}`}
        onClick={() => handleTabClick('setup')}
      >
        <div className="nav-icon-wrap">
          <SlidersHorizontal size={22} />
        </div>
        <span className="nav-label">Kurulum</span>
      </button>

      <button
        type="button"
        className={`nav-item ${activeTab === 'manifest' ? 'active' : ''}`}
        onClick={() => handleTabClick('manifest')}
      >
        <div className="nav-icon-wrap">
          <FileSpreadsheet size={22} />
        </div>
        <span className="nav-label">Manifest</span>
      </button>
    </nav>
  );
}
