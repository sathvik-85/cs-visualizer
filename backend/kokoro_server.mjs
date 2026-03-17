/**
 * Kokoro TTS HTTP server.
 * Loads the Kokoro ONNX model once on startup, then serves TTS requests.
 *
 * POST /tts
 *   Body: { "text": "...", "output_path": "/tmp/..." }
 *   Response: { "duration": 2.34 }  (duration in seconds)
 *
 * GET /health
 *   Response: { "ready": true|false }
 */

import http from "http";
import fs from "fs";
import path from "path";
import { KokoroTTS } from "kokoro-js";

const PORT = process.env.KOKORO_PORT || 8001;
const VOICE = process.env.KOKORO_VOICE || "af_heart";
const MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";

// Set HF token if provided (required to download gated Kokoro model)
if (process.env.HF_TOKEN) {
  process.env.HUGGINGFACE_TOKEN = process.env.HF_TOKEN;
}

let tts = null;
let ready = false;

// Load model in background so health endpoint responds immediately
(async () => {
  try {
    console.log(`[kokoro] Loading model ${MODEL} …`);
    tts = await KokoroTTS.from_pretrained(MODEL, { dtype: "q8" });
    ready = true;
    console.log("[kokoro] Model ready.");
  } catch (err) {
    console.error("[kokoro] Failed to load model:", err);
    process.exit(1);
  }
})();

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => (data += chunk));
    req.on("end", () => {
      try {
        resolve(JSON.parse(data));
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

function send(res, status, body) {
  const json = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(json),
  });
  res.end(json);
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    return send(res, 200, { ready });
  }

  if (req.method === "POST" && req.url === "/tts") {
    if (!ready) {
      return send(res, 503, { error: "Model not ready yet" });
    }
    let body;
    try {
      body = await readBody(req);
    } catch {
      return send(res, 400, { error: "Invalid JSON body" });
    }

    const { text, output_path } = body;
    if (!text || !output_path) {
      return send(res, 400, { error: "Missing text or output_path" });
    }

    try {
      const audio = await tts.generate(text, { voice: VOICE });
      fs.mkdirSync(path.dirname(output_path), { recursive: true });
      await audio.save(output_path);
      const duration = audio.audio.length / audio.sampling_rate;
      return send(res, 200, { duration });
    } catch (err) {
      console.error("[kokoro] TTS generation error:", err);
      return send(res, 500, { error: String(err) });
    }
  }

  send(res, 404, { error: "Not found" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[kokoro] Server listening on http://127.0.0.1:${PORT}`);
});
