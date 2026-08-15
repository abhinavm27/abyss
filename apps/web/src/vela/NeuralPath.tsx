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
        const reveal = active > 0.025 && point.depth <= active;
        const alpha = resolvedRef.current
          ? reveal ? 0.07 : 0.018
          : reveal ? 0.09 + active * 0.16 : 0.025;
        context.beginPath();
        context.moveTo(x, y);
        context.quadraticCurveTo((x + nx) / 2, Math.min(y, ny) - height * 0.04, nx, ny);
        context.strokeStyle = point.lane === 1
          ? `rgba(135, 110, 255, ${alpha})`
          : `rgba(62, 143, 204, ${alpha})`;
        context.lineWidth = reveal ? 0.8 : 0.45;
        context.stroke();

        const pulse = reveal ? 1 + Math.sin(time * (2.5 + voiceEnergy * 7) + index) * (0.28 + voiceEnergy * 0.7) : 0.55;
        context.beginPath();
        context.arc(x, y, (1.1 + point.depth * 2.4) * pulse, 0, Math.PI * 2);
        context.fillStyle = reveal
          ? `rgba(104, 176, 238, ${0.18 + active * 0.38 + voiceEnergy * 0.22})`
          : "rgba(120, 147, 180, 0.045)";
        context.fill();
      });

      const lanes = [-1, -.52, 0, .55, 1];
      const routePoint = (lane: number, t: number) => {
        const y = height * (1.03 - t * .91);
        const fork = Math.sin(Math.PI * Math.min(1, t * 1.18));
        const drift = lane * width * (.055 + fork * .24);
        const bend = Math.sin(t * 8.2 + lane * 1.7) * width * (.009 + Math.abs(lane) * .012);
        return { x: pathX(y) + drift + bend, y };
      };
      const traceRoute = (lane: number, limit: number) => {
        context.beginPath();
        const steps = Math.max(1, Math.floor(80 * limit));
        for (let step = 0; step <= steps; step += 1) {
          const point = routePoint(lane, step / 80);
          if (step === 0) context.moveTo(point.x, point.y);
          else context.lineTo(point.x, point.y);
        }
      };

      lanes.forEach((laneOffset) => {
        traceRoute(laneOffset, 1);
        context.strokeStyle = resolvedRef.current ? "rgba(117,139,166,.035)" : "rgba(105,132,165,.075)";
        context.lineWidth = laneOffset === 0 ? 1 : .7;
        context.setLineDash(Math.abs(laneOffset) === 1 ? [3, 5] : []);
        context.stroke();
      });
      context.setLineDash([]);

      lanes.forEach((laneOffset, lane) => {
        const thresholds = [.18, .31, .05, .43, .56];
        const laneReveal = Math.max(0, Math.min(1, (active - thresholds[lane]) / (1 - thresholds[lane])));
        const winningLane = laneOffset === 0 && resolvedRef.current;
        if (!winningLane && (laneReveal <= 0 || resolvedRef.current)) return;
        traceRoute(laneOffset, winningLane ? 1 : laneReveal);
        context.strokeStyle = winningLane
          ? "rgba(74, 220, 244, .98)"
          : lane % 2 === 0 ? "rgba(91,193,237,.46)" : "rgba(145,119,248,.38)";
        context.lineWidth = winningLane ? 4.2 + voiceEnergy * 2.2 : 1.35 + voiceEnergy * .75;
        context.shadowColor = winningLane ? "rgba(57,205,244,.9)" : "rgba(98,180,230,.22)";
        context.shadowBlur = winningLane ? 22 : 5;
        context.stroke();

        const nodeCount = winningLane ? 8 : Math.floor(laneReveal * 5);
        for (let node = 1; node <= nodeCount; node += 1) {
          const t = node / (nodeCount + 1) * (winningLane ? 1 : laneReveal);
          const point = routePoint(laneOffset, t);
          context.beginPath();
          context.arc(point.x, point.y, winningLane ? 3.2 : 2.1, 0, Math.PI * 2);
          context.fillStyle = "rgba(242,254,255,.96)";
          context.strokeStyle = winningLane ? "rgba(41,183,196,.95)" : "rgba(106,143,220,.62)";
          context.lineWidth = 1.2;
          context.fill();
          context.stroke();
        }
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
