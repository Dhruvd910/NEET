import type { SVGProps } from "react";

const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

type Icon = (p: SVGProps<SVGSVGElement>) => React.ReactElement;

/** Compass ring around a medical cross — the product mark. */
export function CompassCross({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <circle cx="12" cy="12" r="8.2" />
      <path d="M12 8.4v7.2M8.4 12h7.2" strokeWidth="2.1" />
      <path d="M12 1.6v2M12 20.4v2M1.6 12h2M20.4 12h2" strokeWidth="1.6" />
    </svg>
  );
}

export function Stethoscope({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M11 2v2M5 2v2" />
      <path d="M5 3H4a2 2 0 0 0-2 2v4a6 6 0 0 0 12 0V5a2 2 0 0 0-2-2h-1" />
      <path d="M8 15a6 6 0 0 0 12 0v-3" />
      <circle cx="20" cy="10" r="2" />
    </svg>
  );
}

export function HeartPulse({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
      <path d="M3.2 12h5.3l.9-1.8 2 4.4 2-6.6 1.5 3.4h5.9" />
    </svg>
  );
}

export function Dna({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="m10 16 1.5 1.5M14 8l-1.5-1.5M15 2c-1.8 2-2.5 4-2.8 6M16.5 10.5l1 1M17 6l-2.9-2.9M2 15c6.7-6 13.3 0 20-6" />
      <path d="m20 9 .9.9M3.1 14.1 4 15M6.5 12.5l1 1M7 18l2.9 2.9M9 22c1.8-2 2.5-4 2.8-6" />
    </svg>
  );
}

export function Microscope({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M6 18h8M3 22h18" />
      <path d="M14 22a7 7 0 1 0 0-14h-1M9 14h2" />
      <path d="M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z" />
      <path d="M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3" />
    </svg>
  );
}

export function Pill({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z" />
      <path d="m8.5 8.5 7 7" />
    </svg>
  );
}

export function Hospital({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M4 21V6l8-3 8 3v15" />
      <path d="M3 21h18" />
      <path d="M12 9.5v4M10 11.5h4" strokeWidth="2" />
      <path d="M9.5 21v-5h5v5" />
    </svg>
  );
}

export function Clipboard({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <rect x="8" y="2" width="8" height="4" rx="1" />
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      <path d="m9 13.5 2 2 4-4" />
    </svg>
  );
}

export function BadgeId({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <circle cx="9" cy="10.5" r="2" />
      <path d="M6.2 16.4a3 3 0 0 1 5.6 0M15 9h3.5M15 12.5h3.5" />
    </svg>
  );
}

export function Atom({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <circle cx="12" cy="12" r="2" />
      <path d="M12 3.2c4.9 0 8.8 3.9 8.8 8.8M12 20.8c-4.9 0-8.8-3.9-8.8-8.8" />
      <path d="M4.9 6.1c2.5-4.2 8.2-4.9 12.2-2.1M19.1 17.9c-2.5 4.2-8.2 4.9-12.2 2.1" />
    </svg>
  );
}

export function Flask({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M9 3h6M10 3v5.2L5.4 17A2.4 2.4 0 0 0 7.5 21h9a2.4 2.4 0 0 0 2.1-4L14 8.2V3" />
      <path d="M7.5 15h9" />
    </svg>
  );
}

export function Leaf({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M11 20A7 7 0 0 1 4 13c0-5 4-9 16-9 0 12-4 16-9 16Z" />
      <path d="M4 21c2-6 6-9 11-11" />
    </svg>
  );
}

export function Target({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4" />
      <path d="M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3" />
    </svg>
  );
}

export function Scale({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M12 4v16M7 20h10M5 8h14M5 8l-3 6h6L5 8zM19 8l-3 6h6l-3-6z" />
    </svg>
  );
}

export function Calendar({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <rect x="3" y="5" width="18" height="16" rx="2.5" />
      <path d="M8 3v4M16 3v4M3 10h18M8 14h2M8 17.5h2M14 14h2M14 17.5h2" />
    </svg>
  );
}

export function Sparkle({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />
      <path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" />
    </svg>
  );
}

export function Check({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M20 6L9 17l-5-5" strokeWidth="2.4" />
    </svg>
  );
}

export function Arrow({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

export function Plus({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M12 5v14M5 12h14" strokeWidth="2.2" />
    </svg>
  );
}

export function Search({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="m16.5 16.5 4 4" />
    </svg>
  );
}

export function Trash({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M10 11v6M14 11v6" />
    </svg>
  );
}

export function MessageSquare({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M21 12a8.5 8.5 0 0 1-12.3 7.6L4 21l1.4-4.6A8.5 8.5 0 1 1 21 12Z" />
    </svg>
  );
}

export function PanelLeft({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <path d="M9 4v16" />
    </svg>
  );
}

export function Mic({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7" />
    </svg>
  );
}

export function Send({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M12 19V5M6 11l6-6 6 6" strokeWidth="2.2" />
    </svg>
  );
}

export function Volume({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M11 5 6.5 9H3v6h3.5L11 19V5Z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
    </svg>
  );
}

export function X({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

/** Small ECG trace used as a section rule and in the hero. */
export function PulseRule({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 120 12" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M0 6h34l3-4 4 9 3-7 3 2h22l3-4 4 9 3-7 3 2h38" />
    </svg>
  );
}

/** Rod of Asclepius: a single serpent around a staff, the traditional symbol of medicine. */
export function Asclepius({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M12 2.5v19" strokeWidth="2" />
      <path d="M12 5.5c2.6 0 3.6 1.2 3.6 2.4S14.4 10 12 10s-3.6 1-3.6 2.2 1.2 2.3 3.6 2.3 3.4.9 3.4 2-1.1 2-3.4 2" />
      <path d="M12 5.5c-1.3 0-2.2-.6-2.2-1.4S10.7 2.8 12 2.8" />
    </svg>
  );
}

export function Clock({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

export function Bell({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

export function Flag({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M4 22V4" />
      <path d="M4 4h12l-2 4 2 4H4" />
    </svg>
  );
}

export function Pencil({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
      <path d="m15 5 4 4" />
    </svg>
  );
}

export function Expand({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3" />
    </svg>
  );
}

export function Syringe({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" className={className} {...base} {...rest} aria-hidden="true">
      <path d="m18 2 4 4M17 7l3-3M19 9 8.7 19.3a2.4 2.4 0 0 1-3.4 0l-.6-.6a2.4 2.4 0 0 1 0-3.4L15 5" />
      <path d="m9 11 4 4M5 19l-3 3M14 4l6 6" />
    </svg>
  );
}

export type { Icon };
