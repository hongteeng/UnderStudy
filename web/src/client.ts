import type { AskResponse, Teacher } from "./types.js";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const teacherSelect = $<HTMLSelectElement>("teacher");
const form = $<HTMLFormElement>("form");
const input = $<HTMLTextAreaElement>("question");
const button = $<HTMLButtonElement>("send");
const log = $<HTMLDivElement>("log");
const codeInput = $<HTMLInputElement>("code");

const KEY = "understudy-code";
try { codeInput.value = localStorage.getItem(KEY) ?? ""; } catch { /* storage blocked */ }
const headers = (): Record<string, string> => ({ "x-access-code": codeInput.value.trim() });

function addMessage(kind: "user" | "tutor" | "error", text: string): HTMLDivElement {
  const el = document.createElement("div");
  el.className = `msg ${kind}`;
  el.textContent = text; // textContent, never innerHTML: model output is untrusted
  log.appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}

async function loadTeachers(): Promise<void> {
  const res = await fetch("/api/teachers", { headers: headers() });
  if (!res.ok) {
    teacherSelect.replaceChildren();
    addMessage("error", "Enter the access code your teacher gave you (top right).");
    return;
  }
  const teachers: Teacher[] = await res.json();
  teacherSelect.replaceChildren(...teachers.map((t) => new Option(t.name, t.id)));
  if (!teachers.length) addMessage("error", "No teachers available yet.");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question || !teacherSelect.value) return;

  addMessage("user", question);
  input.value = "";
  button.disabled = true;
  const pending = addMessage("tutor", "Thinking…");

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({ teacher: teacherSelect.value, question }),
    });
    const data: AskResponse = await res.json();
    if (data.answer) pending.textContent = data.answer;
    else {
      pending.className = "msg error";
      pending.textContent = data.error ?? "Something went wrong.";
    }
  } catch {
    pending.className = "msg error";
    pending.textContent = "Could not reach the server.";
  } finally {
    button.disabled = false;
    input.focus();
  }
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

codeInput.addEventListener("change", () => {
  try { localStorage.setItem(KEY, codeInput.value.trim()); } catch { /* ignore */ }
  loadTeachers();
});

loadTeachers();
