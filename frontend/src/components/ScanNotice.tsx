import type { LucideIcon } from 'lucide-react';
import { Ban, CircleX, CircleCheck, Radio, Repeat, SearchX } from 'lucide-react';
import type { ScanResponse } from '../api';

export type ScanTone = 'ok' | 'dup' | 'over' | 'miss' | 'out';

export function scanPresentation(result: string): {
  tone: ScanTone;
  title: string;
  hint: string;
  Icon: LucideIcon;
} {
  switch (result) {
    case 'SEVKİYAT ÜRÜNÜ':
      return {
        tone: 'ok',
        title: 'Kabul edildi',
        hint: 'Etiket bu sevkiyatın FIFO tarihine uyuyor.',
        Icon: CircleCheck,
      };
    case 'ZATEN OKUTULDU':
      return {
        tone: 'dup',
        title: 'Tekrar okutma',
        hint: 'Bu etiket daha önce okutulmuş.',
        Icon: Repeat,
      };
    case 'MİKTAR AŞILDI':
      return {
        tone: 'over',
        title: 'Miktar aşıldı',
        hint: 'Bu tarihin kotası doldu.',
        Icon: Ban,
      };
    case 'ETİKET BULUNAMADI':
      return {
        tone: 'miss',
        title: 'Etiket bulunamadı',
        hint: 'Stok listesinde bu barkod yok.',
        Icon: SearchX,
      };
    default:
      return {
        tone: 'out',
        title: 'Sevkiyat dışı',
        hint: 'Bu FIFO tarihi seçili sevkiyatta yok.',
        Icon: CircleX,
      };
  }
}

export function ScanMark({ result, size = 14 }: { result: string; size?: number }) {
  const { tone, Icon } = scanPresentation(result);
  return (
    <span className={`scan-mark tone-${tone}`} aria-hidden>
      <Icon size={size} strokeWidth={2.4} />
    </span>
  );
}

export function ScanNotice({
  scan,
  size = 'dock',
  noticeKey,
  leaving = false,
}: {
  scan: ScanResponse | null;
  size?: 'dock' | 'stage';
  noticeKey?: number;
  leaving?: boolean;
}) {
  if (!scan) {
    return (
      <div className={`scan-notice is-waiting size-${size}`}>
        <div className="wait-radar" aria-hidden>
          <span className="wait-ring r1" />
          <span className="wait-ring r2" />
          <span className="wait-ring r3" />
          <span className="wait-sweep" />
          <span className="wait-core">
            <Radio size={size === 'stage' ? 42 : 22} strokeWidth={1.75} />
          </span>
        </div>
        <div className="scan-notice-copy">
          <div className="scan-notice-kicker">Hazır</div>
          <div className="scan-notice-title">Okutma bekleniyor</div>
          <div className="scan-notice-hint">
            {size === 'stage'
              ? 'Etiket okutulduğunda sonuç 3 saniye görünür.'
              : 'Sonuç 3 saniye görünür. Kayıt alttaki listede durur.'}
          </div>
        </div>
      </div>
    );
  }

  const view = scanPresentation(scan.result);
  const Icon = view.Icon;
  return (
    <div key={noticeKey} className={`scan-notice is-result tone-${view.tone} size-${size}${leaving ? ' is-leaving' : ''}`} role="status">
      <div className={`scan-notice-icon tone-${view.tone}`} aria-hidden>
        <Icon size={size === 'stage' ? 72 : 32} strokeWidth={1.75} />
      </div>
      <div className="scan-notice-copy">
        <div className="scan-notice-kicker">{scan.result}</div>
        <div className="scan-notice-title">{view.title}</div>
        <div className="scan-notice-hint">{view.hint}</div>
        <div className="scan-notice-meta">
          <span><em>Etiket</em> {scan.label}</span>
          {scan.reference && <span><em>Referans</em> {scan.reference}</span>}
          {scan.quantity != null && <span><em>Miktar</em> {scan.quantity}</span>}
          {scan.fifo_date && <span><em>FIFO</em> {scan.fifo_date}</span>}
        </div>
      </div>
    </div>
  );
}
