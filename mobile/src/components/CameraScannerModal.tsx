import { useEffect, useRef, useState } from 'react';
import { Html5Qrcode, Html5QrcodeSupportedFormats } from 'html5-qrcode';
import { X, Camera, RefreshCw } from 'lucide-react';
import { triggerTapHaptic } from '../audio/audioEngine';

interface CameraScannerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onScanResult: (text: string) => void;
}

export default function CameraScannerModal({
  isOpen,
  onClose,
  onScanResult,
}: CameraScannerModalProps) {
  const [cameras, setCameras] = useState<{ id: string; label: string }[]>([]);
  const [activeCameraId, setActiveCameraId] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [isInitializing, setIsInitializing] = useState<boolean>(true);
  const scannerRef = useRef<Html5Qrcode | null>(null);
  const isRunningRef = useRef<boolean>(false);

  useEffect(() => {
    if (!isOpen) return;

    let mounted = true;
    setIsInitializing(true);
    setError('');

    Html5Qrcode.getCameras()
      .then((devices) => {
        if (!mounted) return;
        if (devices && devices.length > 0) {
          setCameras(devices);
          // Prefer back/environment camera
          const backCam = devices.find(d => /back|rear|environment|ark/i.test(d.label)) || devices[0];
          setActiveCameraId(backCam.id);
          startScanner(backCam.id);
        } else {
          setError('Kamera bulunamadı. Lütfen kamera izni verdiğinizden emin olun.');
          setIsInitializing(false);
        }
      })
      .catch((err) => {
        if (!mounted) return;
        setError(`Kamera erişim hatası: ${err instanceof Error ? err.message : String(err)}`);
        setIsInitializing(false);
      });

    return () => {
      mounted = false;
      stopScanner();
    };
  }, [isOpen]);

  const startScanner = async (cameraId: string) => {
    try {
      if (isRunningRef.current && scannerRef.current) {
        await scannerRef.current.stop();
        isRunningRef.current = false;
      }

      const html5QrCode = new Html5Qrcode('camera-reader-region', {
        formatsToSupport: [
          Html5QrcodeSupportedFormats.QR_CODE,
          Html5QrcodeSupportedFormats.CODE_128,
          Html5QrcodeSupportedFormats.CODE_39,
          Html5QrcodeSupportedFormats.EAN_13,
          Html5QrcodeSupportedFormats.EAN_8,
          Html5QrcodeSupportedFormats.DATA_MATRIX,
        ],
        verbose: false,
      });

      scannerRef.current = html5QrCode;

      await html5QrCode.start(
        cameraId,
        {
          fps: 15,
          qrbox: { width: 250, height: 180 },
          aspectRatio: 1.0,
        },
        (decodedText) => {
          void triggerTapHaptic();
          onScanResult(decodedText);
          onClose();
        },
        () => {
          // ignore frame scan misses
        }
      );

      isRunningRef.current = true;
      setIsInitializing(false);
    } catch (err) {
      setError(`Kamera başlatılamadı: ${err instanceof Error ? err.message : String(err)}`);
      setIsInitializing(false);
    }
  };

  const stopScanner = async () => {
    if (scannerRef.current && isRunningRef.current) {
      try {
        await scannerRef.current.stop();
        scannerRef.current.clear();
      } catch {
        // ignore
      }
      isRunningRef.current = false;
      scannerRef.current = null;
    }
  };

  const switchCamera = () => {
    if (cameras.length <= 1) return;
    const currentIndex = cameras.findIndex(c => c.id === activeCameraId);
    const nextIndex = (currentIndex + 1) % cameras.length;
    const nextCamera = cameras[nextIndex];
    setActiveCameraId(nextCamera.id);
    void startScanner(nextCamera.id);
  };

  if (!isOpen) return null;

  return (
    <div className="camera-modal-overlay">
      <div className="camera-modal-content">
        <div className="camera-modal-header">
          <div className="camera-header-title">
            <Camera size={18} />
            <span>Barkod / QR Kamera Okuyucu</span>
          </div>
          <div className="camera-header-actions">
            {cameras.length > 1 && (
              <button type="button" className="camera-icon-btn" onClick={switchCamera} title="Kamera Değiştir">
                <RefreshCw size={18} />
              </button>
            )}
            <button type="button" className="camera-icon-btn close-btn" onClick={onClose} aria-label="Kapat">
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="camera-viewport-wrap">
          <div id="camera-reader-region" className="camera-scanner-viewport" />
          {isInitializing && (
            <div className="camera-loading-overlay">
              <div className="spinner" />
              <span>Kamera başlatılıyor...</span>
            </div>
          )}
          {error && (
            <div className="camera-error-overlay">
              <p>{error}</p>
              <button type="button" className="mobile-btn secondary" onClick={onClose}>
                Geri Dön
              </button>
            </div>
          )}
          <div className="scanner-crosshair-guide">
            <div className="crosshair-box">
              <div className="corner top-left" />
              <div className="corner top-right" />
              <div className="corner bottom-left" />
              <div className="corner bottom-right" />
              <div className="laser-line" />
            </div>
            <p className="scanner-instruction">Barkod veya QR kodu kırmızı kılavuz çizgisine ortalayın</p>
          </div>
        </div>
      </div>
    </div>
  );
}
