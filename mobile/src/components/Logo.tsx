import React from 'react';

export type LogoSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | '2xl' | number;
export type LogoVariant = 'icon' | 'full';

interface LogoProps {
  size?: LogoSize;
  variant?: LogoVariant;
  animated?: boolean;
  className?: string;
  onClick?: () => void;
}

const SIZE_MAP: Record<string, number> = {
  xs: 20,
  sm: 28,
  md: 36,
  lg: 48,
  xl: 68,
  '2xl': 96,
};

export const LogoIcon: React.FC<{ size?: number; className?: string; animated?: boolean }> = ({
  size = 36,
  className = '',
  animated = false,
}) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 512 512"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`app-logo-svg ${animated ? 'logo-pulse-anim' : ''} ${className}`}
      style={{ display: 'inline-block', verticalAlign: 'middle', flexShrink: 0 }}
      aria-label="SevkiyatBul Logo"
    >
      <defs>
        <linearGradient id="sbPrimaryMob" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="50%" stopColor="#2563eb" />
          <stop offset="100%" stopColor="#1d4ed8" />
        </linearGradient>

        <linearGradient id="sbAccentMob" x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#10b981" />
          <stop offset="60%" stopColor="#06b6d4" />
          <stop offset="100%" stopColor="#38bdf8" />
        </linearGradient>

        <linearGradient id="sbBeamMob" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#38bdf8" stopOpacity="0" />
          <stop offset="30%" stopColor="#38bdf8" stopOpacity="0.85" />
          <stop offset="50%" stopColor="#ffffff" stopOpacity="1" />
          <stop offset="70%" stopColor="#10b981" stopOpacity="0.85" />
          <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
        </linearGradient>

        <linearGradient id="sbBoxTopMob" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#1e293b" />
          <stop offset="100%" stopColor="#0f172a" />
        </linearGradient>

        <filter id="sbGlowMob" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="10" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      {/* Hexagonal Isometric Shipping Box */}
      <g>
        {/* Top Face */}
        <path
          d="M256 64 L420 156 L256 248 L92 156 Z"
          fill="url(#sbBoxTopMob)"
          stroke="url(#sbAccentMob)"
          strokeWidth="8"
          strokeLinejoin="round"
        />

        {/* Left Face */}
        <path
          d="M92 156 L256 248 L256 436 L92 344 Z"
          fill="#0f172a"
          stroke="url(#sbPrimaryMob)"
          strokeWidth="8"
          strokeLinejoin="round"
        />

        {/* Right Face */}
        <path
          d="M256 248 L420 156 L420 344 L256 436 Z"
          fill="#131e36"
          stroke="url(#sbAccentMob)"
          strokeWidth="8"
          strokeLinejoin="round"
        />

        {/* Dynamic Stylized FIFO "S" Flow */}
        <path
          d="M370 190 L275 243 L275 320 L350 278"
          stroke="url(#sbAccentMob)"
          strokeWidth="16"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        <path
          d="M162 235 L237 277 L237 355 L142 302"
          stroke="url(#sbPrimaryMob)"
          strokeWidth="16"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Center Target & Sync Diamond */}
        <path
          d="M256 215 L285 245 L256 275 L227 245 Z"
          fill="#38bdf8"
          filter="url(#sbGlowMob)"
        />

        {/* Barcode Lines on Top */}
        <line x1="200" y1="130" x2="230" y2="147" stroke="#38bdf8" strokeWidth="5" strokeLinecap="round" opacity="0.85" />
        <line x1="215" y1="120" x2="260" y2="145" stroke="#38bdf8" strokeWidth="7" strokeLinecap="round" opacity="0.9" />
        <line x1="250" y1="110" x2="280" y2="127" stroke="#10b981" strokeWidth="5" strokeLinecap="round" opacity="0.85" />
        <line x1="280" y1="118" x2="315" y2="138" stroke="#10b981" strokeWidth="6" strokeLinecap="round" opacity="0.9" />

        {/* Laser Scanning Beam */}
        <path
          d="M70 248 Q256 230 442 248"
          stroke="url(#sbBeamMob)"
          strokeWidth="10"
          strokeLinecap="round"
          filter="url(#sbGlowMob)"
        />

        {/* Targeting Corners */}
        <path d="M72 130 L60 136 L60 170" stroke="#38bdf8" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M440 130 L452 136 L452 170" stroke="#38bdf8" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M60 330 L60 360 L75 368" stroke="#38bdf8" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M452 330 L452 360 L437 368" stroke="#10b981" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  );
};

export default function Logo({
  size = 'md',
  variant = 'full',
  animated = false,
  className = '',
  onClick,
}: LogoProps) {
  const pixelSize = typeof size === 'number' ? size : SIZE_MAP[size] || 36;

  if (variant === 'icon') {
    return (
      <div
        className={`app-logo-wrap icon-only ${className}`}
        onClick={onClick}
        style={{ cursor: onClick ? 'pointer' : 'default', display: 'inline-flex', alignItems: 'center' }}
      >
        <LogoIcon size={pixelSize} animated={animated} />
      </div>
    );
  }

  return (
    <div
      className={`app-logo-wrap full-brand ${className}`}
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.55rem',
        cursor: onClick ? 'pointer' : 'default',
        userSelect: 'none',
      }}
    >
      <LogoIcon size={pixelSize} animated={animated} />
      <div className="brand-text-block" style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
          <span
            style={{
              fontWeight: 900,
              fontSize: `${Math.max(13, pixelSize * 0.46)}px`,
              letterSpacing: '0.5px',
              background: 'linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            SEVKİYAT
          </span>
          <span
            style={{
              fontWeight: 900,
              fontSize: `${Math.max(13, pixelSize * 0.46)}px`,
              letterSpacing: '0.5px',
              background: 'linear-gradient(135deg, #38bdf8 0%, #10b981 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            BUL
          </span>
        </div>
        <span
          style={{
            fontSize: `${Math.max(8, pixelSize * 0.22)}px`,
            fontWeight: 700,
            letterSpacing: '0.8px',
            color: '#64748b',
            textTransform: 'uppercase',
          }}
        >
          FIFO Kontrol
        </span>
      </div>
    </div>
  );
}
