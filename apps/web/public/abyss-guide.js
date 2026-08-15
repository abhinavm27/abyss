(() => {
  const poses = {
    idle: ["idle", "I'm right here when you need me."],
    listen: ["listen", "I'm listening."],
    dive: ["think", "Diving into the details…"],
    answer: ["present", "Let's make this clear."],
    celebrate: ["celebrate", "Nice—you found your next step!"],
    concern: ["reassure", "No worries. We can figure this out."],
  };
  const guide = document.createElement("aside");
  guide.className = "abyss-guide";
  guide.dataset.abyssGuide = "";
  guide.setAttribute("aria-live", "polite");
  guide.innerHTML = '<span class="abyss-guide__bubble is-visible"></span><button type="button" class="abyss-guide__button" aria-label="Talk to ABYSS"><img alt="" draggable="false" class="abyss-sprite"></button>';
  document.body.append(guide);
  const bubble = guide.querySelector(".abyss-guide__bubble");
  const image = guide.querySelector(".abyss-sprite");
  let timer;
  function react(pose) {
    clearTimeout(timer);
    const [file, copy] = poses[pose];
    guide.dataset.pose = pose;
    image.src = `/mascot/approved/abyss-${file}.png`;
    bubble.textContent = copy;
    bubble.classList.add("is-visible");
    timer = setTimeout(() => bubble.classList.remove("is-visible"), 2400);
  }
  function poseFor(target) {
    const words = `${target.getAttribute("aria-label") || ""} ${target.textContent || ""}`.toLowerCase();
    if (/voice|mic|listen|ask out loud/.test(words)) return "listen";
    if (/search|cost|price|compare|check/.test(words)) return "dive";
    if (/save|finish|continue|done|select|choose/.test(words)) return "celebrate";
    if (/back|close|delete|sign out|replace|error/.test(words)) return "concern";
    return "answer";
  }
  document.addEventListener("pointerdown", (event) => {
    const target = event.target.closest?.("button, a, input, select, textarea, [role='button']");
    if (target && !target.closest("[data-abyss-guide]")) react(poseFor(target));
  }, true);
  document.addEventListener("focusin", (event) => {
    if (event.target.matches?.("input, textarea")) react("listen");
  }, true);
  guide.querySelector("button").addEventListener("click", () => react("listen"));
  react("idle");
})();
