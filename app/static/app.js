// LinkPlease Front-end Control Center

let pollingInterval = null;

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  fetchStats();
  fetchRules();
  fetchActivity();

  // Poll stats and activity every 2 seconds
  pollingInterval = setInterval(() => {
    fetchStats();
    fetchActivity();
  }, 2000);

  // Setup form listeners
  setupRuleForm();
  setupSimForm();
  setupTruthChecker();

  document.getElementById("btn-manual-refresh").addEventListener("click", () => {
    fetchStats();
    fetchRules();
    fetchActivity();
  });

  // Pre-fill simulation URL with current origin
  const origin = window.location.origin;
  document.getElementById("sim-url").value = `${origin}/webhook`;
});

// Fetch and display live /stats
async function fetchStats() {
  try {
    const res = await fetch("/stats");
    if (!res.ok) return;
    const stats = await res.json();

    document.getElementById("stat-sent").innerText = stats.sent.toLocaleString();
    document.getElementById("stat-queued").innerText = stats.queued.toLocaleString();
    document.getElementById("stat-blocked").innerText = stats.duplicates_blocked.toLocaleString();
    document.getElementById("stat-failed").innerText = stats.failed.toLocaleString();
  } catch (err) {
    console.error("Error fetching stats:", err);
  }
}

// Fetch and render configured rules
async function fetchRules() {
  try {
    const res = await fetch("/rules");
    if (!res.ok) return;
    const rules = await res.json();

    const container = document.getElementById("rules-container");
    const countBadge = document.getElementById("rules-count");
    countBadge.innerText = `${rules.length} active`;

    if (rules.length === 0) {
      container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 1rem; font-size: 0.85rem;">No rules configured yet. Create one above!</div>`;
      return;
    }

    container.innerHTML = rules.map(r => `
      <div class="rule-item">
        <div>
          <span class="rule-keyword">${escapeHtml(r.keyword)}</span>
          <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">ID: ${escapeHtml(r.rule_id)}</div>
        </div>
        <div class="rule-message" title="${escapeHtml(r.dm_message)}">${escapeHtml(r.dm_message)}</div>
      </div>
    `).join("");
  } catch (err) {
    console.error("Error fetching rules:", err);
  }
}

// Fetch recent jobs activity
async function fetchActivity() {
  try {
    const res = await fetch("/api/activity?limit=15");
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById("jobs-tbody");

    if (!data.jobs || data.jobs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No DM jobs in queue yet. Trigger a webhook or simulation!</td></tr>`;
      return;
    }

    tbody.innerHTML = data.jobs.map(job => {
      let badgeClass = "badge-queued";
      if (job.status === "sent") badgeClass = "badge-sent";
      else if (job.status === "failed") badgeClass = "badge-failed";
      else if (job.status === "waiting_reconciliation") badgeClass = "badge-reconciling";
      else if (job.status === "cancelled") badgeClass = "badge-cancelled";

      return `
        <tr>
          <td><code style="font-size: 0.75rem;">${job.job_id.substring(0, 12)}...</code></td>
          <td><b>${escapeHtml(job.user_id)}</b></td>
          <td><code>${escapeHtml(job.comment_id)}</code></td>
          <td><code>${job.dm_id || "—"}</code></td>
          <td><span class="badge ${badgeClass}">${job.status}</span></td>
          <td>${job.retry_count} / ${job.max_retries}</td>
          <td style="color: var(--text-muted); font-size: 0.75rem; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            ${escapeHtml(job.last_error || "—")}
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Error fetching activity:", err);
  }
}

// Setup Rule Creation Form
function setupRuleForm() {
  const form = document.getElementById("rule-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const keywordInput = document.getElementById("rule-keyword");
    const messageInput = document.getElementById("rule-message");
    const btn = document.getElementById("btn-save-rule");

    const keyword = keywordInput.value.trim();
    const dm_message = messageInput.value.trim();

    if (!keyword || !dm_message) return;

    btn.disabled = true;
    btn.innerText = "Creating...";

    try {
      const res = await fetch("/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword, dm_message })
      });

      if (res.ok) {
        keywordInput.value = "";
        messageInput.value = "";
        await fetchRules();
      } else {
        const err = await res.json();
        alert(`Failed to create rule: ${err.detail || res.statusText}`);
      }
    } catch (err) {
      alert(`Network error creating rule: ${err}`);
    } finally {
      btn.disabled = false;
      btn.innerText = "+ Create Rule (POST /rules)";
    }
  });
}

// Setup Simulation Trigger Form
function setupSimForm() {
  const form = document.getElementById("sim-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const webhookUrl = document.getElementById("sim-url").value.trim();
    const count = parseInt(document.getElementById("sim-count").value, 10);
    const duration = parseInt(document.getElementById("sim-duration").value, 10);
    const btn = document.getElementById("btn-start-sim");

    btn.disabled = true;
    btn.innerText = "Starting Simulation...";

    try {
      const res = await fetch("/api/simulate/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ webhook_url: webhookUrl, count, duration_seconds: duration })
      });

      const data = await res.json();
      if (res.ok) {
        alert(`Simulation started! Run ID: ${data.run_id}`);
        document.getElementById("truth-run-id").value = data.run_id;
        fetchStats();
      } else {
        alert(`Simulation trigger error: ${data.detail || JSON.stringify(data)}`);
      }
    } catch (err) {
      alert(`Failed to contact simulation API: ${err}`);
    } finally {
      btn.disabled = false;
      btn.innerText = "⚡ Trigger Simulation (POST /v1/simulate/start)";
    }
  });
}

// Setup Truth Checker
function setupTruthChecker() {
  const btn = document.getElementById("btn-check-truth");
  btn.addEventListener("click", async () => {
    const runId = document.getElementById("truth-run-id").value.trim();
    const box = document.getElementById("truth-result");

    if (!runId) {
      alert("Please enter a Run ID.");
      return;
    }

    btn.disabled = true;
    btn.innerText = "Fetching...";
    box.style.display = "block";
    box.innerText = "Loading ground truth data from Pseudogram...";

    try {
      const res = await fetch(`/api/simulate/${encodeURIComponent(runId)}/truth`);
      const data = await res.json();
      box.innerText = JSON.stringify(data, null, 2);
    } catch (err) {
      box.innerText = `Error fetching truth: ${err}`;
    } finally {
      btn.disabled = false;
      btn.innerText = "Check Truth";
    }
  });
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.innerText = text;
  return div.innerHTML;
}
