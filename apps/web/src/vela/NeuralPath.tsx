import { useEffect, useRef } from "react";

type Props = {
  progress: number;
  energy?: number;
  resolved?: boolean;
  className?: string;
};

type Point = { x: number; y: number; depth: number; lane: number };

function seeded(index: number) {
  const value = Math.sin(index * 92.173 + 17.71) * 43758.5453;
  return value - Math.floor(value);
}

export function NeuralPath({ progress, energy = 0, resolved = false, className = "" }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const progressRef = useRef(progress);
  const resolvedRef = useRef(resolved);
  const energyRef = useRef(energy);

  useEffect(() => {
    progressRef.current = progress;
    resolvedRef.current = resolved;
    energyRef.current = energy;
  }, [progress, energy, resolved]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    let frame = 0;
    let animation = 0;
    let width = 0;
    let height = 0;
    let points: Point[] = [];

    const makePoints = () => {
      points = Array.from({ length: 92 }, (_, index) => {
        const depth = seeded(index + 8);
        return {
          x: 0.06 + seeded(index + 31) * 0.88,
          y: 0.18 + depth * 0.76,
          depth,
          lane: Math.floor(seeded(index + 77) * 5),
        };
      });
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      canvas.width = width * ratio;
      canvas.height = height * ratio;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      makePoints();
    };

    const pathX = (y: number) => {
      const t = y / Math.max(height, 1);
      return width * (0.5 + Math.sin(t * 8.8 + 0.8) * 0.065 + Math.sin(t * 3.1) * 0.025);
    };

    const draw = () => {
      frame += 1;
      context.clearRect(0, 0, width, height);
      const active = Math.max(0, Math.min(1, progressRef.current));
      const voiceEnergy = Math.max(0, Math.min(1, energyRef.current));
      const time = frame / 75;

      const wash = context.createRadialGradient(width * 0.5, height * 0.8, 0, width * 0.5, height * 0.8, width * 0.48);
      wash.addColorStop(0, `rgba(62, 204, 244, ${0.055 + active * 0.12})`);
      wash.addColorStop(0.5, `rgba(164, 181, 255, ${0.025 + active * 0.055})`);
      wash.addColorStop(1, "rgba(255,255,255,0)");
      context.fillStyle = wash;
      context.fillRect(0, 0, width, height);

      points.forEach((point, index) => {
        const x = point.x * width;
        const y = point.y * height;
        const nearest = points[(index * 7 + 13) % points.length];
        const nx = nearest.x * width;
        const ny = nearest.y * height;
        const reveal = point.depth <= active + 0.12;
        const alpha = reveal ? 0.11 + active * 0.16 : 0.035;
        context.beginPath();
        context.moveTo(x, y);
        context.quadraticCurveTo((x + nx) / 2, Math.min(y, ny) - height * 0.04, nx, ny);
        context.strokeStyle = point.lane === 1
          ? `rgba(135, 110, 255, ${alpha})`
          : `rgba(62, 143, 204, ${alpha})`;
        context.lineWidth = reveal ? 0.8 : 0.45;
        context.stroke();

        const pulse = reveal ? 1 + Math.sin(time * (2.5 + voiceEnergy * 7) + index) * (0.28 + voiceEnergy * 0.7) : 0.7;
        context.beginPath();
        context.arc(x, y, (1.1 + point.depth * 2.4) * pulse, 0, Math.PI * 2);
        context.fillStyle = reveal
          ? `rgba(104, 176, 238, ${0.18 + active * 0.38 + voiceEnergy * 0.22})`
          : "rgba(120, 147, 180, 0.09)";
        context.fill();
      });

      const lanes = [-0.25, -0.13, 0, 0.14, 0.27];
      lanes.forEach((offset, lane) => {
        context.beginPath();
        for (let step = 0; step <= 70; step += 1) {
          const t = step / 70;
          const y = height * (0.14 + t * 0.92);
          const spread = width * (0.4 - t * 0.34);
          const x = pathX(y) + offset * spread + Math.sin(t * 9 + lane) * width * 0.01;
          if (step === 0) context.moveTo(x, y);
          else context.lineTo(x, y);
        }
        const laneActive = active >= lane * 0.17;
        context.strokeStyle = lane === 2 && resolvedRef.current
          ? "rgba(95, 224, 247, 0.93)"
          : laneActive
            ? lane % 2 === 0 ? "rgba(89, 201, 245, 0.36)" : "rgba(137, 112, 255, 0.28)"
            : "rgba(122, 143, 170, 0.07)";
        context.lineWidth = lane === 2 && resolvedRef.current ? 3.4 + voiceEnergy * 2.2 : laneActive ? 1.25 + voiceEnergy * 0.8 : 0.65;
        context.shadowColor = lane === 2 && resolvedRef.current ? "rgba(63, 205, 247, 0.75)" : "transparent";
        context.shadowBlur = lane === 2 && resolvedRef.current ? 18 : 0;
        context.stroke();
      });
      context.shadowBlur = 0;

      if (resolvedRef.current) {
        for (let index = 0; index < 8; index += 1) {
          const t = (index + 1) / 9;
          const y = height * (0.19 + t * 0.78);
          const x = pathX(y);
          const glow = 3 + Math.sin(time * 3 + index) * 1.5;
          context.beginPath();
          context.arc(x, y, glow, 0, Math.PI * 2);
          context.fillStyle = "rgba(236, 254, 255, 0.98)";
          context.shadowColor = "rgba(72, 216, 247, 0.95)";
          context.shadowBlur = 15;
          context.fill();
        }
        context.shadowBlur = 0;
      }

      animation = window.requestAnimationFrame(draw);
    };

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();
    draw();
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(animation);
    };
  }, []);

  return <canvas ref={canvasRef} className={`vela-network ${className}`} aria-hidden />;
}
