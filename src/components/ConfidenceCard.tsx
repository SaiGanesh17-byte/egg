import React from 'react';

interface GlowDotProps {
  color: 'green' | 'blue' | 'red' | 'white';
}

export const GlowDot: React.FC<GlowDotProps> = ({ color }) => {
  const colorMap = {
    green: 'bg-[#30D158] shadow-[0_0_12px_rgba(48,209,88,0.6)]',
    blue: 'bg-[#0A84FF] shadow-[0_0_12px_rgba(10,132,255,0.6)]',
    red: 'bg-[#FF453A] shadow-[0_0_12px_rgba(255,69,58,0.6)]',
    white: 'bg-white shadow-[0_0_12px_rgba(255,255,255,0.6)]',
  };

  return (
    <div className="relative flex items-center justify-center w-4 h-4 mr-2">
      {/* Halo radial blur */}
      <div className={`absolute w-3 h-3 rounded-full opacity-35 blur-[3px] ${colorMap[color].split(' ')[0]}`} />
      {/* Solid center dot */}
      <div className={`w-2 h-2 rounded-full relative z-10 ${colorMap[color]}`} />
    </div>
  );
};

interface ConfidenceCardProps {
  highCount: number;
  mediumCount: number;
  lowCount: number;
  totalCount: number;
}

export const ConfidenceCard: React.FC<ConfidenceCardProps> = ({
  highCount = 0,
  mediumCount = 0,
  lowCount = 0,
  totalCount = 0,
}) => {
  const getPercentage = (count: number) => {
    if (!totalCount) return 0;
    return Math.round((count / totalCount) * 100);
  };

  const highPct = getPercentage(highCount);
  const mediumPct = getPercentage(mediumCount);
  const lowPct = getPercentage(lowCount);

  return (
    <div className="relative overflow-hidden transition-all duration-300 group rounded-[16px] backdrop-blur-xl border border-white/10 hover:border-white/20 p-6 bg-gradient-to-br from-white/[0.06] to-white/[0.02]">
      {/* Specular Highlight Hover Sweep */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-500 bg-[radial-gradient(ellipse_at_top_left,rgba(255,255,255,0.12)_0%,transparent_50%)]" />

      {/* Top Left Specular Shine Dot */}
      <div className="absolute top-2 left-2 w-16 h-8 rounded-full bg-white/5 blur-[8px] pointer-events-none transform -rotate-45" />

      <h3 className="text-sm font-semibold tracking-wider uppercase text-white/50 mb-4 flex items-center">
        <GlowDot color="white" /> Type-Resolution Confidence
      </h3>

      <div className="grid grid-cols-3 gap-6 relative z-10">
        {/* High Confidence */}
        <div className="relative group/stat p-4 rounded-xl bg-white/[0.02] border border-white/5 hover:border-white/10 transition-colors">
          {/* Ambient Glow */}
          <div className="absolute -inset-1 rounded-xl bg-[#30D158]/5 blur-lg opacity-0 group-hover/stat:opacity-100 transition-opacity pointer-events-none" />
          <div className="flex items-center text-xs text-white/60 mb-2">
            <GlowDot color="green" /> High (RTA)
          </div>
          <div className="text-2xl font-mono font-bold text-white relative">
            {highPct}%
            <span className="text-xs text-white/40 block font-sans font-normal mt-1">{highCount} edges</span>
          </div>
        </div>

        {/* Medium Confidence */}
        <div className="relative group/stat p-4 rounded-xl bg-white/[0.02] border border-white/5 hover:border-white/10 transition-colors">
          {/* Ambient Glow */}
          <div className="absolute -inset-1 rounded-xl bg-[#0A84FF]/5 blur-lg opacity-0 group-hover/stat:opacity-100 transition-opacity pointer-events-none" />
          <div className="flex items-center text-xs text-white/60 mb-2">
            <GlowDot color="blue" /> Medium
          </div>
          <div className="text-2xl font-mono font-bold text-white relative">
            {mediumPct}%
            <span className="text-xs text-white/40 block font-sans font-normal mt-1">{mediumCount} edges</span>
          </div>
        </div>

        {/* Low Confidence */}
        <div className="relative group/stat p-4 rounded-xl bg-white/[0.02] border border-white/5 hover:border-white/10 transition-colors">
          {/* Ambient Glow */}
          <div className="absolute -inset-1 rounded-xl bg-[#FF453A]/5 blur-lg opacity-0 group-hover/stat:opacity-100 transition-opacity pointer-events-none" />
          <div className="flex items-center text-xs text-white/60 mb-2">
            <GlowDot color="red" /> Low (CHA)
          </div>
          <div className="text-2xl font-mono font-bold text-white relative">
            {lowPct}%
            <span className="text-xs text-white/40 block font-sans font-normal mt-1">{lowCount} edges</span>
          </div>
        </div>
      </div>
    </div>
  );
};
