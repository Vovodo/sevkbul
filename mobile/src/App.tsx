import { useState, useEffect, useCallback } from 'react';
import { api, ShipmentGroup, ShipmentTarget, RecentScan, ShipmentManifest, ScanResponse } from './api';
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
  const [groups, setGroups] = useState<ShipmentGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [targets, setTargets] = useState<ShipmentTarget[]>([]);
  const [manifests, setManifests] = useState<ShipmentManifest[]>([]);
  const [recentScans, setRecentScans] = useState<RecentScan[]>([]);
  const [lastScan, setLastScan] = useState<ScanResponse | null>(null);
  const [stockLoaded, setStockLoaded] = useState<boolean>(false);
  const [stockCount, setStockCount] = useState<number>(0);
  const [showSoundModal, setShowSoundModal] = useState<boolean>(false);

  // Okutma bildirimi banner'ını webdeki gibi 3.5 saniye sonra otomatik kaldır
  useEffect(() => {
    if (!lastScan) return;
    const timer = setTimeout(() => {
      setLastScan(null);
    }, 3500);
    return () => clearTimeout(timer);
  }, [lastScan]);

  // Aktif seçili sevkiyat grubunu otomatik belirle
  useEffect(() => {
    if (groups.length > 0) {
      if (selectedGroupId == null || !groups.some((g) => g.group_id === selectedGroupId)) {
        const firstIncomplete =
          groups.find((g) => !g.is_complete && g.scanned_quantity < g.requested_quantity) || groups[0];
        setSelectedGroupId(firstIncomplete.group_id);
      }
    } else {
      setSelectedGroupId(null);
    }
  }, [groups, selectedGroupId]);

  // Initial Data Fetch
  const refreshAllData = useCallback(async () => {
    try {
      const [stats, targetList, groupList, activeGroup] = await Promise.all([
        api.getInventoryStats().catch(() => ({ total_labels: 0, total_references: 0 })),
        api.getTargets().catch(() => []),
        api.getGroups().catch(() => []),
        api.getActiveGroup().catch(() => ({ selected_group_id: null })),
      ]);

      setStockLoaded(stats.total_labels > 0);
      setStockCount(stats.total_labels);
      setTargets(targetList);
      setGroups(groupList);
      if (activeGroup.selected_group_id != null) {
        setSelectedGroupId(activeGroup.selected_group_id);
      }

      if (groupList.length > 0) {
        api.getManifest().then(setManifests).catch(() => {});
      }
    } catch {
      // ignore on initial offline
    }
  }, []);

  useEffect(() => {
    void refreshAllData();
  }, [refreshAllData]);

  const handleSelectGroup = useCallback((gid: number) => {
    setSelectedGroupId(gid);
    api.selectActiveGroup(gid).catch(() => {});
  }, []);

  // Live WebSocket Message Handler
  const handleWsMessage = useCallback((msg: WsMessage) => {
    const d = msg.data;

    if (d?.selected_group_id !== undefined) {
      setSelectedGroupId(d.selected_group_id);
    }

    if (msg.event === 'stock_import') {
      if (d?.total_labels != null) {
        setStockLoaded(d.total_labels > 0);
        setStockCount(d.total_labels);
      }
      return;
    }

    if (msg.event === 'reset') {
      setGroups([]);
      setSelectedGroupId(null);
      setRecentScans([]);
      setManifests([]);
      setLastScan(null);
      if (d?.targets) {
        setTargets(d.targets);
      }
      return;
    }

    if (d?.groups) {
      setGroups(d.groups);
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
    setGroups([]);
    setRecentScans([]);
    setManifests([]);
    setLastScan(null);
    setActiveTab('setup');
  };

  const handleShipmentsFound = async () => {
    const groupList = await api.getGroups();
    setGroups(groupList);
    setTargets([]);
    setActiveTab('scan');
    api.getManifest().then(setManifests).catch(() => {});
  };

  const totalScanned = groups.reduce((sum, g) => sum + g.scanned_quantity, 0);
  const totalTarget = groups.reduce((sum, g) => sum + g.requested_quantity, 0);
  const unfulfilledGroupsCount = groups.filter(
    (g) => !g.is_complete && g.scanned_quantity < g.requested_quantity
  ).length;

  return (
    <div className="mobile-app">
      {/* Mobile Top App Bar */}
      <Header
        wsConnected={isConnected}
        activeShipmentCount={groups.length}
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
            groups={groups}
            selectedGroupId={selectedGroupId}
            onSelectGroup={handleSelectGroup}
            recentScans={recentScans}
            lastScan={lastScan}
            onSetLastScan={setLastScan}
            onRefreshGroups={() => {
              api.getGroups().then(setGroups).catch(() => {});
            }}
            onNavigateToSetup={() => setActiveTab('setup')}
            onNavigateToShipments={() => setActiveTab('shipments')}
          />
        )}

        {activeTab === 'shipments' && (
          <ShipmentsPage
            groups={groups}
            selectedGroupId={selectedGroupId}
            onSelectGroup={(gid) => {
              handleSelectGroup(gid);
              setActiveTab('scan');
            }}
            onRefresh={() => {
              api.getGroups().then(setGroups).catch(() => {});
            }}
            onResetShipments={handleReset}
            onNavigateToManifest={() => setActiveTab('manifest')}
            onNavigateToSetup={() => setActiveTab('setup')}
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
        shipmentCount={groups.length}
        unfulfilledCount={unfulfilledGroupsCount}
      />

      {/* Sound & Haptic Settings Modal */}
      <SoundSettingsModal
        isOpen={showSoundModal}
        onClose={() => setShowSoundModal(false)}
      />
    </div>
  );
}
