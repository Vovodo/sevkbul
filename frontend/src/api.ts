const API_BASE = import.meta.env.VITE_API_URL || '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Bir hata oluştu' }));
    const detail = typeof err.detail === 'string' ? err.detail : 'Bir hata oluştu';
    if (res.status === 404 && detail === 'Not Found') {
      throw new Error('API endpoint bulunamadı. Backend penceresini kapatıp start.cmd ile yeniden başlatın.');
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
  reference: string;
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

export const api = {
  importStock: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${API_BASE}/api/inventory/import/stock`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Import hatası' }));
      const detail = err.detail || 'Import hatası';
      if (res.status === 404) throw new Error('API endpoint bulunamadı. Backend\'i yeniden başlatın.');
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
      if (res.status === 404) throw new Error('API endpoint bulunamadı. Backend\'i yeniden başlatın.');
      throw new Error(detail);
    }
    return res.json() as Promise<{ targets: ShipmentTarget[]; successful: number }>;
  },

  findShipments: () =>
    request<{ shipments: ShipmentProgress[]; errors: { reference: string; error: string }[] }>(
      '/api/shipment/find',
      { method: 'POST' }
    ),

  getShipmentStatus: () => request<ShipmentProgress[]>('/api/shipment/status'),

  scan: (label: string) =>
    request<ScanResponse>('/api/shipment/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label }),
    }),

  resetShipments: () =>
    request<{ cancelled: number }>('/api/shipment/reset', { method: 'POST' }),

  getScannedLabels: (shipmentId: number) =>
    request<ScannedLabel[]>(`/api/shipment/${shipmentId}/scanned`),

  undoScan: (shipmentId: number, label: string) =>
    request<ShipmentProgress>(`/api/shipment/${shipmentId}/scans/${encodeURIComponent(label)}`, {
      method: 'DELETE',
    }),
};
