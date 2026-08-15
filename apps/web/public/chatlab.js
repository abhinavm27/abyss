const API = `http://${location.hostname}:8011`;
const DEMO = { email: "demo@example.test", password: "demo-password-123" };
let journey = null;

const el = (id) => document.getElementById(id);
const messages = el("messages");
const input = el("input");
const status = el("status");

function addMessage(text, role = "assistant") {
  const node = document.createElement("div");
  node.className = `msg ${role}`;
  node.textContent = text;
  messages.append(node);
  messages.scrollTop = messages.scrollHeight;
}

async function request(path, options = {}) {
  const token = localStorage.getItem("abyss.token");
  const response = await fetch(API + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function button(label, handler, secondary = false) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = `control${secondary ? " secondary" : ""}`;
  node.textContent = label;
  node.onclick = async () => {
    node.disabled = true;
    await run(handler);
    node.disabled = false;
  };
  return node;
}

function render() {
  el("stage").textContent = journey ? journey.stage : "Not started";
  const controls = el("controls");
  controls.replaceChildren();
  if (!journey) {
    controls.textContent = "Send a request to create a journey.";
  } else if (journey.stage === "intake") {
    if (journey.onboarding_missing?.length) {
      const note = document.createElement("p");
      note.textContent = `Waiting for: ${journey.onboarding_missing.join(", ")}. Answer in chat to continue.`;
      controls.append(note);
    } else {
      controls.append(button("Approve synthetic document processing", async () => {
        journey = await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "process_documents", scope: "synthetic request and documents", approved: true }) });
        addMessage("Consent recorded. Intake advanced to deterministic comparison.");
      }));
    }
  } else if (journey.stage === "compare") {
    controls.append(button("Run deterministic plan comparison", async () => {
      journey = await request(`/api/journeys/${journey.journey_id}/compare`, { method: "POST" });
      addMessage("Three seeded paths were evaluated and ranked by deterministic annual-cost rules.");
    }));
  } else if (journey.stage === "recommend") {
    controls.append(button("Continue with recommended plan", async () => {
      journey = await request(`/api/journeys/${journey.journey_id}/advance`, { method: "POST" });
      addMessage("Recommendation accepted for the sandbox flow. Enrollment still requires explicit consent.");
    }));
    controls.append(button("Ask Nemotron to explain ranking", async () => {
      const result = await request(`/api/journeys/${journey.journey_id}/matching-reason`, { method: "POST", body: JSON.stringify({ question: "Why is the top feasible plan ranked first?" }) });
      journey = result.journey;
      addMessage(result.reason);
    }, true));
  } else if (journey.stage === "enroll") {
    controls.append(button("Approve sandbox enrollment in WA Plan B", async () => {
      await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "enroll_plan", scope: "wa-plan-b", approved: true }) });
      journey = await request(`/api/journeys/${journey.journey_id}/actions`, { method: "POST", body: JSON.stringify({ action: "enroll_plan", scope: "wa-plan-b", idempotency_key: `ui-enroll-${journey.journey_id}` }) });
      addMessage("Sandbox enrollment completed and a receipt was recorded.");
    }));
  } else if (journey.stage === "transition") {
    controls.append(button("Approve safe coverage transition", async () => {
      const scope = "current coverage to wa-plan-b";
      await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "transition_coverage", scope, approved: true }) });
      journey = await request(`/api/journeys/${journey.journey_id}/actions`, { method: "POST", body: JSON.stringify({ action: "transition_coverage", scope, idempotency_key: `ui-transition-${journey.journey_id}`, new_effective_date: "2026-09-01", first_premium_confirmed: true }) });
      addMessage("Coverage transition completed only after the new effective date and first premium were confirmed.");
    }));
  } else if (journey.stage === "verify") {
    controls.append(button("Approve provider verification", async () => {
      const scope = "Dr. Lee / Seattle General";
      await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "share_with_provider", scope, approved: true }) });
      journey = await request(`/api/journeys/${journey.journey_id}/actions`, { method: "POST", body: JSON.stringify({ action: "share_with_provider", scope, idempotency_key: `ui-verify-${journey.journey_id}` }) });
      addMessage("Provider verification completed in the sandbox adapter.");
    }));
  } else if (journey.stage === "book") {
    controls.append(button("Approve sandbox appointment booking", async () => {
      const scope = "Dr. Lee / September 4, 2026 at 10:30";
      await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "book_appointment", scope, approved: true }) });
      journey = await request(`/api/journeys/${journey.journey_id}/actions`, { method: "POST", body: JSON.stringify({ action: "book_appointment", scope, idempotency_key: `ui-book-${journey.journey_id}` }) });
      addMessage("Sandbox appointment booked. The care journey is complete.");
    }));
  } else {
    controls.textContent = "Journey complete. All material actions have receipts.";
  }

  el("evaluations").innerHTML = journey?.evaluations?.length
    ? `<ul>${journey.evaluations.map((x) => `<li><b>${x.plan_name}</b>: $${x.annual_total.toLocaleString()}${x.feasible ? "" : " (constraint failed)"}</li>`).join("")}</ul>`
    : "No comparison yet.";
  el("receipts").innerHTML = journey?.receipts?.length
    ? `<ul>${journey.receipts.map((x) => `<li>${x.action}: ${x.status}</li>`).join("")}</ul>`
    : "No sandbox receipts yet.";
}

async function run(work) {
  status.className = "";
  status.textContent = "Working…";
  try {
    await work();
    status.textContent = journey ? `Stage: ${journey.stage}` : "Ready";
    render();
  } catch (error) {
    status.className = "error";
    status.textContent = `Error: ${error.message}`;
  }
}

el("login").onclick = () => run(async () => {
  const result = await request("/api/auth/login", { method: "POST", body: JSON.stringify(DEMO) });
  localStorage.setItem("abyss.token", result.token);
  el("login").textContent = "Synthetic demo user signed in";
  addMessage("Signed in. Send a care request to begin.");
});

el("composer").onsubmit = (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMessage(text, "user");
  run(async () => {
    if (!localStorage.getItem("abyss.token")) throw new Error("Sign in as the synthetic demo user first.");
    if (!journey) {
      journey = await request("/api/journeys", { method: "POST", body: JSON.stringify({}) });
      journey = await request(`/api/journeys/${journey.journey_id}/onboard`, { method: "POST", body: JSON.stringify({ text, source: "user_request" }) });
      addMessage(journey.onboarding_questions?.length ? journey.onboarding_questions.join(" ") : "The Onboarding and Knowledge agents recorded the intake facts.");
    } else if (journey.stage === "intake") {
      journey = await request(`/api/journeys/${journey.journey_id}/onboard`, { method: "POST", body: JSON.stringify({ text, source: "user_request" }) });
      addMessage(journey.onboarding_questions?.length ? journey.onboarding_questions.join(" ") : "The intake facts were recorded.");
    } else {
      addMessage("Use the journey controls to run the next permissioned step.");
    }
  });
};

render();
