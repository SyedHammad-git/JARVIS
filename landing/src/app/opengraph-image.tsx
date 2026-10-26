import { ImageResponse } from "next/og";

export const alt = "J.A.R.V.I.S. — Your AI. Your PC. Connected.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          alignItems: "center",
          justifyContent: "space-between",
          background: "linear-gradient(130deg, #06182B 0%, #10233F 65%, #0878F9 150%)",
          color: "#F5F9FF",
          padding: "80px",
          fontFamily: "Arial, sans-serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", maxWidth: "720px" }}>
          <div style={{ color: "#8BBEFF", fontSize: 24, fontWeight: 700, letterSpacing: 7 }}>J.A.R.V.I.S.</div>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 48, fontSize: 76, fontWeight: 800, lineHeight: 1.05 }}>
            <span>Your AI. Your PC.</span>
            <span>Connected.</span>
          </div>
          <div style={{ marginTop: 24, color: "#B7C6D9", fontSize: 25 }}>A personal AI dashboard for your connected devices.</div>
        </div>
        <div style={{ display: "flex", width: 150, height: 150, alignItems: "center", justifyContent: "center", border: "2px solid #70B5FF", borderRadius: 42, color: "#FFFFFF", fontSize: 84, fontWeight: 800 }}>J</div>
      </div>
    ),
    size,
  );
}
