import { readFile } from "node:fs/promises";
import sharp from "sharp";

const publicRoot = new URL("../public/", import.meta.url);
const assetRoot = new URL("../assets/", import.meta.url);
const mark = await readFile(new URL("gazette-emblem.png", assetRoot));
const carrier = await readFile(new URL("notice-carrier.png", assetRoot));
for (const [name, size] of [["favicon-32.png", 32], ["apple-touch-icon.png", 180], ["brand-mark-512.png", 512]]) {
  await sharp(mark).trim().resize(size, size, { fit: "contain", background: "#f4f0e6" }).png().toFile(new URL(name, publicRoot).pathname);
}
await sharp(mark).trim().resize(256, 256, { fit: "contain", background: "#00000000" }).png({ palette: true, quality: 90 }).toFile(new URL("gazette-emblem.png", publicRoot).pathname);
await sharp(carrier).resize(640, 640, { fit: "contain", background: "#00000000" }).png({ palette: true, quality: 90 }).toFile(new URL("notice-carrier.png", publicRoot).pathname);

const card = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <path fill="#f4f0e6" d="M0 0h1200v630H0z"/>
  <path fill="#232b27" d="M0 0h1200v12H0zM58 170h1084v2H58zM58 178h1084v1H58zM58 557h1084v2H58z"/>
  <image x="50" y="30" width="130" height="130" href="data:image/png;base64,${mark.toString("base64")}"/>
  <g fill="#232b27" font-family="Georgia, serif">
    <text x="188" y="116" font-size="64" font-weight="700" letter-spacing="-4">Breach <tspan font-style="italic">Gazette</tspan></text>
    <text x="62" y="302" font-size="76" font-weight="700" letter-spacing="-3">When a breach</text>
    <text x="62" y="387" font-size="76" font-weight="700" letter-spacing="-3">becomes <tspan fill="#a33b25" font-weight="400" font-style="italic">public.</tspan></text>
  </g>
  <g font-family="Arial, sans-serif" fill="#5d625b">
    <text x="65" y="224" font-size="16" letter-spacing="3">THE PUBLIC RECORD</text>
    <text x="65" y="463" font-size="24">Official breach notices. Source by source.</text>
    <text x="65" y="598" font-size="17">NOTIFICATIONS / STATISTICS / REGULATOR ACTIONS</text>
    <text x="1138" y="598" text-anchor="end" font-size="17">breachgazette.netlify.app</text>
  </g>
  <image x="797" y="190" width="350" height="350" href="data:image/png;base64,${carrier.toString("base64")}"/>
</svg>`;
await sharp(Buffer.from(card)).png().toFile(new URL("og-card.png", publicRoot).pathname);
console.log("Rendered the masthead emblem, notice carrier, touch icon and social card.");
