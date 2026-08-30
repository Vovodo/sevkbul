import { Capacitor } from '@capacitor/core';

const PRODUCTION_API = 'https://sevkbulapi.rfqcollector.com';

export function getApiBase(): string {
  let url = (import.meta.env.VITE_API_URL || '').trim();
  if (url) {
    url = url.replace(/\/+$/, '');
    url = url.replace(/\/api(\/v\d+)?$/i, '');
    return url;
  }
  // VITE_API_URL verilmemişse (local dev dışında):
  // Native Android'de Capacitor WebView'i localhost olarak görür — production backend kullan
  // Web tarayıcısında mobile servis URL'i backend değildir — production backend kullan
  if (Capacitor.isNativePlatform()) {
    return PRODUCTION_API;
  }
  // Yerel geliştirme ortamı: vite proxy üzerinden erişim (boş string → relative URL)
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    return '';
  }
  // Coolify/production mobile servisinde VITE_API_URL girilmemişse hardcode backend kullan
  return PRODUCTION_API;
}

export const API_BASE = getApiBase();

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const fullUrl = `${API_BASE}${path}`;
  try {
    const res = await fetch(fullUrl, options);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Sunucu hatası oluştu' }));
      const detail = typeof err.detail === 'string' ? err.detail : 'İşlem başarısız oldu';
      if (res.status === 404 && detail === 'Not Found') {
        throw new Error('API endpoint bulunamadı.');
      }
      throw new Error(detail);
    }
    return res.json();
  } catch (error: unknown) {
    if (error instanceof Error) {
      if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
        throw new Error('Sunucuya bağlanılamadı. İnternet bağlantınızı veya sunucu durumunu kontrol edin.');
      }
      throw error;
    }
    throw new Error('Bilinmeyen bir hata oluştu');
  }
}

export interface ImportResult {
  total_rows: number;
  successful: number;
  error_count: number;
  duplicate_count: number;
  invalid_label_count: number;
  invalid_reference_count: number;
  invalid_quantity_count: number;
  invalid_fifo_date_count: number;
  errors: { row: number; reason: string }[];
  duplicate_labels: string[];
  missing_columns: string[];
  preview_rows: { label: string; reference: string; quantity: number; fifo_date: string }[];
}

export interface ShipmentTarget {
  id: number;
  reference: string;
  target_quantity: number;
}

export interface ShipmentProgress {
  shipment_id: number;
  reference: string;
  name?: string | null;
  requested_quantity: number;
  pool_quantity: number;
  scanned_quantity: number;
  remaining_quantity: number;
  progress_percent: number;
  status: string;
  is_complete: boolean;
}

export interface ScanResponse {
  result: string;
  label: string;
  reference?: string;
  quantity?: number;
  scanned_quantity?: number;
  remaining_quantity?: number;
  progress_percent: number;
  is_complete: boolean;
  shipment_id?: number;
  fifo_date?: string;
  success: boolean;
  already_scanned: boolean;
}

export interface RecentScan {
  label: string;
  reference?: string;
  quantity?: number;
  result: string;
  time: string;
}

export interface ScannedLabel {
  label: string;
  quantity: number;
  fifo_date: string;
  scanned_at: string | null;
}

export interface ShipmentManifestItem {
  label: string;
  reference: string;
  quantity: number;
  fifo_date: string;
  fifo_group_date: string;
  status: string;
  is_scanned: boolean;
}

export interface ShipmentManifest {
  shipment_id: number;
  reference: string;
  requested_quantity: number;
  pool_quantity: number;
  scanned_quantity: number;
  remaining_quantity: number;
  progress_percent: number;
  hourly_fifo: boolean;
  status: string;
  is_complete: boolean;
  items: ShipmentManifestItem[];
}

export const api = {
  healthCheck: () =>
    request<{ status: string; service: string; version: string; features: string[] }>('/api/health'),

  importStock: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${API_BASE}/api/inventory/import/stock`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Import hatası' }));
      const detail = err.detail || 'Import hatası';
      if (res.status === 404) throw new Error('API endpoint bulunamadı.');
      throw new Error(detail);
    }
    return res.json() as Promise<ImportResult>;
  },

  getInventoryStats: () => request<{ total_labels: number; total_references: number }>('/api/inventory/stats'),

  getTargets: () => request<ShipmentTarget[]>('/api/shipment/targets'),

  addTarget: (reference: string, target_quantity: number) =>
    request<ShipmentTarget>('/api/shipment/targets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reference, target_quantity }),
    }),

  importTargetsExcel: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${API_BASE}/api/shipment/targets/import`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Import hatası' }));
      const detail = err.detail || 'Import hatası';
      if (res.status === 404) throw new Error('API endpoint bulunamadı.');
      throw new Error(detail);
    }
    return res.json() as Promise<{ targets: ShipmentTarget[]; successful: number }>;
  },

  findShipments: (hourlyFifo: boolean = false) =>
    request<{ shipments: ShipmentProgress[]; errors: { reference: string; error: string }[] }>(
      `/api/shipment/find${hourlyFifo ? '?hourly_fifo=true' : ''}`,
      { method: 'POST' }
    ),

  getShipmentStatus: () => request<ShipmentProgress[]>('/api/shipment/status'),

  getManifest: () => request<ShipmentManifest[]>('/api/shipment/manifest'),

  scan: (label: string, shipment_id?: number | null) =>
    request<ScanResponse>('/api/shipment/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, shipment_id: shipment_id || null }),
    }),

  resetShipments: () =>
    request<{ cancelled: number }>('/api/shipment/reset', { method: 'POST' }),

  getScannedLabels: (shipmentId: number) =>
    request<ScannedLabel[]>(`/api/shipment/${shipmentId}/scanned`),

  undoScan: (shipmentId: number, label: string) =>
    request<ShipmentProgress>(`/api/shipment/${shipmentId}/scans/${encodeURIComponent(label)}`, {
      method: 'DELETE',
    }),

  renameShipment: (shipmentId: number, name: string) =>
    request<ShipmentProgress>(`/api/shipment/${shipmentId}/name`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
};
