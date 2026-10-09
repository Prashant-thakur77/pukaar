import { useMemo } from 'react';
import qrcode from 'qrcode-generator';

/** QR code as inline SVG path (no canvas, crisp at any size). */
export function QRCode({ value, label, size = 176 }: { value: string; label: string; size?: number }) {
  const { path, n } = useMemo(() => {
    const qr = qrcode(0, 'M');
    qr.addData(value);
    qr.make();
    const count = qr.getModuleCount();
    let d = '';
    for (let r = 0; r < count; r++) for (let c = 0; c < count; c++) if (qr.isDark(r, c)) d += `M${c + 2},${r + 2}h1v1h-1z`;
    return { path: d, n: count + 4 };
  }, [value]);
  return (
    <svg className="qr" width={size} height={size} viewBox={`0 0 ${n} ${n}`} role="img" aria-label={label} shapeRendering="crispEdges">
      <rect width={n} height={n} fill="#fff" />
      <path d={path} fill="#0b1026" />
    </svg>
  );
}
