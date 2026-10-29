import { Capacitor } from '@capacitor/core';

const PRODUCTION_API = 'https://sevkbulapi.rfqcollector.com';

export function getApiBase(): string {
  let url = (import.meta.env.VITE_API_URL || '').trim();
  if (url) {
    url = url.replace(/\/+$/, '');
    url = url.replace(/\/api(\/v\d+)?$/i, '');
    return url;
  }
  if (Capacitor.isNativePlatform()) {
    return PRODUCTION_API;
  }
  if (typeof window !== 'undefined') {
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
      return '';
    }
  }
  return PRODUCTION_API;
}

export const API_BASE = getApiBase();


async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Bir hata oluştu' }));
    const detail = typeof err.detail === 'string' ? err.detail : 'Bir hata oluştu';
    if (res.status === 404 && detail === 'Not Found') {
      throw new Error('API endpoint bulunamadı.');
    }
    throw new Error(detail);
  }
  return res.json();
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
  group_id?: number;
  reference: string;
  name?: string | null;
  requested_quantity: number;
  pool_quantity: number;
  scanned_quantity: number;
  scanned_label_count?: number;
  remaining_quantity: number;
  progress_percent: number;
  status: string;
  is_complete: boolean;
  stock_note?: string | null;
  short_quantity?: number;
  blocked_label_count?: number;
  unblocked_label_count?: number;
  blocked_quantity?: number;
  unblocked_quantity?: number;
}

export interface ShipmentGroup {
  group_id: number;
  index: number;
  name: string;
  requested_quantity: number;
  scanned_quantity: number;
  remaining_quantity: number;
  progress_percent: number;
  status: string;
  is_complete: boolean;
  created_at?: string | null;
  blocked_label_count?: number;
  unblocked_label_count?: number;
  items: ShipmentProgress[];
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
  hint?: string | null;
  expected_fifo_date?: string | null;
  suggested_shipment?: string | null;
}

export interface RecentScan {
  label: string;
  reference?: string;
  quantity?: number;
  result: string;
  time: string;
}

export interface RecalculateStatus {
  job?: number;
  phase: 'idle' | 'running' | 'done' | 'error';
  percent: number;
  done: number;
  total: number;
  message: string;
  error: string | null;
  updated: number;
}

export interface CandidateLabel {
  label: string;
  quantity: number;
  fifo_time: string;
  blocked?: boolean;
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
  scanned_quantity?: number;
  fifo_date: string;
  fifo_group_date: string;
  status: string;
  is_scanned: boolean;
  outside_fifo?: boolean;
  outside_reason?: 'window' | null;
  has_blocked?: boolean;
  blocked_count?: number;
  scanned_labels?: { label: string; quantity: number; outside_fifo?: boolean; blocked?: boolean }[];
}

export interface InventoryLabelItem {
  id: number;
  label: string;
  reference: string;
  quantity: number;
  fifo_date: string;
  blocked: boolean;
  hidden: boolean;
  scanned: boolean;
}

export interface InventoryListResponse {
  total: number;
  active_count: number;
  hidden_count: number;
  blocked_count: number;
  items: InventoryLabelItem[];
}

export interface ShipmentManifest {
  shipment_id: number;
  group_id?: number;
  group_name?: string | null;
  reference: string;
  requested_quantity: number;
  pool_quantity: number;
  scanned_quantity: number;
  remaining_quantity: number;
  progress_percent: number;
  hourly_fifo: boolean;
  status: string;
  is_complete: boolean;
  blocked_label_count?: number;
  unblocked_label_count?: number;
  blocked_labels?: CandidateLabel[];
  items: ShipmentManifestItem[];
}

export const api = {
  healthCheck: () =>
    request<{ status: string; service: string; version: string; features: string[] }>('/api/health'),

  importStock: async (file: File, replace: boolean = true) => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${API_BASE}/api/inventory/import/stock?replace=${replace}`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Import hatası' }));
      const detail = err.detail || 'Import hatası';
      if (res.status === 404) throw new Error('API endpoint bulunamadı.');
      throw new Error(detail);
    }
    return res.json() as Promise<ImportResult>;
  },

  exportManifestExcelUrl: (groupId?: number | null) =>
    `${API_BASE}/api/shipment/export${groupId != null ? `?group_id=${groupId}` : ''}`,

  getInventoryStats: () =>
    request<{ total_labels: number; total_references: number; blocked_labels?: number; unblocked_labels?: number; hidden_labels?: number }>('/api/inventory/stats'),

  getInventoryLabels: (q: string = '', filterMode: string = 'all', limit: number = 10000) =>
    request<InventoryListResponse>(
      `/api/inventory/labels?q=${encodeURIComponent(q)}&filter_mode=${encodeURIComponent(filterMode)}&limit=${limit}`
    ),

  setInventoryLabelHidden: (labelId: number, hidden: boolean) =>
    request<InventoryLabelItem>(`/api/inventory/labels/${labelId}/hidden`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hidden }),
    }),

  setInventoryLabelsBulkHidden: (labelIds: number[], hidden: boolean) =>
    request<{ updated: number; hidden: boolean }>('/api/inventory/labels/bulk-hidden', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label_ids: labelIds, hidden }),
    }),

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

  clearTargets: () =>
    request<{ ok: boolean }>('/api/shipment/targets', { method: 'DELETE' }),

  deleteTarget: (id: number) =>
    request<{ ok: boolean }>(`/api/shipment/targets/${id}`, { method: 'DELETE' }),

  findShipments: (hourlyFifo: boolean = false) =>
    request<{ shipments: ShipmentProgress[]; errors: { reference: string; error: string }[] }>(
      `/api/shipment/find${hourlyFifo ? '?hourly_fifo=true' : ''}`,
      { method: 'POST' }
    ),

  recalculate: () =>
    request<{ status: string }>('/api/shipment/recalculate', { method: 'POST' }),

  recalculateStatus: () =>
    request<RecalculateStatus>('/api/shipment/recalculate/status'),

  getShipmentStatus: () => request<ShipmentProgress[]>('/api/shipment/status'),

  getGroups: () => request<ShipmentGroup[]>('/api/shipment/groups'),

  getManifest: (opts?: { groupId?: number; shipmentId?: number }) => {
    const params = new URLSearchParams();
    if (opts?.groupId != null) params.set('group_id', String(opts.groupId));
    if (opts?.shipmentId != null) params.set('shipment_id', String(opts.shipmentId));
    const qs = params.toString();
    return request<ShipmentManifest[]>(`/api/shipment/manifest${qs ? `?${qs}` : ''}`);
  },

  getCandidates: (shipmentId: number, fifoGroup: string) =>
    request<{ remaining: number; labels: CandidateLabel[] }>(
      `/api/shipment/${shipmentId}/candidates?fifo_group=${encodeURIComponent(fifoGroup)}`
    ),

  scan: (label: string, shipment_id?: number | null, group_id?: number | null, blocked_only: boolean = false) =>
    request<ScanResponse>('/api/shipment/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        label,
        shipment_id: shipment_id || null,
        group_id: group_id || null,
        blocked_only,
      }),
    }),

  resetShipments: () =>
    request<{ cancelled: number }>('/api/shipment/reset', { method: 'POST' }),

  deleteShipmentGroup: (groupId: number) =>
    request<{ removed_group_id: number; removed: number }>(`/api/shipment/group/${groupId}`, {
      method: 'DELETE',
    }),

  reorderGroups: (groupIds: number[]) =>
    request<ShipmentGroup[]>('/api/shipment/groups/order', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_ids: groupIds }),
    }),

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

  renameGroup: (groupId: number, name: string) =>
    request<ShipmentGroup[]>(`/api/shipment/group/${groupId}/name`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  selectActiveGroup: (groupId: number) =>
    request<{ selected_group_id: number }>(`/api/shipment/active-group/${groupId}`, {
      method: 'POST',
    }),

  getActiveGroup: () =>
    request<{ selected_group_id: number | null }>('/api/shipment/active-group'),
};
