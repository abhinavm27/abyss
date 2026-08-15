import { moneyExact } from "@/lib/api";

/** Progress toward the deductible, as a ring.
 *
 * The "where do I stand" glance. A ring rather than the bar used in PlanCard
 * because this is the home screen's anchor and needs to hold the centre of the
 * layout; the bar stays where it is, inside a denser list of figures.
 *
 * Plain SVG — a charting dependency for one arc would be a poor trade. */
export function DeductibleRing({
  met,
  total,
  size = 148,
}: {
  met: number;
  total: number;
  size?: number;
}) {
  const stroke = 10;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const fraction = total > 0 ? Math.min(1, Math.max(0, met / total)) : 0;
  const remaining = Math.max(0, total - met);
  const isMet = total > 0 && remaining <= 0;

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="-rotate-90"
          role="img"
          aria-label={
            isMet
              ? "Deductible met"
              : `${moneyExact(met)} of ${moneyExact(total)} deductible met`
          }
        >
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="hsl(var(--muted))"
            strokeWidth={stroke}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={isMet ? "hsl(var(--success))" : "hsl(var(--primary))"}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - fraction)}
            className="transition-[stroke-dashoffset] duration-700"
          />
        </svg>

        <div className="absolute inset-0 flex flex-col items-center justify-center">
          {isMet ? (
            <p className="font-display text-lg font-semibold text-success">Met</p>
          ) : (
            <>
              <p className="font-display text-2xl font-semibold leading-none text-foreground">
                {moneyExact(remaining)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">to go</p>
            </>
          )}
        </div>
      </div>

      <p className="mt-3 max-w-[16rem] text-center text-sm leading-relaxed text-muted-foreground">
        {isMet ? (
          <>You've met your deductible — your plan picks up more from here.</>
        ) : (
          <>
            {moneyExact(met)} of your {moneyExact(total)} deductible so far this year.
          </>
        )}
      </p>
    </div>
  );
}
