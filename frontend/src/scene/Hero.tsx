import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useState,
  type ErrorInfo,
  type ReactNode,
} from "react";

const HeroScene = lazy(() => import("./HeroScene"));

function canUse3D(): boolean {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return false;
  }

  try {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return false;
    }

    const nav = navigator as Navigator & {
      connection?: { saveData?: boolean };
      deviceMemory?: number;
    };

    if (nav.connection?.saveData) return false;
    if ((nav.hardwareConcurrency ?? 4) <= 2) return false;
    if ((nav.deviceMemory ?? 4) <= 2) return false;

    const canvas = document.createElement("canvas");
    const gl =
      canvas.getContext("webgl2") ??
      canvas.getContext("webgl");

    if (!gl) return false;

    const precision = gl.getShaderPrecisionFormat(
      gl.VERTEX_SHADER,
      gl.HIGH_FLOAT,
    );

    return precision !== null && precision.precision > 0;
  } catch {
    return false;
  }
}

function Fallback() {
  return (
    <svg
      viewBox="0 0 200 200"
      width="100%"
      height="100%"
      role="img"
      aria-label="Stack of coins"
    >
      <defs>
        <linearGradient id="coinTop" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#27c981" />
          <stop offset="100%" stopColor="#087746" />
        </linearGradient>
        <linearGradient id="coinSide" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#146b48" />
          <stop offset="100%" stopColor="#0a3527" />
        </linearGradient>
      </defs>

      <ellipse
        cx="100"
        cy="169"
        rx="68"
        ry="15"
        fill="#000"
        opacity=".2"
      />

      {[0, 1, 2, 3].map((i) => {
        const y = 142 - i * 27;

        return (
          <g key={i}>
            <path
              d={`M 38 ${y} L 38 ${y + 13}
                A 62 20 0 0 0 162 ${y + 13}
                L 162 ${y} A 62 20 0 0 1 38 ${y}`}
              fill="url(#coinSide)"
            />
            <ellipse
              cx="100"
              cy={y}
              rx="62"
              ry="20"
              fill="url(#coinTop)"
              stroke="#52e5a3"
              strokeWidth="1.5"
            />
            <ellipse
              cx="100"
              cy={y}
              rx="44"
              ry="12"
              fill="none"
              stroke="#b0f5d2"
              strokeWidth="1.5"
              opacity=".65"
            />
          </g>
        );
      })}
    </svg>
  );
}

class HeroSceneBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn(
      "3D hero unavailable; using fallback illustration.",
      error,
      info.componentStack,
    );
  }

  render() {
    if (this.state.failed) {
      return <Fallback />;
    }

    return this.props.children;
  }
}

export default function Hero() {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    setEnabled(canUse3D());
  }, []);

  if (!enabled) {
    return <Fallback />;
  }

  return (
    <HeroSceneBoundary>
      <Suspense fallback={<Fallback />}>
        <HeroScene />
      </Suspense>
    </HeroSceneBoundary>
  );
}