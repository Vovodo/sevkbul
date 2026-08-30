import { useState, useEffect, useCallback } from 'react';
import { api, ShipmentProgress, ShipmentTarget, RecentScan, ShipmentManifest, ScanResponse } from './api';
import { useLiveUpdates, WsMessage } from './useLiveUpdates';
import { playMobileSound } from './audio/audioEngine';
import Header from './components/Header';
import BottomNav, { MobileTab } from './components/BottomNav';
import SoundSettingsModal from './components/SoundSettingsModal';
import ScanPage from './pages/ScanPage';
import ShipmentsPage from './pages/ShipmentsPage';
import SetupPage from './pages/SetupPage';
import ManifestPage from './pages/ManifestPage';

export default function App() {
  const [activeTab, setActiveTab] = useState<MobileTab>('scan');
  const [shipments, setShipments] = useState<ShipmentProgress[]>([]);
  const [targets, setTargets] = useState<ShipmentTarget[]>([]);
  const [manifests, setManifests] = useState<ShipmentManifest[]>([]);
  const [recentScans, setRecentScans] = useState<RecentScan[]>([]);
  const [lastScan, setLastScan] = useState<ScanResponse | null>(null);
  const [stockLoaded, setStockLoaded] = useState<boolean>(false);
  const [stockCount, setStockCount] = useState<number>(0);
  const [showSoundModal, setShowSoundModal] = useState<boolean>(false);

  // Initial Data Fetch
  const refreshAllData = useCallback(async () => {
    try {
      const [stats, targetList, shipmentList] = await Promise.all([
        api.getInventoryStats().catch(() => ({ total_labels: 0, total_references: 0 })),
        api.getTargets().catch(() => []),
        api.getShipmentStatus().catch(() => []),
      ]);

      setStockLoaded(stats.total_labels > 0);
      setStockCount(stats.total_labels);
      setTargets(targetList);
      setShipments(shipmentList);

      if (shipmentList.length > 0) {
        api.getManifest().then(setManifests).catch(() => {});
      }
    } catch {
      // ignore on initial offline
    }
  }, []);

  useEffect(() => {
    void refreshAllData();
  }, [refreshAllData]);

  // Live WebSocket Message Handler
  const handleWsMessage = useCallback((msg: WsMessage) => {
    const d = msg.data;

    if (msg.event === 'stock_import') {
      if (d?.total_labels != null) {
        setStockLoaded(d.total_labels > 0);
        setStockCount(d.total_labels);
      }
      return;
    }

    if (msg.event === 'reset') {
      setShipments([]);
      setRecentScans([]);
      setManifests([]);
      setLastScan(null);
      if (d?.targets) {
        setTargets(d.targets);
      }
      return;
    }

    if (d?.shipments) {
      setShipments(d.shipments);
    }

    if (d?.targets) {
      setTargets(d.targets);
    }

    if (msg.event === 'scan' && d?.scan) {
      const scanData = d.scan as ScanResponse;
      setLastScan(scanData);

      // Ses & Titreşim efekti çal
      try {
        if (scanData.is_complete && scanData.success) {
          playMobileSound('completion');
        } else if (scanData.result === 'SEVKİYAT ÜRÜNÜ') {
          playMobileSound('success');
        } else if (scanData.result === 'ZATEN OKUTULDU') {
          playMobileSound('duplicate');
        } else if (scanData.result === 'MİKTAR AŞILDI') {
          playMobileSound('exceeded');
        } else {
          playMobileSound('failure');
        }
      } catch {
        // audio context
      }

      // 3.5 saniye sonra bildirimi kaldır
      setTimeout(() => {
        setLastScan((prev) => (prev?.label === scanData.label ? null : prev));
      }, 3500);

      setRecentScans((prev) => [
        {
          label: scanData.label,
          reference: scanData.reference,
          quantity: scanData.quantity,
          result: scanData.result,
          time: new Date().toLocaleTimeString('tr-TR'),
        },
        ...prev,
      ].slice(0, 40));

      // Refresh manifest in background
      api.getManifest().then(setManifests).catch(() => {});
    }
  }, []);

  const { isConnected } = useLiveUpdates(handleWsMessage);

  const handleReset = async () => {
    await api.resetShipments();
    setShipments([]);
    setRecentScans([]);
    setManifests([]);
    setLastScan(null);
    setActiveTab('setup');
  };

  const handleShipmentsFound = async () => {
    const status = await api.getShipmentStatus();
    setShipments(status);
    setTargets([]);
    setActiveTab('scan');
    api.getManifest().then(setManifests).catch(() => {});
  };

  const totalScanned = shipments.reduce((sum, s) => sum + s.scanned_quantity, 0);
  const totalTarget = shipments.reduce((sum, s) => sum + s.requested_quantity, 0);
  const unfulfilledShipmentsCount = shipments.filter(
    (s) => !s.is_complete && s.scanned_quantity < s.requested_quantity
  ).length;

  return (
    <div className="mobile-app">
      {/* Mobile Top App Bar */}
      <Header
        wsConnected={isConnected}
        activeShipmentCount={shipments.length}
        totalProgress={{ scanned: totalScanned, target: totalTarget }}
        onOpenSoundSettings={() => setShowSoundModal(true)}
      />

      {/* Floating Live Scan Toast when on other tabs */}
      {activeTab !== 'scan' && lastScan && (
        <div
          className={`mobile-floating-toast res-${
            lastScan.result === 'SEVKİYAT ÜRÜNÜ'
              ? 'success'
              : lastScan.result === 'MİKTAR AŞILDI'
              ? 'exceeded'
              : lastScan.result === 'ZATEN OKUTULDU'
              ? 'duplicate'
              : 'failure'
          }`}
          onClick={() => setActiveTab('scan')}
        >
          <div className="toast-tag">{lastScan.result}</div>
          <div className="toast-body">
            <strong>{lastScan.label}</strong>
            {lastScan.reference && <span> • {lastScan.reference} ({lastScan.quantity} Adet)</span>}
          </div>
        </div>
      )}

      {/* Main Page Body */}
      <main className="mobile-content">
        {activeTab === 'scan' && (
          <ScanPage
            shipments={shipments}
            recentScans={recentScans}
            lastScan={lastScan}
            onSetLastScan={setLastScan}
            onRefreshShipments={() => {
              api.getShipmentStatus().then(setShipments).catch(() => {});
            }}
            onNavigateToSetup={() => setActiveTab('setup')}
            onNavigateToShipments={() => setActiveTab('shipments')}
          />
        )}


        {activeTab === 'shipments' && (
          <ShipmentsPage
            shipments={shipments}
            onRefresh={() => {
              api.getShipmentStatus().then(setShipments).catch(() => {});
            }}
            onResetShipments={handleReset}
            onNavigateToManifest={() => setActiveTab('manifest')}
          />
        )}

        {activeTab === 'setup' && (
          <SetupPage
            targets={targets}
            onRefreshTargets={() => {
              api.getTargets().then(setTargets).catch(() => {});
            }}
            onShipmentsFound={handleShipmentsFound}
            stockLoaded={stockLoaded}
            stockCount={stockCount}
          />
        )}

        {activeTab === 'manifest' && (
          <ManifestPage
            manifests={manifests}
            onRefresh={async () => {
              const data = await api.getManifest();
              setManifests(data);
            }}
          />
        )}
      </main>

      {/* Bottom Navigation */}
      <BottomNav
        activeTab={activeTab}
        onChangeTab={setActiveTab}
        shipmentCount={shipments.length}
        unfulfilledCount={unfulfilledShipmentsCount}
      />

      {/* Sound & Haptic Settings Modal */}
      <SoundSettingsModal
        isOpen={showSoundModal}
        onClose={() => setShowSoundModal(false)}
      />
    </div>
  );
}
