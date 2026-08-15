const API = `http://${location.hostname}:8011`;
const DEMO = { email: "demo@example.test", password: "demo-password-123" };
let journey = null;
let careContext = { journeys: [], appointments: [], scheduled_tasks: [] };
let lastAgentPlan = null;

const el = (id) => document.getElementById(id);
const messages = el("messages");
const input = el("input");
const status = el("status");
const money = (value) => Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" });
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
})[char]);
const localDateTime = (value) => new Date(value).toLocaleString("en-US", {
  weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
});

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
  renderCareContext();
  const controls = el("controls");
  controls.replaceChildren();
  if (!journey) {
    controls.textContent = "Send a request to create a journey.";
  } else if (journey.read_only_history) {
    controls.innerHTML = "<p>This durable journey history is available to the Journey Agent. Material actions require its deterministic runtime to be restored.</p>";
  } else if (journey.reschedule_original_slot) {
    if (!journey.selected_booking_slot) {
      controls.innerHTML = "<p>The original appointment is still confirmed. Choose a replacement slot below.</p>";
    } else if (journey.reschedule_pending) {
      controls.innerHTML = "<p>The replacement confirmation is pending. The original appointment remains confirmed.</p>";
    } else {
      controls.append(button("Approve replacement, then cancel original", async () => {
        const bookingScope = journey.booking_consent_scope;
        const cancellationScope = journey.cancellation_consent_scope;
        if (!bookingScope || !cancellationScope) throw new Error("Exact reschedule consent scopes are unavailable.");
        await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "book_appointment", scope: bookingScope, approved: true }) });
        await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "cancel_appointment", scope: cancellationScope, approved: true }) });
        journey = await request(`/api/journeys/${journey.journey_id}/reschedule`, { method: "POST", body: JSON.stringify({ booking_scope: bookingScope, cancellation_scope: cancellationScope, idempotency_key: `ui-reschedule-${journey.journey_id}-${journey.selected_booking_slot.slot_id}` }) });
        if (journey.reschedule_pending) {
          addMessage("The replacement is pending confirmation. I kept the original appointment and scheduled an exact-slot retry.");
          void pollBookingTask();
        } else {
          addMessage("The replacement was confirmed first; only then was the original sandbox appointment cancelled.");
        }
      }));
    }
  } else if (journey.stage === "intake") {
    if (journey.onboarding_missing?.length) {
      const note = document.createElement("p");
      note.textContent = `Waiting for: ${journey.onboarding_missing.join(", ")}. Answer in chat to continue.`;
      controls.append(note);
    } else {
      controls.textContent = "Intake is complete. Preparing current-plan hospital options.";
    }
  } else if (journey.stage === "compare") {
    controls.textContent = "Comparing hospitals under your current coverage.";
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
    controls.textContent = "Plan switching is outside this hospital-booking demo. Your current coverage is unchanged.";
  } else if (journey.stage === "transition") {
    controls.textContent = "Plan switching is outside this hospital-booking demo. Your current coverage is unchanged.";
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
    if (!journey.booking_slots?.length) {
      const prompt = document.createElement("p");
      prompt.textContent = "Tell the Booking Agent your date range and whether you prefer mornings or afternoons.";
      controls.append(prompt);
    } else if (!journey.selected_booking_slot) {
      const prompt = document.createElement("p");
      prompt.textContent = "Choose one of the Booking Agent's available slots below.";
      controls.append(prompt);
    } else {
      controls.append(button("Approve exact sandbox booking", async () => {
        const scope = journey.booking_consent_scope;
        if (!scope) throw new Error("The exact booking scope is unavailable.");
        await request(`/api/journeys/${journey.journey_id}/consents`, { method: "POST", body: JSON.stringify({ action: "book_appointment", scope, approved: true }) });
        journey = await request(`/api/journeys/${journey.journey_id}/actions`, { method: "POST", body: JSON.stringify({ action: "book_appointment", scope, idempotency_key: `ui-book-${journey.journey_id}-${journey.selected_booking_slot.slot_id}` }) });
        const scheduled = journey.booking_tasks?.some((task) => task.status === "scheduled");
        if (scheduled) {
          addMessage("The provider did not confirm immediately. I scheduled a retry for this exact approved slot and will update you here when it finishes.");
          void pollBookingTask();
        } else {
          addMessage("Sandbox appointment booked. The care journey is complete.");
        }
      }));
    }
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
    alternativeCoverage.innerHTML = `<div class="path-card"><span class="eyebrow">Informational only · not part of this demo</span><b>${escapeHtml(alt.plan_name)}</b><strong>${money(alt.estimated_annual_total)} estimated annual total</strong><small>Potential savings ${money(alt.estimated_annual_savings)} · modeled at ${escapeHtml(alt.hospital)} · switching requires a separate eligibility and enrollment journey. Continue above with your current plan.</small></div>`;
  } else {
    alternativeCoverage.textContent = "No alternative scenario yet.";
  }

  const booking = el("booking");
  if (!journey?.selected_care_path || !["book", "complete"].includes(journey.stage)) {
    booking.textContent = "Select and verify a care path first.";
  } else if (journey.selected_booking_slot) {
    const slot = journey.selected_booking_slot;
    booking.innerHTML = `<div class="selected"><span class="eyebrow">Selected appointment</span><b>${localDateTime(slot.starts_at)}</b><small>${escapeHtml(slot.hospital)} · ${slot.duration_minutes} minutes · ${escapeHtml(slot.procedure_code)}</small></div>`;
  } else if (journey.booking_slots?.length) {
    booking.innerHTML = `<p class="notice">These are synthetic slots. Choosing one does not book it.</p><ul>${journey.booking_slots.map((slot) => `<li class="path-card"><span class="eyebrow">${slot.retry_demo ? "Retry demonstration slot" : "Available"}</span><b>${localDateTime(slot.starts_at)}</b><small>${escapeHtml(slot.hospital)} · ${slot.duration_minutes} minutes${slot.retry_demo ? " · first confirmation attempt will be delayed" : ""}</small><button type="button" data-slot-id="${escapeHtml(slot.slot_id)}">Choose this slot</button></li>`).join("")}</ul>`;
    booking.querySelectorAll("button[data-slot-id]").forEach((node) => {
      node.onclick = () => run(async () => {
        journey = await request(`/api/journeys/${journey.journey_id}/booking/slots/${encodeURIComponent(node.dataset.slotId)}/select`, { method: "POST" });
        addMessage(`You selected ${localDateTime(journey.selected_booking_slot.starts_at)}. Review and approve the exact booking in Journey controls.`);
      });
    });
  } else {
    booking.innerHTML = `<p>The Booking Agent is ready. Try: <b>“2026-08-30 to 2026-09-15, any time.”</b></p>`;
  }
  if (journey?.booking_tasks?.length) {
    booking.insertAdjacentHTML("beforeend", journey.booking_tasks.map((task) => `<div class="task ${task.status === "completed" ? "completed" : ""}"><b>Booking task: ${escapeHtml(task.status)}</b><small>Attempts: ${task.attempts}${task.status === "scheduled" ? ` · next retry ${localDateTime(task.next_attempt_at)}` : ""}</small></div>`).join(""));
  }
  if (journey?.notifications?.length) {
    booking.insertAdjacentHTML("beforeend", journey.notifications.slice(-3).reverse().map((item) => `<div class="notification"><b>${escapeHtml(item.kind.replaceAll("_", " "))}</b><small>${escapeHtml(item.message)}</small></div>`).join(""));
  }
  el("receipts").innerHTML = journey?.receipts?.length
    ? `<ul>${journey.receipts.map((x) => `<li>${x.action}: ${x.status}</li>`).join("")}</ul>`
    : "No sandbox receipts yet.";
}

function renderCareContext() {
  const journeyList = el("journeys");
  if (!careContext.journeys?.length) {
    journeyList.textContent = "No care journeys yet.";
  } else {
    journeyList.innerHTML = careContext.journeys.map((item) => `<div class="journey-card ${journey?.journey_id === item.journey_id ? "active" : ""}"><span class="eyebrow">${escapeHtml(item.status)} · ${escapeHtml(item.stage)}</span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.journey_id)}</small><button type="button" data-journey-id="${escapeHtml(item.journey_id)}">${journey?.journey_id === item.journey_id ? "Active journey" : "Open journey"}</button></div>`).join("");
    journeyList.querySelectorAll("button[data-journey-id]").forEach((node) => {
      node.onclick = () => run(async () => {
        journey = await request(`/api/journeys/${encodeURIComponent(node.dataset.journeyId)}`);
        addMessage(`Switched to ${node.dataset.journeyId}.`);
      });
    });
  }
  const plan = el("agent-plan");
  plan.innerHTML = lastAgentPlan
    ? `<div class="agent-plan"><span class="eyebrow">${escapeHtml(lastAgentPlan.intent)}</span><b>${escapeHtml(lastAgentPlan.correlation_id)}</b><code>${escapeHtml(lastAgentPlan.steps.join(" → "))}</code></div>`
    : "No message routed yet.";
}

async function run(work) {
  status.className = "";
  status.textContent = "Working…";
  try {
    await work();
    if (localStorage.getItem("abyss.token")) careContext = await request("/api/care-context");
    status.textContent = journey ? `Stage: ${journey.stage}` : "Ready";
    render();
  } catch (error) {
    status.className = "error";
    status.textContent = `Error: ${error.message}`;
  }
}

async function pollBookingTask() {
  for (let attempt = 0; attempt < 12 && (journey?.stage === "book" || journey?.reschedule_pending); attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      journey = await request(`/api/journeys/${journey.journey_id}`);
      render();
      const task = journey.booking_tasks?.slice(-1)[0];
      if (journey.stage === "complete" && !journey.reschedule_pending) {
        addMessage(journey.notifications?.slice(-1)[0]?.message || "The scheduled booking task completed.");
        status.textContent = "Booking confirmed";
        return;
      }
      if (task?.status === "needs_user_action") {
        addMessage(journey.notifications?.slice(-1)[0]?.message || "The booking task needs your attention.");
        status.textContent = "Booking needs attention";
        return;
      }
    } catch (error) {
      status.className = "error";
      status.textContent = `Booking status check failed: ${error.message}`;
      return;
    }
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
    const result = await request("/api/care-agent/messages", { method: "POST", body: JSON.stringify({ text, active_journey_id: journey?.journey_id || null }) });
    lastAgentPlan = result.plan;
    careContext = result.context;
    if (result.journey) journey = result.journey;
    addMessage(result.reply);
  });
};

render();
