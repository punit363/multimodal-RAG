// app/page.tsx
"use client";

import Link from "next/link";
import { Abstract3DNode } from "@/components/Abstract3DNode";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ArrowRight, Code, MessageSquare, Globe } from "lucide-react";

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col justify-between px-6 md:px-16 py-8 relative overflow-hidden">
      
      {/* Top Navigation */}
      <header className="flex items-center justify-between z-20">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <span className="w-3 h-3 rounded-full bg-[#D4AF37] shadow-[0_0_12px_#D4AF37]" />
          <span className="font-bold text-lg tracking-wider text-neutral-900 dark:text-white uppercase">
            MultiModal<span className="text-[#D4AF37]">.RAG</span>
          </span>
        </div>

        {/* Nav Links */}
        <nav className="hidden md:flex items-center gap-8 text-xs font-semibold tracking-widest text-neutral-500 dark:text-neutral-400 uppercase">
          <a href="#features" className="hover:text-[#D4AF37] transition-colors">Features</a>
          <a href="#architecture" className="hover:text-[#D4AF37] transition-colors">Architecture</a>
          <a href="#docs" className="hover:text-[#D4AF37] transition-colors">Docs</a>
          <a href="#pipeline" className="hover:text-[#D4AF37] transition-colors">Pipeline</a>
          <a href="#demo" className="hover:text-[#D4AF37] transition-colors">Demo</a>
        </nav>

        {/* Theme Toggle */}
        <div className="flex items-center gap-4">
          <ThemeToggle />
        </div>
      </header>

      {/* Hero Section */}
      <main className="flex-1 flex flex-col md:flex-row items-center justify-between gap-12 my-12 z-10">
        {/* Left Text Block */}
        <div className="max-w-xl space-y-8">
          <div className="inline-flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-neutral-400 dark:text-neutral-500">
            <span className="w-8 h-[1px] bg-[#D4AF37]" />
            Next-Gen Document Intelligence
          </div>

          <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-neutral-900 dark:text-white leading-[1.15]">
            Multi-Modal <span className="text-[#D4AF37] underline decoration-[#D4AF37]/40 underline-offset-8">RAG</span>
          </h1>

          <p className="text-sm sm:text-base text-neutral-600 dark:text-neutral-400 leading-relaxed max-w-md">
            Seamlessly query complex unstructured PDFs. Deep reasoning across text, embedded HTML tables, and multi-modal vector embeddings.
          </p>

          {/* Action Button -> Navigates to /chat */}
          <div>
            <Link
              href="/chat"
              className="inline-flex items-center gap-3 px-8 py-3.5 rounded-full border border-[#D4AF37]/60 text-xs font-semibold tracking-widest uppercase text-neutral-900 dark:text-white hover:bg-gold-gradient hover:text-black dark:hover:text-black transition-all duration-300 group shadow-[0_0_20px_rgba(212,175,55,0.2)]"
            >
              <span>Launch RAG Explorer</span>
              <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
            </Link>
          </div>
        </div>

        {/* Right 3D Visual Element */}
        <div className="w-full md:w-auto flex justify-center">
          <Abstract3DNode />
        </div>
      </main>

      {/* Footer / Socials */}
      <footer className="flex items-end justify-between z-20 text-xs text-neutral-400">
        <div className="hidden sm:block font-mono tracking-widest text-[10px] uppercase rotate-[-90deg] origin-left translate-y-[-20px]">
          • Scroll Down
        </div>

        <div className="flex items-center gap-6 text-neutral-500 dark:text-neutral-400 ml-auto">
          <a href="#" className="hover:text-[#D4AF37] transition-colors"><Code size={16} /></a>
          <a href="#" className="hover:text-[#D4AF37] transition-colors"><MessageSquare size={16} /></a>
          <a href="#" className="hover:text-[#D4AF37] transition-colors"><Globe size={16} /></a>
        </div>
      </footer>

    </div>
  );
}