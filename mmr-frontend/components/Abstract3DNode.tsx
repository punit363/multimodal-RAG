"use client";

export function Abstract3DNode() {
  return (
    <div className="relative w-72 h-72 sm:w-96 sm:h-96 flex items-center justify-center">
      {/* Outer ambient gold glow */}
      <div className="absolute w-64 h-64 bg-[#D4AF37]/15 rounded-full blur-3xl animate-pulse" />

      {/* Floating 3D Geometric Layers */}
      <div className="relative w-full h-full flex items-center justify-center">
        {/* Outer Rotating Diamond Ring */}
        <div className="absolute w-56 h-56 border-2 border-[#D4AF37]/40 rounded-[30%] rotate-45 animate-[spin_20s_linear_infinite]" />

        {/* Inner Counter-Rotating Hexagon Ring */}
        <div className="absolute w-44 h-44 border border-[#AA7C11]/50 rounded-[20%] -rotate-12 animate-[spin_15s_linear_infinite_reverse]" />

        {/* Core Glassmorphic Node */}
        <div className="relative z-10 w-32 h-32 rounded-2xl bg-gradient-to-tr from-[#AA7C11]/40 via-[#D4AF37]/20 to-[#F3E5AB]/10 backdrop-blur-md border border-[#D4AF37]/50 shadow-gold-node flex flex-col items-center justify-center gap-2 transform hover:scale-105 transition-transform duration-500">
          <div className="w-10 h-10 rounded-full bg-gold-gradient shadow-[0_0_20px_rgba(212,175,55,0.8)] animate-pulse" />
          <span className="text-[10px] font-mono tracking-widest uppercase text-[#D4AF37]">
            M-RAG CORE
          </span>
        </div>

        {/* Floating Orbital Particle Points */}
        <div className="absolute top-8 left-12 w-3 h-3 rounded-full bg-[#D4AF37] shadow-[0_0_10px_#D4AF37] animate-bounce" />
        <div className="absolute bottom-10 right-14 w-2 h-2 rounded-full bg-[#F3E5AB] shadow-[0_0_8px_#F3E5AB] animate-ping" />
      </div>
    </div>
  );
}