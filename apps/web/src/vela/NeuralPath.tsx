import type { CSSProperties } from "react";

type Props = {
  progress: number;
  energy?: number;
  resolved?: boolean;
  className?: string;
};

const routes = [
  "M500 735 C478 672 548 620 516 558 C486 500 552 456 523 397 C495 338 554 292 519 235 C492 190 526 137 501 75",
  "M500 735 C444 661 348 665 294 592 C245 526 322 475 266 410 C211 347 271 286 222 222 C180 168 209 119 174 72",
  "M500 735 C421 677 310 703 224 637 C144 577 214 511 148 455 C91 406 156 342 105 291 C70 256 92 185 72 133",
  "M500 735 C548 666 648 671 702 600 C753 534 681 481 742 414 C798 352 744 295 797 231 C842 176 813 119 852 75",
  "M500 735 C588 683 690 712 780 646 C855 591 790 530 856 469 C911 418 850 355 903 302 C943 261 922 197 949 145",
  "M500 735 C466 674 420 645 438 582 C454 528 397 488 421 432 C447 373 396 327 432 270 C461 224 426 164 454 111",
  "M500 735 C535 678 583 645 567 582 C551 525 607 486 582 429 C557 371 611 326 575 269 C548 226 582 163 552 109",
] as const;

const crossLinks = [
  "M148 455 C242 432 329 445 421 432",
  "M266 410 C350 386 435 404 523 397",
  "M421 432 C470 448 533 445 582 429",
  "M523 397 C604 382 667 394 742 414",
  "M222 222 C306 244 355 272 432 270",
  "M432 270 C478 251 527 250 575 269",
  "M575 269 C653 249 718 244 797 231",
  "M72 133 C205 150 325 135 454 111",
  "M552 109 C685 128 814 120 949 145",
] as const;

const feederPaths = [
  "M500 735 C430 704 360 688 286 642 C222 602 187 553 118 526",
  "M500 735 C410 731 326 705 241 673 C164 644 113 603 47 579",
  "M500 735 C455 670 373 622 306 582 C237 541 193 500 123 478",
  "M500 735 C476 654 422 595 355 548 C291 503 244 468 175 444",
  "M500 735 C570 704 640 688 714 642 C778 602 813 553 882 526",
  "M500 735 C590 731 674 705 759 673 C836 644 887 603 953 579",
  "M500 735 C545 670 627 622 694 582 C763 541 807 500 877 478",
  "M500 735 C524 654 578 595 645 548 C709 503 756 468 825 444",
  "M438 582 C362 570 292 548 224 520",
  "M567 582 C643 570 713 548 780 520",
  "M421 432 C343 430 276 410 207 382",
  "M582 429 C660 429 728 408 795 380",
] as const;

const nodes = [
  [500, 735], [516, 558], [523, 397], [519, 235], [501, 75],
  [294, 592], [266, 410], [222, 222], [174, 72],
  [224, 637], [148, 455], [105, 291], [72, 133],
  [702, 600], [742, 414], [797, 231], [852, 75],
  [780, 646], [856, 469], [903, 302], [949, 145],
  [438, 582], [421, 432], [432, 270], [454, 111],
  [567, 582], [582, 429], [575, 269], [552, 109],
] as const;

const thresholds = [.03, .16, .35, .24, .48, .1, .12];

export function NeuralPath({ progress, energy = 0, resolved = false, className = "" }: Props) {
  const active = Math.max(0, Math.min(1, progress));
  const activity = Math.max(0, Math.min(1, energy));
  const style = { "--vela-energy": activity } as CSSProperties;

  return (
    <svg className={`vela-network vela-route-map ${resolved ? "is-resolved" : ""} ${className}`} style={style} viewBox="0 0 1000 760" preserveAspectRatio="xMidYMax slice" aria-hidden>
      <defs>
        <linearGradient id="vela-route-cyan" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#65e5fb" />
          <stop offset=".52" stopColor="#36cce9" />
          <stop offset="1" stopColor="#21b99e" />
        </linearGradient>
        <linearGradient id="vela-route-blue" x1="0" y1="1" x2="0" y2="0"><stop stopColor="#65c9ed" /><stop offset="1" stopColor="#8d83ed" /></linearGradient>
        <radialGradient id="vela-route-wash"><stop stopColor="#62dcf5" stopOpacity=".2" /><stop offset="1" stopColor="#fff" stopOpacity="0" /></radialGradient>
        <filter id="vela-route-glow" x="-80%" y="-30%" width="260%" height="160%"><feGaussianBlur stdDeviation="9" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        <filter id="vela-node-glow" x="-300%" y="-300%" width="700%" height="700%"><feGaussianBlur stdDeviation="4" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>

      <g className="vela-route-world" transform="translate(0 225) scale(1 .7)">
        <ellipse className="vela-route-wash" cx="500" cy="650" rx="410" ry="250" fill="url(#vela-route-wash)" />
        <g className="vela-route-feeders">{feederPaths.map((path) => <path d={path} key={path} />)}</g>
        <g className="vela-route-crosslinks">{crossLinks.map((path) => <path d={path} key={path} />)}</g>
        <g className="vela-route-bases">{routes.map((path, index) => <path className={index === 0 ? "is-primary" : ""} d={path} key={path} pathLength="1" />)}</g>

        <g className="vela-route-progress">
          {routes.map((path, index) => {
            const reveal = resolved ? index === 0 ? 1 : 0 : Math.max(0, Math.min(1, (active - thresholds[index]) / (1 - thresholds[index])));
            return <path className={`${index === 0 ? "is-primary" : ""} route-${index}`} d={path} key={path} pathLength="1" style={{ strokeDashoffset: 1 - reveal }} />;
          })}
        </g>

        <g className="vela-route-nodes">{nodes.map(([x, y], index) => {
          const revealAt = .05 + (1 - y / 760) * .55;
          const visible = resolved ? (index < 5 ? 1 : .12) : active >= revealAt ? 1 : .18;
          return <circle cx={x} cy={y} key={`${x}-${y}`} r={index < 5 ? 4 : 3} style={{ opacity: visible }} />;
        })}</g>
        <g className="vela-route-dust">{Array.from({ length: 44 }, (_, index) => {
          const x = 48 + ((index * 137) % 904);
          const y = 355 + ((index * 79) % 355);
          return <circle cx={x} cy={y} key={index} r={index % 7 === 0 ? 2.1 : 1.25} />;
        })}</g>

        {active > .08 && !resolved && <g className="vela-route-traveler"><circle r="4"><animateMotion dur={`${Math.max(1.3, 3.2 - activity)}s`} repeatCount="indefinite" path={routes[0]} /></circle></g>}
        {resolved && <g className="vela-route-destination" transform="translate(501 75)"><circle r="18" /><circle r="7" /><path d="m-3 0 2.4 2.7L5-4" /></g>}
      </g>
    </svg>
  );
}
