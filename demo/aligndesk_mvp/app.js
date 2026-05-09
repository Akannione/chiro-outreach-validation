const templates = {
  lowBack: {
    patientName: "Jordan Lee",
    visitType: "Initial evaluation",
    region: "Lumbar spine",
    painScore: 6,
    chiefConcern:
      "Gradual onset low back pain after increased sitting and weekend lifting. Symptoms limit sitting tolerance and bending.",
    redFlags: ["No red flags reported", "Numbness/tingling screened"],
    rom: "Reduced flexion and extension",
    palpation: "Paraspinal hypertonicity and segmental restriction",
    findings: [
      "Functional limitation with sitting",
      "Functional limitation with lifting",
      "Postural compensation noted",
      "Neurologic screen within expected limits",
    ],
    plan: ["Chiropractic adjustment", "Therapeutic exercise instruction", "Ergonomic coaching"],
    frequency: "2x/week for 2 weeks, then reassess",
  },
  neck: {
    patientName: "Maya Brooks",
    visitType: "Follow-up adjustment",
    region: "Cervical spine",
    painScore: 4,
    chiefConcern:
      "Neck stiffness improved since prior visit, with lingering tension after desk work and limited right rotation.",
    redFlags: ["No red flags reported", "Numbness/tingling screened"],
    rom: "Reduced cervical rotation",
    palpation: "Upper trap and levator tenderness",
    findings: ["Postural compensation noted", "Home care compliance reviewed"],
    plan: ["Chiropractic adjustment", "Soft tissue therapy", "Ergonomic coaching"],
    frequency: "1x/week for 4 weeks",
  },
  pediatric: {
    patientName: "Avery Chen",
    visitType: "Pediatric exam",
    region: "Pediatric wellness",
    painScore: 1,
    chiefConcern:
      "Parent reports wellness check after sports activity. No acute complaint. Developmental and posture screen requested.",
    redFlags: ["No red flags reported", "Referral criteria reviewed"],
    rom: "Within functional limits",
    palpation: "Mild tenderness without acute distress",
    findings: ["Home care compliance reviewed", "Neurologic screen within expected limits"],
    plan: ["Therapeutic exercise instruction", "Ergonomic coaching"],
    frequency: "Wellness check in 4 weeks",
  },
  reeval: {
    patientName: "Chris Morgan",
    visitType: "Re-evaluation",
    region: "Pelvis / SI",
    painScore: 3,
    chiefConcern:
      "Recheck after two weeks of care. Patient reports improved walking tolerance with occasional SI discomfort after longer shifts.",
    redFlags: ["No red flags reported", "Numbness/tingling screened"],
    rom: "Guarded movement pattern",
    palpation: "SI tenderness with glute compensation",
    findings: [
      "Functional limitation with lifting",
      "Home care compliance reviewed",
      "Neurologic screen within expected limits",
    ],
    plan: ["Chiropractic adjustment", "Soft tissue therapy", "Re-evaluate next visit"],
    frequency: "As needed with home care",
  },
};

const fields = [
  "patientName",
  "visitType",
  "region",
  "painScore",
  "chiefConcern",
  "dictationNotes",
  "rom",
  "palpation",
  "frequency",
];

const checkboxGroups = ["redFlags", "findings", "plan"];

const form = document.querySelector("#noteForm");
const soapNote = document.querySelector("#soapNote");
const ehrOutput = document.querySelector("#ehrOutput");
const noteTitle = document.querySelector("#noteTitle");
const completionMetric = document.querySelector("#completionMetric");
const timeMetric = document.querySelector("#timeMetric");
const taskMetric = document.querySelector("#taskMetric");
const visitStatus = document.querySelector("#visitStatus");
const examStatus = document.querySelector("#examStatus");
const planStatus = document.querySelector("#planStatus");
const auditStatus = document.querySelector("#auditStatus");
const taskList = document.querySelector("#taskList");
const painScore = document.querySelector("#painScore");
const painScoreValue = document.querySelector("#painScoreValue");
const feedbackForm = document.querySelector("#feedbackForm");
const feedbackSaved = document.querySelector("#feedbackSaved");
const speechStatus = document.querySelector("#speechStatus");
const dictationNotes = document.querySelector("#dictationNotes");
const startDictation = document.querySelector("#startDictation");
const stopDictation = document.querySelector("#stopDictation");
const applyDictation = document.querySelector("#applyDictation");
const clearDictation = document.querySelector("#clearDictation");

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition;
let isListening = false;

function getChecked(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value);
}

function setChecked(name, values) {
  const selected = new Set(values);
  document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
    input.checked = selected.has(input.value);
  });
}

function getState() {
  return {
    patientName: document.querySelector("#patientName").value.trim(),
    visitType: document.querySelector("#visitType").value,
    region: document.querySelector("#region").value,
    painScore: Number(document.querySelector("#painScore").value),
    chiefConcern: document.querySelector("#chiefConcern").value.trim(),
    dictationNotes: document.querySelector("#dictationNotes").value.trim(),
    redFlags: getChecked("redFlags"),
    rom: document.querySelector("#rom").value,
    palpation: document.querySelector("#palpation").value,
    findings: getChecked("findings"),
    plan: getChecked("plan"),
    frequency: document.querySelector("#frequency").value,
  };
}

function applyTemplate(key) {
  const data = templates[key];
  fields.forEach((field) => {
    document.querySelector(`#${field}`).value = data[field];
  });
  checkboxGroups.forEach((group) => setChecked(group, data[group]));
  document.querySelectorAll(".case-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.template === key);
  });
  render();
}

function completeness(state) {
  const checks = [
    state.patientName,
    state.visitType,
    state.region,
    state.chiefConcern,
    state.redFlags.length >= 2,
    state.rom,
    state.palpation,
    state.findings.length >= 3,
    state.plan.length >= 2,
    state.frequency,
  ];
  return Math.round((checks.filter(Boolean).length / checks.length) * 100);
}

function noteSections(state) {
  const redFlags = state.redFlags.length ? state.redFlags.join("; ") : "Red flag review incomplete.";
  const findings = state.findings.length ? state.findings.join("; ") : "Additional functional findings needed.";
  const plan = state.plan.length ? state.plan.join("; ") : "Plan not selected.";

  return {
    subjective: `${state.patientName || "Patient"} presents for ${state.visitType.toLowerCase()} with ${state.region.toLowerCase()} concern. ${state.chiefConcern || "Chief concern not documented."} Pain reported at ${state.painScore}/10. ${redFlags}`,
    objective: `ROM: ${state.rom}. Palpation: ${state.palpation}. Functional findings: ${findings}${state.dictationNotes ? `. Dictated details: ${state.dictationNotes}` : ""}`,
    assessment: `${state.region} dysfunction with documented functional limitations and care plan alignment. Current documentation supports conservative chiropractic management pending ongoing response to care.`,
    plan: `${plan}. Recommended frequency: ${state.frequency}.`,
  };
}

function configureSpeechRecognition() {
  if (!SpeechRecognition) {
    speechStatus.textContent = "Dictation unsupported";
    speechStatus.className = "status-pill";
    startDictation.disabled = true;
    stopDictation.disabled = true;
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onstart = () => {
    isListening = true;
    speechStatus.textContent = "Listening";
    speechStatus.className = "status-pill good";
    startDictation.disabled = true;
    stopDictation.disabled = false;
  };

  recognition.onerror = (event) => {
    speechStatus.textContent = event.error === "not-allowed" ? "Mic blocked" : "Dictation paused";
    speechStatus.className = "status-pill";
    isListening = false;
    startDictation.disabled = false;
    stopDictation.disabled = true;
  };

  recognition.onend = () => {
    isListening = false;
    if (speechStatus.textContent === "Listening") {
      speechStatus.textContent = "Mic idle";
      speechStatus.className = "status-pill neutral";
    }
    startDictation.disabled = false;
    stopDictation.disabled = true;
  };

  recognition.onresult = (event) => {
    let finalText = "";
    let interimText = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const phrase = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalText += phrase;
      } else {
        interimText += phrase;
      }
    }

    if (finalText.trim()) {
      appendDictation(finalText.trim());
      render();
    }

    if (interimText.trim()) {
      speechStatus.textContent = "Listening...";
      speechStatus.className = "status-pill good";
    }
  };
}

function appendDictation(text) {
  const existing = dictationNotes.value.trim();
  dictationNotes.value = existing ? `${existing} ${text}` : text;
}

function startListening() {
  if (!recognition || isListening) return;
  try {
    recognition.start();
  } catch (_error) {
    speechStatus.textContent = "Mic busy";
    speechStatus.className = "status-pill";
  }
}

function stopListening() {
  if (!recognition || !isListening) return;
  recognition.stop();
}

function applyDictationToFields() {
  const text = dictationNotes.value.toLowerCase();
  if (!text.trim()) return;

  const painMatch =
    text.match(/(?:pain|score).*?(\d{1,2})(?:\s*out of\s*10|\s*\/\s*10)?/) ||
    text.match(/\b(\d{1,2})\s*(?:out of\s*)?10\b/);
  if (painMatch) {
    const value = Math.max(0, Math.min(10, Number(painMatch[1])));
    document.querySelector("#painScore").value = value;
  }

  if (text.includes("neck") || text.includes("cervical")) {
    document.querySelector("#region").value = "Cervical spine";
    document.querySelector("#rom").value = "Reduced cervical rotation";
    document.querySelector("#palpation").value = "Upper trap and levator tenderness";
  } else if (text.includes("low back") || text.includes("lumbar")) {
    document.querySelector("#region").value = "Lumbar spine";
    document.querySelector("#rom").value = "Reduced flexion and extension";
    document.querySelector("#palpation").value = "Paraspinal hypertonicity and segmental restriction";
  } else if (text.includes("si") || text.includes("pelvis")) {
    document.querySelector("#region").value = "Pelvis / SI";
    document.querySelector("#palpation").value = "SI tenderness with glute compensation";
  }

  const redFlags = new Set(getChecked("redFlags"));
  if (text.includes("no red flag")) redFlags.add("No red flags reported");
  if (text.includes("numbness") || text.includes("tingling")) redFlags.add("Numbness/tingling screened");
  if (text.includes("refer") || text.includes("referral")) redFlags.add("Referral criteria reviewed");
  setChecked("redFlags", [...redFlags]);

  const findings = new Set(getChecked("findings"));
  if (text.includes("sitting")) findings.add("Functional limitation with sitting");
  if (text.includes("lifting")) findings.add("Functional limitation with lifting");
  if (text.includes("posture") || text.includes("postural")) findings.add("Postural compensation noted");
  if (text.includes("home care") || text.includes("exercise")) findings.add("Home care compliance reviewed");
  if (text.includes("neuro") || text.includes("neurologic")) findings.add("Neurologic screen within expected limits");
  setChecked("findings", [...findings]);

  const plan = new Set(getChecked("plan"));
  if (text.includes("adjust")) plan.add("Chiropractic adjustment");
  if (text.includes("soft tissue")) plan.add("Soft tissue therapy");
  if (text.includes("exercise")) plan.add("Therapeutic exercise instruction");
  if (text.includes("ergonomic") || text.includes("desk")) plan.add("Ergonomic coaching");
  if (text.includes("re-evaluate") || text.includes("recheck")) plan.add("Re-evaluate next visit");
  setChecked("plan", [...plan]);

  if (!document.querySelector("#chiefConcern").value.trim()) {
    document.querySelector("#chiefConcern").value = sentenceCase(dictationNotes.value.trim());
  }

  speechStatus.textContent = "Note updated";
  speechStatus.className = "status-pill good";
  render();
}

function sentenceCase(text) {
  return text ? `${text[0].toUpperCase()}${text.slice(1)}` : "";
}

function buildTasks(state) {
  const tasks = [
    {
      title: "Confirm red flag screen before final sign-off",
      detail: state.redFlags.length >= 2 ? "Screen looks complete for demo note." : "Add red flag and referral criteria review.",
    },
    {
      title: "Send home care reminder",
      detail: state.plan.includes("Therapeutic exercise instruction")
        ? "Attach exercise instructions to patient follow-up."
        : "No exercise handout selected.",
    },
    {
      title: "Front desk scheduling",
      detail: `Schedule ${state.frequency.toLowerCase()}.`,
    },
  ];

  if (state.painScore >= 7) {
    tasks.unshift({
      title: "Escalate high pain score",
      detail: "Doctor review recommended before patient leaves.",
    });
  }

  return tasks;
}

function render() {
  const state = getState();
  const sections = noteSections(state);
  const score = completeness(state);
  const tasks = buildTasks(state);
  const estimatedSaved = Math.max(4, Math.round(score / 9));

  painScoreValue.textContent = state.painScore;
  noteTitle.textContent = `${state.patientName || "Patient"} · ${state.visitType}`;
  completionMetric.textContent = `${score}%`;
  timeMetric.textContent = `${estimatedSaved} min`;
  taskMetric.textContent = String(tasks.length);

  visitStatus.textContent = state.redFlags.length >= 2 ? "Red flags screened" : "Needs red flag review";
  visitStatus.className = `status-pill ${state.redFlags.length >= 2 ? "good" : ""}`;
  examStatus.textContent = `${state.findings.length} findings`;
  planStatus.textContent = state.plan.length >= 2 ? "Care plan ready" : "Plan incomplete";
  auditStatus.textContent = score >= 80 ? "Ready to paste" : "Needs review";
  auditStatus.className = `status-pill ${score >= 80 ? "good" : ""}`;

  const note = `SUBJECTIVE
${sections.subjective}

OBJECTIVE
${sections.objective}

ASSESSMENT
${sections.assessment}

PLAN
${sections.plan}`;

  soapNote.textContent = note;
  ehrOutput.value = `${state.patientName || "Patient"} - ${state.visitType}
Region: ${state.region}
Pain: ${state.painScore}/10

${note}

Follow-up tasks:
${tasks.map((task) => `- ${task.title}: ${task.detail}`).join("\n")}`;

  taskList.innerHTML = tasks
    .map(
      (task) => `
        <li>
          <span class="task-icon" aria-hidden="true">&#10003;</span>
          <div>
            <strong>${task.title}</strong>
            <p>${task.detail}</p>
          </div>
        </li>
      `,
    )
    .join("");
}

function copyText(text) {
  navigator.clipboard
    .writeText(text)
    .then(() => {
      auditStatus.textContent = "Copied";
      auditStatus.className = "status-pill good";
      setTimeout(render, 1400);
    })
    .catch(() => {
      ehrOutput.select();
      document.execCommand("copy");
    });
}

function switchTab(tab) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
  document.querySelector(`#${tab}Tab`).classList.add("active");
}

function saveFeedback(event) {
  event.preventDefault();
  const entries = JSON.parse(localStorage.getItem("aligndeskFeedback") || "[]");
  entries.push({
    savedAt: new Date().toISOString(),
    role: document.querySelector("#feedbackRole").value,
    saveTime: document.querySelector("#saveTime").value,
    priceReaction: document.querySelector("#priceReaction").value,
    missingPiece: document.querySelector("#missingPiece").value.trim(),
    patientCase: getState().visitType,
  });
  localStorage.setItem("aligndeskFeedback", JSON.stringify(entries));
  feedbackSaved.textContent = `Saved ${entries.length} reaction${entries.length === 1 ? "" : "s"} locally.`;
  feedbackForm.reset();
}

function exportFeedback() {
  const entries = JSON.parse(localStorage.getItem("aligndeskFeedback") || "[]");
  const header = ["savedAt", "role", "saveTime", "priceReaction", "missingPiece", "patientCase"];
  const rows = [header.join(",")].concat(
    entries.map((entry) =>
      header
        .map((key) => `"${String(entry[key] || "").replaceAll('"', '""')}"`)
        .join(","),
    ),
  );
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "aligndesk-demo-feedback.csv";
  link.click();
  URL.revokeObjectURL(url);
}

document.querySelectorAll(".case-button").forEach((button) => {
  button.addEventListener("click", () => applyTemplate(button.dataset.template));
});

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});

form.addEventListener("input", render);
form.addEventListener("change", render);
painScore.addEventListener("input", render);
feedbackForm.addEventListener("submit", saveFeedback);

document.querySelector("#resetButton").addEventListener("click", () => applyTemplate("lowBack"));
document.querySelector("#copyButton").addEventListener("click", () => copyText(ehrOutput.value));
document.querySelector("#copyPlainButton").addEventListener("click", () => copyText(ehrOutput.value));
document.querySelector("#exportFeedbackButton").addEventListener("click", exportFeedback);
startDictation.addEventListener("click", startListening);
stopDictation.addEventListener("click", stopListening);
applyDictation.addEventListener("click", applyDictationToFields);
clearDictation.addEventListener("click", () => {
  dictationNotes.value = "";
  speechStatus.textContent = "Mic idle";
  speechStatus.className = "status-pill neutral";
  render();
});

configureSpeechRecognition();
applyTemplate("lowBack");
