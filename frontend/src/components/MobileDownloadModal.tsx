import { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';

interface MobileDownloadModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function MobileDownloadModal({ isOpen, onClose }: MobileDownloadModalProps) {
  const [copied, setCopied] = useState<boolean>(false);

  if (!isOpen) return null;

  // Determine current download URL
  const apiBase = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '').replace(/\/api(\/v\d+)?$/i, '');
  const downloadUrl = apiBase ? `${apiBase}/api/download/apk` : `${window.location.origin}/api/download/apk`;
  const mobileWebUrl = window.location.origin;

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
              <span className="modal-subtitle">Android APK & Mobil Web Erişimi</span>
            </div>
          </div>
          <button type="button" className="op-btn danger compact" onClick={onClose}>
            ✕ Kapat
          </button>
        </div>

        <div className="download-modal-body">
          {/* QR Code Container */}
          <div className="qr-code-section">
            <div className="qr-box">
              <QRCodeSVG
                value={downloadUrl}
                size={190}
                level="H"
                includeMargin={true}
                bgColor="#ffffff"
                fgColor="#0f172a"
              />
            </div>
            <span className="qr-hint">Telefon veya el terminali kamerasıyla okutun</span>
          </div>

          {/* Action Buttons */}
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
              <span>{copied ? '✓ İndirme Linki Kopyalandı!' : '📋 İndirme Linkini Kopyala'}</span>
            </button>
          </div>

          {/* Instructions Box */}
          <div className="download-guide-box">
            <h4>📌 Kolay Kurulum Adımları:</h4>
            <ol className="guide-steps">
              <li>
                <strong>QR Kodu Okutun:</strong> Telefon veya el terminalinizin kamerasıyla yukarıdaki QR kodu okutun.
              </li>
              <li>
                <strong>APK'yı İndirin:</strong> Açılan bağlantıdan <code>SevkiyatBul.apk</code> dosyasını cihazınıza indirin.
              </li>
              <li>
                <strong>Yükleyin & Kullanın:</strong> İndirilen dosyaya dokunup <em>"Yükle"</em> seçeneğini onaylayın ve uygulamayı başlatın.
              </li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
}
