import { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';

interface MobileDownloadModalProps {
  isOpen: boolean;
  onClose: () => void;
}

// APK indirme URL'ini belirle:
// Coolify'da VITE_API_URL build arg olarak verilmişse onu kullan,
// verilmemişse aynı origin üzerinden /api/download/apk'ya git.
function getDownloadUrl(): string {
  const raw = (import.meta.env.VITE_API_URL || '').trim();
  if (raw) {
    // Trailing slash ve /api suffix temizle
    const base = raw.replace(/\/+$/, '').replace(/\/api(\/v\d+)?$/i, '');
    return `${base}/api/download/apk`;
  }
  // Fallback: aynı origin (nginx reverse proxy üzerinden çalışır)
  return `${window.location.origin}/api/download/apk`;
}

export default function MobileDownloadModal({ isOpen, onClose }: MobileDownloadModalProps) {
  const [copied, setCopied] = useState<boolean>(false);

  if (!isOpen) return null;

  const downloadUrl = getDownloadUrl();

  const handleCopy = () => {
    navigator.clipboard.writeText(downloadUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  };

  return (
    <div className="manifest-overlay" onClick={onClose}>
      <div className="mobile-download-modal" onClick={(e) => e.stopPropagation()}>
        <div className="download-modal-header">
          <div className="download-modal-title">
            <span className="modal-icon">📱</span>
            <div>
              <h3>SevkiyatBul Mobil Uygulaması</h3>
              <span className="modal-subtitle">Android APK İndir</span>
            </div>
          </div>
          <button type="button" className="op-btn danger compact" onClick={onClose}>
            ✕ Kapat
          </button>
        </div>

        <div className="download-modal-body">
          {/* QR Code */}
          <div className="qr-code-section">
            <div className="qr-box">
              <QRCodeSVG
                value={downloadUrl}
                size={200}
                level="H"
                includeMargin={true}
                bgColor="#ffffff"
                fgColor="#0f172a"
              />
            </div>
            <span className="qr-hint">Telefon kamerasıyla okutun — doğrudan APK indirir</span>
          </div>

          {/* Butonlar */}
          <div className="download-actions-grid">
            <a
              href={downloadUrl}
              download="SevkiyatBul.apk"
              className="op-btn primary large download-apk-btn"
              target="_blank"
              rel="noreferrer"
            >
              <span>⬇️ Android APK İndir</span>
            </a>

            <button type="button" className="op-btn secondary" onClick={handleCopy}>
              <span>{copied ? '✓ Link Kopyalandı!' : '📋 İndirme Linkini Kopyala'}</span>
            </button>
          </div>

          {/* URL göster */}
          <div className="download-guide-box">
            <h4>📌 Kurulum Adımları:</h4>
            <ol className="guide-steps">
              <li>
                <strong>QR Kodu Okutun:</strong> Telefonunuzun kamerasıyla yukarıdaki QR kodu tarayın.
              </li>
              <li>
                <strong>APK'yı İndirin:</strong> Açılan bağlantıdan <code>SevkiyatBul.apk</code> dosyasını indirin.
              </li>
              <li>
                <strong>İzin Verin ve Yükleyin:</strong> Telefonda "Bilinmeyen kaynaklardan yükle" iznini onaylayın, ardından <em>"Yükle"</em> deyin.
              </li>
            </ol>
            <p style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: '#94a3b8', wordBreak: 'break-all' }}>
              İndirme linki: <a href={downloadUrl} target="_blank" rel="noreferrer" style={{ color: '#93c5fd' }}>{downloadUrl}</a>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
