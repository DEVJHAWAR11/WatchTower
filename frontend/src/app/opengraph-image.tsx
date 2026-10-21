import { ImageResponse } from "next/og";

export const alt = "Watchtower: the web moves, we keep watch";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  const rings = [90, 150, 210, 270];
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", background: "#f0ece2", color: "#14201b", padding: 72, position: "relative" }}>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", width: 700 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 40 }}>
            <div style={{ width: 44, height: 44, border: "5px solid #14201b", transform: "rotate(45deg)" }} />
            Watchtower
          </div>
          <div style={{ display: "flex", flexDirection: "column", fontSize: 88, lineHeight: 1.02, letterSpacing: -3 }}>
            <span>The web moves.</span>
            <span style={{ color: "#b5671a" }}>We keep watch.</span>
          </div>
          <div style={{ fontSize: 28, color: "#3c4741", width: 640 }}>AI agents that watch the web and bring you the signal.</div>
        </div>
        <div style={{ position: "absolute", right: -110, top: 45, width: 540, height: 540, display: "flex" }}>
          {rings.map((r) => (
            <div
              key={r}
              style={{ position: "absolute", left: 270 - r, top: 270 - r, width: r * 2, height: r * 2, borderRadius: "50%", border: "1.5px solid rgba(20,32,27,0.25)" }}
            />
          ))}
          <div style={{ position: "absolute", left: 270, top: 0, width: 1.5, height: 540, background: "rgba(20,32,27,0.3)" }} />
          <div style={{ position: "absolute", top: 270, left: 0, height: 1.5, width: 540, background: "rgba(20,32,27,0.3)" }} />
          <div style={{ position: "absolute", left: 262, top: 262, width: 16, height: 16, borderRadius: 8, background: "#14201b" }} />
          <div style={{ position: "absolute", left: 420, top: 120, width: 22, height: 22, borderRadius: 11, background: "#e29a3b" }} />
          <div style={{ position: "absolute", left: 160, top: 360, width: 12, height: 12, borderRadius: 6, background: "#14201b" }} />
        </div>
      </div>
    ),
    size,
  );
}
