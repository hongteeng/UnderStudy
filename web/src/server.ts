import { createServer, IncomingMessage, ServerResponse } from "node:http";
import { execFile } from "node:child_process";
import { readFile, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { AskRequest, AskResponse, Teacher } from "./types.js";

const WEB_ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const PROJECT_ROOT = resolve(WEB_ROOT, "..");
const PUBLIC_DIR = join(WEB_ROOT, "public");
const TEACHERS_DIR = join(PROJECT_ROOT, "data", "teachers");
const PYTHON = existsSync(join(PROJECT_ROOT, ".venv/bin/python"))
  ? join(PROJECT_ROOT, ".venv/bin/python")
  : "python3";
const PORT = Number(process.env.PORT ?? 3000);
// Local dev stays on localhost; hosts set HOST=0.0.0.0 (the Dockerfile does).
const HOST = process.env.HOST ?? "127.0.0.1";
// Students enter this code in the page. Unset = open (local dev only).
const ACCESS_CODE = process.env.ACCESS_CODE ?? "";
// Optional comma-separated allowlist, e.g. TEACHER_IDS=hong-ting
const TEACHER_IDS = (process.env.TEACHER_IDS ?? "").split(",").map((t) => t.trim()).filter(Boolean);
const PER_MINUTE = Number(process.env.RATE_PER_MINUTE ?? 6); // per student IP
const DAILY_CAP = Number(process.env.DAILY_CAP ?? 300);      // total questions/day, protects your OpenAI bill

const hits = new Map<string, number[]>();
let day = new Date().toDateString();
let today = 0;

function allowed(ip: string): string | null {
  const now = Date.now();
  if (day !== new Date().toDateString()) { day = new Date().toDateString(); today = 0; }
  if (today >= DAILY_CAP) return "Daily limit reached. Please try again tomorrow.";
  const recent = (hits.get(ip) ?? []).filter((t) => now - t < 60_000);
  if (recent.length >= PER_MINUTE) return "Slow down a little and try again in a minute.";
  recent.push(now);
  hits.set(ip, recent);
  today++;
  return null;
}

function clientIp(req: IncomingMessage): string {
  const fwd = req.headers["x-forwarded-for"];
  const first = (Array.isArray(fwd) ? fwd[0] : fwd)?.split(",")[0]?.trim();
  return first || req.socket.remoteAddress || "unknown";
}

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
};

function send(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

async function listTeachers(): Promise<Teacher[]> {
  const entries = await readdir(TEACHERS_DIR, { withFileTypes: true });
  const teachers: Teacher[] = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    // Only teachers whose rules have been approved can answer questions.
    if (!existsSync(join(TEACHERS_DIR, entry.name, "rules.md"))) continue;
    let name = entry.name;
    try {
      const meta = JSON.parse(
        await readFile(join(TEACHERS_DIR, entry.name, "teacher.json"), "utf-8"),
      );
      name = meta.display_name ?? name;
    } catch {
      /* fall back to folder name */
    }
    if (TEACHER_IDS.length && !TEACHER_IDS.includes(entry.name)) continue;
    teachers.push({ id: entry.name, name });
  }
  return teachers.sort((a, b) => a.name.localeCompare(b.name));
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((ok, fail) => {
    let data = "";
    req.on("data", (chunk) => {
      data += chunk;
      if (data.length > 20_000) fail(new Error("Request too large"));
    });
    req.on("end", () => ok(data));
    req.on("error", fail);
  });
}

// Reuses the existing Python engine, so the UI never re-implements teacher logic.
function ask({ teacher, question }: AskRequest): Promise<AskResponse> {
  return new Promise((done) => {
    execFile(
      PYTHON,
      ["answer.py", "--teacher", teacher, question],
      { cwd: PROJECT_ROOT, timeout: 120_000, maxBuffer: 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) done({ error: stderr.trim() || error.message });
        else done({ answer: stdout.trim() });
      },
    );
  });
}

createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", "http://localhost");

    if (url.pathname.startsWith("/api/") && ACCESS_CODE && req.headers["x-access-code"] !== ACCESS_CODE) {
      return send(res, 401, { error: "Wrong or missing access code." });
    }

    if (req.method === "GET" && url.pathname === "/api/teachers") {
      return send(res, 200, await listTeachers());
    }

    if (req.method === "POST" && url.pathname === "/api/ask") {
      const body = JSON.parse(await readBody(req)) as AskRequest;
      const teachers = await listTeachers();
      if (!teachers.some((t) => t.id === body.teacher)) {
        return send(res, 400, { error: "Unknown teacher." });
      }
      if (!body.question?.trim()) {
        return send(res, 400, { error: "Please enter a question." });
      }
      const limited = allowed(clientIp(req));
      if (limited) return send(res, 429, { error: limited });
      const result = await ask({ teacher: body.teacher, question: body.question.trim() });
      return send(res, result.error ? 500 : 200, result);
    }

    if (req.method === "GET") {
      const file = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
      const full = resolve(PUBLIC_DIR, file);
      if (full.startsWith(PUBLIC_DIR) && existsSync(full)) {
        res.writeHead(200, { "Content-Type": MIME[extname(full)] ?? "text/plain" });
        return res.end(await readFile(full));
      }
    }
    send(res, 404, { error: "Not found" });
  } catch (error) {
    send(res, 500, { error: error instanceof Error ? error.message : "Server error" });
  }
}).listen(PORT, HOST, () => {
  console.log(`UnderStudy UI: http://localhost:${PORT}`);
});
