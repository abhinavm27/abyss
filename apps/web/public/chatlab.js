const API = `http://${location.hostname}:8011`;
const DEMO = { email: "demo@example.test", password: "demo-password-123" };
let journey = null;

const el = (id) => document.getElementById(id);
const messages = el("messages");
const input = el("input");
const status = el("status");
const money = (value) => Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" });
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
})[char]);

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
    controls.append(button("Build current-plan care options", async () => {
      journey = await request(`/api/journeys/${journey.journey_id}/compare`, { method: "POST" });
      addMessage(`I found ${journey.current_plan_options.length} hospital options under your current ${journey.current_plan_name} scenario. Choose one below, or review the separate alternative-plan scenario.`);
    }));
  } else if (journey.stage === "recommend") {
    const note = document.createElement("p");
    note.textContent = `Keep ${journey.current_plan_name} and choose a hospital below. Selecting does not book care.`;
    controls.append(note);
    controls.append(button("Ask Nemotron to explain ranking", async () => {
      const result = await request(`/api/journeys/${journey.journey_id}/matching-reason`, { method: "POST", body: JSON.stringify({ question: "Explain the current-plan hospital options and the separate alternative coverage scenario without treating estimates as guarantees." }) });
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
    controls.append(button("Verify network and provider", async () => {
      const selected = journey.selected_care_path;
      if (!selected) throw new Error("Choose a current-plan hospital first.");
      const scope = `Dr. Lee / ${selected.hospital} / ${selected.plan_name}`;
      await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "share_with_provider", scope, approved: true }) });
      journey = await request(`/api/journeys/${journey.journey_id}/actions`, { method: "POST", body: JSON.stringify({ action: "share_with_provider", scope, idempotency_key: `ui-verify-${journey.journey_id}` }) });
      addMessage(`Sandbox verification completed for ${selected.hospital}. Booking still requires separate consent.`);
    }));
  } else if (journey.stage === "book") {
    controls.append(button("Approve sandbox appointment booking", async () => {
      const selected = journey.selected_care_path;
      if (!selected) throw new Error("A selected care path is required before booking.");
      const scope = `${selected.hospital} / September 4, 2026 at 10:30`;
      await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "book_appointment", scope, approved: true }) });
      journey = await request(`/api/journeys/${journey.journey_id}/actions`, { method: "POST", body: JSON.stringify({ action: "book_appointment", scope, idempotency_key: `ui-book-${journey.journey_id}` }) });
      addMessage("Sandbox appointment booked. The care journey is complete.");
    }));
  } else {
    controls.textContent = "Journey complete. All material actions have receipts.";
  }

  const currentCoverage = el("hospitals");
  if (journey?.selected_care_path) {
    const selected = journey.selected_care_path;
    const networkLabel = selected.network_status === "sandbox_verified" ? "network sandbox-verified" : "network verification pending";
    const bookingLabel = selected.booking_consent ? "booking consent recorded" : "no booking consent recorded";
    currentCoverage.innerHTML = `<div class="selected"><span class="eyebrow">Selected care path</span><b>${escapeHtml(selected.plan_name)}</b><strong>${escapeHtml(selected.hospital)}</strong><small>Scenario member cost ${money(selected.estimated_member_cost)} · ${networkLabel} · ${bookingLabel}</small></div>`;
  } else if (journey?.current_plan_options?.length) {
    currentCoverage.innerHTML = `<p><b>${escapeHtml(journey.current_plan_name)}</b> is your current plan. Choose a hospital to continue.</p><p class="notice">Member costs are deterministic scenarios using seeded plan terms and published hospital rates. Network verification is the next step.</p><ul>${journey.current_plan_options.slice(0, 3).map((x, index) => `<li class="path-card${index === 0 ? " recommended" : ""}"><span class="eyebrow">${index === 0 ? "Lowest current-plan scenario" : "Current-plan option"}</span><b>${escapeHtml(x.hospital)}</b><strong>${money(x.estimated_member_cost)} estimated member cost</strong><small>Hospital published ${money(x.published_typical_rate)} typical · annual scenario ${money(x.estimated_annual_total)} · network pending</small><button type="button" data-hospital-id="${x.hospital_id}">Choose ${escapeHtml(x.hospital)}</button></li>`).join("")}</ul>`;
    currentCoverage.querySelectorAll("button[data-hospital-id]").forEach((node) => {
      node.onclick = () => run(async () => {
        journey = await request(`/api/journeys/${journey.journey_id}/selection`, { method: "POST", body: JSON.stringify({ hospital_id: Number(node.dataset.hospitalId) }) });
        addMessage(`You chose ${journey.selected_care_path.hospital} with your current ${journey.selected_care_path.plan_name}. I recorded the choice; nothing has been booked.`);
      });
    });
  } else {
    currentCoverage.textContent = "No care options yet.";
  }

  const alternativeCoverage = el("evaluations");
  if (journey?.alternative_plan) {
    const alt = journey.alternative_plan;
    alternativeCoverage.innerHTML = `<div class="path-card"><span class="eyebrow">Optional switch scenario</span><b>${escapeHtml(alt.plan_name)}</b><strong>${money(alt.estimated_annual_total)} estimated annual total</strong><small>Potential savings ${money(alt.estimated_annual_savings)} · modeled at ${escapeHtml(alt.hospital)} · requires a separate eligibility and plan-switch flow</small><button id="explore-switch" type="button" class="secondary">Explore plan switch</button></div>`;
    el("explore-switch").onclick = () => addMessage(`${alt.plan_name} is an exploration-only scenario. The separate eligibility and plan-switch flow is not part of this demo; your current-plan selection is unchanged.`);
  } else {
    alternativeCoverage.textContent = "No alternative scenario yet.";
  }
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
