// Same-origin keeps API and WebSocket requests valid when the demo is served
// over HTTPS. Vite proxies both paths to the private backend.
const API = "";
const DEMO = { email: "demo@example.test", password: "demo-password-123" };
let journey = null;
let careContext = { journeys: [], appointments: [], scheduled_tasks: [] };
let lastAgentPlan = null;

const el = (id) => document.getElementById(id);
const messages = el("messages");
const input = el("input");
const status = el("status");
const voiceButton = el("voice");
const voiceLabel = el("voice-label");
const voiceStatus = el("voice-status");
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

const VOICE_WORKLET = `
class ChatLabPCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.inputRate = sampleRate; this.outputRate = 16000;
    this.ratio = this.inputRate / this.outputRate; this.phase = 0; this.prev = 0;
    this.samples = []; this.target = 2048; this.active = false; this.silence = 0;
    this.prebuffer = []; this.muted = false;
    this.port.onmessage = (event) => { this.muted = Boolean(event.data && event.data.muted); };
  }
  chunk(value) { this.port.postMessage(value.buffer, [value.buffer]); }
  event(type) { this.port.postMessage({ type }); }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i += 1) {
      const current = channel[i];
      while (this.phase < 1) {
        this.samples.push(this.prev + (current - this.prev) * this.phase);
        this.phase += this.ratio;
      }
      this.phase -= 1; this.prev = current;
    }
    while (this.samples.length >= this.target) {
      const values = this.samples.splice(0, this.target);
      if (this.muted) { this.active = false; this.silence = 0; this.prebuffer = []; continue; }
      let sum = 0;
      for (let i = 0; i < values.length; i += 1) sum += values[i] * values[i];
      const rms = Math.sqrt(sum / values.length);
      let ended = false;
      if (this.active) {
        if (rms < 0.008) {
          this.silence += 1;
          if (this.silence >= 10) {
            this.active = false; this.silence = 0; ended = true; this.event('speech_end');
          }
        } else this.silence = 0;
      } else if (rms >= 0.015) {
        this.active = true; this.silence = 0; this.event('speech_start');
      }
      const pcm = new Int16Array(values.length);
      for (let i = 0; i < values.length; i += 1) {
        const sample = Math.max(-1, Math.min(1, values[i]));
        pcm[i] = sample < 0 ? sample * 32768 : sample * 32767;
      }
      if (this.active) {
        while (this.prebuffer.length) this.chunk(this.prebuffer.shift());
        this.chunk(pcm);
      } else if (!ended) {
        this.prebuffer.push(pcm);
        while (this.prebuffer.length > 2) this.prebuffer.shift();
      }
    }
    return true;
  }
}
registerProcessor('chatlab-pcm', ChatLabPCMProcessor);
`;

let voiceSocket = null;
let voiceStream = null;
let voiceContext = null;
let voiceWorklet = null;
let playbackContext = null;
let nextPlaybackAt = 0;
let voiceOutputRate = 22050;
let voiceSpeaking = false;

function voiceState(label, active = true, meter = false) {
  voiceButton.classList.toggle("active", active);
  voiceButton.setAttribute("aria-pressed", String(active));
  voiceLabel.textContent = active ? "Stop voice" : "Start voice";
  voiceStatus.innerHTML = `${meter ? '<span class="voice-meter" aria-hidden="true"><i></i><i></i><i></i></span>' : ""}<span>${escapeHtml(label)}</span>`;
}

function bytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let value = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    value += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(value);
}

function playVoiceChunk(encoded) {
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const sampleCount = Math.floor(bytes.byteLength / 2);
  if (!sampleCount) return;
  if (!playbackContext || playbackContext.state === "closed") {
    playbackContext = new AudioContext({ sampleRate: voiceOutputRate });
    nextPlaybackAt = 0;
  }
  const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, sampleCount);
  const buffer = playbackContext.createBuffer(1, pcm.length, voiceOutputRate);
  const output = buffer.getChannelData(0);
  for (let i = 0; i < pcm.length; i += 1) output[i] = pcm[i] / 32768;
  const source = playbackContext.createBufferSource();
  source.buffer = buffer;
  const gain = playbackContext.createGain(); gain.gain.value = 1.5;
  source.connect(gain).connect(playbackContext.destination);
  const startsAt = Math.max(playbackContext.currentTime, nextPlaybackAt);
  nextPlaybackAt = startsAt + buffer.duration;
  source.start(startsAt);
  voiceSpeaking = true;
  voiceWorklet?.port.postMessage({ muted: true });
  voiceState("ABYSS is speaking", true, true);
}

function stopVoice() {
  voiceSocket?.close(); voiceSocket = null;
  voiceWorklet?.disconnect(); voiceWorklet = null;
  voiceStream?.getTracks().forEach((track) => track.stop()); voiceStream = null;
  void voiceContext?.close().catch(() => {}); voiceContext = null;
  void playbackContext?.close().catch(() => {}); playbackContext = null;
  nextPlaybackAt = 0; voiceSpeaking = false;
  voiceState("Voice uses NVIDIA Parakeet, Nemotron, and Magpie.", false);
}

async function startVoice() {
  const token = localStorage.getItem("abyss.token");
  if (!token) throw new Error("Sign in as the synthetic demo user first.");
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new Error("Microphone access requires the HTTPS Chat Lab URL.");
  }
  voiceState("Connecting NVIDIA speech services…", true, true);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  voiceSocket = socket;
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "ready") {
      voiceOutputRate = Number(message.output_sample_rate) || 22050;
      voiceState("Listening — speak naturally, then pause.", true, true);
    } else if (message.type === "listening") {
      voiceState("Listening…", true, true);
    } else if (message.type === "processing") {
      const labels = { transcribing: "Parakeet is transcribing…", reasoning: "Journey Agent is reasoning…", speaking: "Magpie is preparing speech…" };
      voiceState(labels[message.stage] || "Working…", true, true);
    } else if (message.type === "transcript") {
      addMessage(message.text, message.role === "user" ? "user" : "assistant");
    } else if (message.type === "audio") {
      playVoiceChunk(message.data);
    } else if (message.type === "ui" && message.target === "care_journey") {
      const result = message.payload;
      lastAgentPlan = result.plan;
      careContext = result.context;
      if (result.journey) journey = result.journey;
      render();
    } else if (message.type === "turn_complete") {
      const waitMs = playbackContext ? Math.max(0, (nextPlaybackAt - playbackContext.currentTime) * 1000) + 200 : 0;
      window.setTimeout(() => {
        if (voiceSocket !== socket) return;
        voiceSpeaking = false;
        voiceWorklet?.port.postMessage({ muted: false });
        voiceState("Listening — speak naturally, then pause.", true, true);
      }, waitMs);
    } else if (message.type === "error") {
      status.className = "error";
      status.textContent = `Voice error: ${message.message}`;
      stopVoice();
    }
  };
  socket.onclose = () => { if (voiceSocket === socket) stopVoice(); };
  socket.onerror = () => {
    status.className = "error";
    status.textContent = "Could not reach the NVIDIA voice gateway.";
  };
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    window.setTimeout(() => reject(new Error("Voice connection timed out.")), 10000);
  });
  socket.send(JSON.stringify({ type: "auth", token }));
  voiceStream = await navigator.mediaDevices.getUserMedia({ audio: {
    echoCancellation: true, noiseSuppression: true, autoGainControl: true,
  }});
  voiceContext = new AudioContext();
  if (voiceContext.state === "suspended") await voiceContext.resume();
  const url = URL.createObjectURL(new Blob([VOICE_WORKLET], { type: "application/javascript" }));
  await voiceContext.audioWorklet.addModule(url); URL.revokeObjectURL(url);
  voiceWorklet = new AudioWorkletNode(voiceContext, "chatlab-pcm");
  voiceWorklet.port.onmessage = (event) => {
    if (!voiceSocket || voiceSocket.readyState !== WebSocket.OPEN || voiceSpeaking) return;
    if (event.data instanceof ArrayBuffer) {
      voiceSocket.send(JSON.stringify({ type: "audio", data: bytesToBase64(event.data) }));
    } else if (event.data?.type === "speech_start" || event.data?.type === "speech_end") {
      voiceSocket.send(JSON.stringify({ type: event.data.type }));
    }
  };
  voiceContext.createMediaStreamSource(voiceStream).connect(voiceWorklet);
  const silent = voiceContext.createGain(); silent.gain.value = 0;
  voiceWorklet.connect(silent).connect(voiceContext.destination);
}

voiceButton.onclick = () => {
  if (voiceSocket) stopVoice();
  else startVoice().catch((error) => {
    stopVoice(); status.className = "error"; status.textContent = `Voice error: ${error.message}`;
  });
};

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
