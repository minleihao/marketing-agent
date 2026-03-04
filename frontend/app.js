async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `Request failed: ${res.status}`);
  }
  return data;
}

function parseJsonOrDefault(raw, defaultValue) {
  if (!raw || !raw.trim()) return defaultValue;
  return JSON.parse(raw);
}

async function loadKbList() {
  const selector = document.getElementById("kb_id");
  if (!selector) return;
  selector.innerHTML = "";
  const list = await api("/api/kb/list");
  for (const kb of list) {
    const option = document.createElement("option");
    option.value = kb.id;
    option.textContent = `${kb.id} (v${kb.version}) - ${kb.name}`;
    selector.appendChild(option);
  }
}

async function submitPrompt() {
  const prompt = document.getElementById("prompt")?.value || "";
  const channel = document.getElementById("channel")?.value || "";
  const product = document.getElementById("product")?.value || "";
  const audience = document.getElementById("audience")?.value || "";
  const objective = document.getElementById("objective")?.value || "";
  const kbId = document.getElementById("kb_id")?.value || "";

  const outputBox = document.getElementById("output");
  const violationsBox = document.getElementById("violations");
  outputBox.textContent = "Generating...";
  violationsBox.textContent = "";

  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        kb_id: kbId,
        tool_args: {
          channel,
          product,
          audience,
          objective,
        },
      }),
    });
    outputBox.textContent = data.output || "";
    violationsBox.textContent = (data.violations || []).join("\n") || "None";
  } catch (err) {
    outputBox.textContent = `Error: ${err.message}`;
  }
}

function getKbPayload() {
  const kbId = document.getElementById("kb-id").value.trim();
  return {
    id: kbId,
    name: document.getElementById("kb-name").value.trim(),
    version: 1,
    brand_voice: document.getElementById("brand-voice").value.trim(),
    positioning: parseJsonOrDefault(document.getElementById("positioning").value, {}),
    glossary: parseJsonOrDefault(document.getElementById("glossary").value, []),
    forbidden_words: parseJsonOrDefault(document.getElementById("forbidden").value, []),
    required_terms: [],
    claims_policy: parseJsonOrDefault(document.getElementById("claims").value, {}),
    examples: null,
    notes: document.getElementById("notes").value.trim() || null,
  };
}

async function saveKb(isUpdate) {
  const result = document.getElementById("kb-result");
  try {
    const payload = getKbPayload();
    const url = isUpdate ? `/api/kb/${payload.id}` : "/api/kb";
    const method = isUpdate ? "PUT" : "POST";
    const data = await api(url, {
      method,
      body: JSON.stringify(payload),
    });
    result.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    result.textContent = `Error: ${err.message}`;
  }
}

(function init() {
  const genBtn = document.getElementById("generate");
  if (genBtn) {
    genBtn.addEventListener("click", submitPrompt);
    loadKbList().catch((e) => {
      document.getElementById("output").textContent = `Failed to load KB list: ${e.message}`;
    });
  }

  const saveBtn = document.getElementById("save");
  if (saveBtn) {
    saveBtn.addEventListener("click", () => saveKb(false));
  }

  const updateBtn = document.getElementById("update");
  if (updateBtn) {
    updateBtn.addEventListener("click", () => saveKb(true));
  }
})();
