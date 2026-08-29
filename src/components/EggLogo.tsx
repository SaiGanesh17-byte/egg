import React from 'react';

export function EggLogo({ className = "w-10 h-10" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 512 512" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="bgGrad" x1="0" y1="0" x2="512" y2="512" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#1C212B" />
          <stop offset="55%" stopColor="#12151C" />
          <stop offset="100%" stopColor="#06070A" />
        </linearGradient>
        <linearGradient id="squircleSheen" x1="256" y1="32" x2="256" y2="300" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.06" />
          <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="shellGlass" x1="150" y1="85" x2="362" y2="425" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.22" />
          <stop offset="45%" stopColor="#FFFFFF" stopOpacity="0.05" />
          <stop offset="100%" stopColor="#0071E3" stopOpacity="0.16" />
        </linearGradient>
        <linearGradient id="shellBorder" x1="150" y1="85" x2="362" y2="425" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.55" />
          <stop offset="55%" stopColor="#FFFFFF" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#0071E3" stopOpacity="0.35" />
        </linearGradient>
        <linearGradient id="specular" x1="180" y1="120" x2="240" y2="220" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="nodeGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#30D158" stopOpacity="0.35" />
          <stop offset="60%" stopColor="#0071E3" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#0071E3" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="dotGlowWhite" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="dotGlowGreen" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#30D158" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#30D158" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="dotGlowBlue" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#0A84FF" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#0A84FF" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="dotGlowRed" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#FF453A" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#FF453A" stopOpacity="0" />
        </radialGradient>
        <filter id="blurGlow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="26" />
        </filter>
        <filter id="blurSoft" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
        <clipPath id="eggClip">
          <path d="M 256 98 C 338 98, 390 190, 390 286 C 390 368, 330 424, 256 424 C 182 424, 122 368, 122 286 C 122 190, 174 98, 256 98 Z" />
        </clipPath>
      </defs>
      <rect x="32" y="32" width="448" height="448" rx="100" fill="url(#bgGrad)" stroke="rgba(255,255,255,0.08)" strokeWidth="2"/>
      <rect x="33" y="33" width="446" height="446" rx="99" fill="url(#squircleSheen)"/>
      <circle cx="256" cy="270" r="150" fill="url(#nodeGlow)" filter="url(#blurGlow)"/>
      <path d="M 256 98 C 338 98, 390 190, 390 286 C 390 368, 330 424, 256 424 C 182 424, 122 368, 122 286 C 122 190, 174 98, 256 98 Z" fill="url(#shellGlass)" stroke="url(#shellBorder)" strokeWidth="2.5" />
      <g clipPath="url(#eggClip)">
        <ellipse cx="196" cy="150" rx="46" ry="30" fill="url(#specular)" transform="rotate(-28 196 150)" opacity="0.8"/>
        <g stroke="rgba(255,255,255,0.28)" strokeWidth="2" strokeLinecap="round">
          <line x1="256" y1="178" x2="202" y2="244" />
          <line x1="256" y1="178" x2="308" y2="240" />
          <line x1="202" y1="244" x2="228" y2="328" />
          <line x1="308" y1="240" x2="228" y2="328" />
          <line x1="308" y1="240" x2="322" y2="318" />
          <line x1="228" y1="328" x2="278" y2="362" />
        </g>
        <circle cx="256" cy="178" r="16" fill="url(#dotGlowWhite)" filter="url(#blurSoft)" />
        <circle cx="202" cy="244" r="16" fill="url(#dotGlowGreen)" filter="url(#blurSoft)" />
        <circle cx="308" cy="240" r="18" fill="url(#dotGlowBlue)" filter="url(#blurSoft)" />
        <circle cx="228" cy="328" r="18" fill="url(#dotGlowWhite)" filter="url(#blurSoft)" />
        <circle cx="322" cy="318" r="14" fill="url(#dotGlowRed)" filter="url(#blurSoft)" />
        <circle cx="278" cy="362" r="14" fill="url(#dotGlowWhite)" filter="url(#blurSoft)" />
        <circle cx="256" cy="178" r="6.5" fill="#FFFFFF" />
        <circle cx="202" cy="244" r="5.5" fill="#30D158" />
        <circle cx="308" cy="240" r="6.5" fill="#0A84FF" />
        <circle cx="228" cy="328" r="7.5" fill="#FFFFFF" />
        <circle cx="322" cy="318" r="5" fill="#FF453A" />
        <circle cx="278" cy="362" r="5.5" fill="#FFFFFF" />
        <g fill="none" stroke="rgba(255,255,255,0.6)" strokeWidth="1">
          <circle cx="256" cy="178" r="6.5" />
          <circle cx="202" cy="244" r="5.5" />
          <circle cx="308" cy="240" r="6.5" />
          <circle cx="228" cy="328" r="7.5" />
          <circle cx="322" cy="318" r="5" />
          <circle cx="278" cy="362" r="5.5" />
        </g>
      </g>
    </svg>
  );
}
