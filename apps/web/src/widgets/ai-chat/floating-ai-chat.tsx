"use client";

import { useState } from "react";
import { AiChat } from "@/widgets/ai-chat/ai-chat";

/** App-wide floating AI chat: a bottom-right bubble that toggles the chat panel. */
export function FloatingAiChat() {
  const [open, setOpen] = useState(false);
  return (
    <>
      {open ? (
        <div className="fixed bottom-24 right-4 z-50 max-h-[78vh] w-[min(440px,94vw)] overflow-y-auto rounded-xl shadow-2xl sm:right-6">
          <AiChat />
        </div>
      ) : null}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? "Đóng chat AI" : "Hỏi chuyên gia AI"}
        title={open ? "Đóng" : "Hỏi chuyên gia AI"}
        className="fixed bottom-5 right-4 z-50 grid h-14 w-14 place-items-center rounded-full bg-brand text-2xl text-white shadow-xl transition-transform hover:scale-105 sm:right-6"
      >
        {open ? "✕" : "🤖"}
      </button>
    </>
  );
}
