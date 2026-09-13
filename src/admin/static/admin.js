const state = {
  tab: "hot",
  hotItems: [],
  digestDay: "",
  digestItems: [],
  editContext: null,
  hotTopicsLlmBusy: false,
  digestLlmBusy: false,
  globalJobBusy: false,
  activeHotJobId: null,
};

const $ = (sel) => document.querySelector(sel);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function hasHotAdhdZh(item) {
  const zh = (item.summary_zh || "").trim();
  return zh.includes("一句话总结") || zh.includes("🔥 核心亮点");
}

function hasHotAdhdEn(item) {
  const en = (item.summary_en || "").trim();
  return en.includes("One-liner") || en.includes("🔥 Key takeaways");
}

function hasHotAdhd(item) {
  return hasHotAdhdZh(item) || hasHotAdhdEn(item);
}

function adhdStatusLabel(item) {
  const zh = hasHotAdhdZh(item) ? "zh✓" : "zh–";
  const en = hasHotAdhdEn(item) ? "en✓" : "en–";
  return `${zh} ${en}`;
}

function esc(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function feedLabel(item) {
  const bits = [];
  if (item.source) bits.push(item.source);
  if (Array.isArray(item.sources) && item.sources.length) {
    bits.push(item.sources.join(", "));
  }
  return bits.join(" · ") || "—";
}

function audioCell(audioEn, audioZh) {
  const parts = [];
  if (audioEn?.exists) {
    parts.push(`<a class="audio-link" href="${esc(audioEn.play_url)}" target="_blank" rel="noopener">EN</a>`);
    parts.push(`<audio controls preload="none" src="${esc(audioEn.play_url)}"></audio>`);
  }
  if (audioZh?.exists) {
    parts.push(`<a class="audio-link" href="${esc(audioZh.play_url)}" target="_blank" rel="noopener">ZH</a>`);
    parts.push(`<audio controls preload="none" src="${esc(audioZh.play_url)}"></audio>`);
  }
  return parts.length ? `<div class="audio-cell">${parts.join("")}</div>` : '<span class="badge no">—</span>';
}

function setJobStatus(text) {
  $("#job-status").textContent = text || "";
}

function setPanelBusy(panelId, overlayId, labelId, busy, label) {
  const panel = document.getElementById(panelId);
  const overlay = document.getElementById(overlayId);
  const labelEl = document.getElementById(labelId);
  if (!panel || !overlay) return;
  panel.classList.toggle("is-busy", busy);
  overlay.classList.toggle("hidden", !busy);
  overlay.setAttribute("aria-hidden", busy ? "false" : "true");
  const hotOpen = !document.getElementById("hot-busy-overlay")?.classList.contains("hidden");
  const digestOpen = !document.getElementById("digest-busy-overlay")?.classList.contains("hidden");
  document.body.classList.toggle("panel-busy-open", hotOpen || digestOpen);
  if (labelEl && label) labelEl.textContent = label;
  panel.querySelectorAll("button, select, input, textarea, a").forEach((el) => {
    if (busy) {
      if (!el.dataset.busyPrevDisabled) {
        el.dataset.busyPrevDisabled = el.disabled ? "1" : "0";
      }
      el.disabled = true;
      el.setAttribute("aria-disabled", "true");
    } else if (el.dataset.busyPrevDisabled) {
      el.disabled = el.dataset.busyPrevDisabled === "1";
      delete el.dataset.busyPrevDisabled;
      el.removeAttribute("aria-disabled");
    }
  });
}

function setHotTopicsLlmBusy(busy, label = "热搜 LLM 任务进行中…") {
  state.hotTopicsLlmBusy = busy;
  setPanelBusy("panel-hot", "hot-busy-overlay", "hot-busy-label", busy, label);
  const stopBtn = $("#btn-hot-stop");
  if (stopBtn) {
    stopBtn.classList.toggle("hidden", !busy);
    if (busy) {
      stopBtn.disabled = false;
      stopBtn.removeAttribute("aria-disabled");
    }
  }
  if (!busy) state.activeHotJobId = null;
}

function setDigestLlmBusy(busy, label = "Digest LLM 任务进行中…") {
  state.digestLlmBusy = busy;
  setPanelBusy("panel-digest", "digest-busy-overlay", "digest-busy-label", busy, label);
}

function setGlobalJobBusy(busy, label = "") {
  state.globalJobBusy = busy;
  ["btn-build", "btn-publish"].forEach((id) => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = busy;
  });
  if (label) setJobStatus(label);
}

function needsTitleZh(item) {
  const zh = (item.title_zh || "").trim();
  return !zh;
}

function needsHotAdhdZh(item) {
  return !hasHotAdhdZh(item);
}

function needsHotAdhdEn(item) {
  return !hasHotAdhdEn(item);
}

async function pollJob(jobId, label, maxLoops = 120) {
  setJobStatus(`${label}…`);
  for (let i = 0; i < maxLoops; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const job = await api(`/api/jobs/${jobId}`);
    if (job.status === "running" || job.status === "pending") {
      setJobStatus(`${label} (${job.status})`);
      continue;
    }
    if (job.status === "done") {
      setJobStatus(`${label} 完成`);
      return job;
    }
    if (job.status === "cancelled") {
      const changed = job.result?.changed ?? 0;
      setJobStatus(changed ? `${label} 已停止（已完成 ${changed} 条）` : `${label} 已停止`);
      return job;
    }
    throw new Error(job.message || `${label} 失败`);
  }
  throw new Error(`${label} 超时`);
}

async function loadMeta() {
  const meta = await api("/api/meta");
  $("#meta-line").textContent = `热搜: ${meta.hot_topics_path} · Digest: ${meta.content_digests_dir}`;
  setHotTopicsLlmBusy(Boolean(meta.hot_topics_llm_busy));
}

async function loadHotTopics() {
  const data = await api("/api/hot-topics");
  state.hotItems = data.items || [];
  renderHotTopics();
}

function renderHotTopics() {
  const tbody = $("#hot-tbody");
  tbody.innerHTML = state.hotItems
    .map(
      (item) => `
    <tr>
      <td>${esc(item.heat?.toFixed?.(2) ?? item.heat)}</td>
      <td class="cell-title">${esc(item.title)}</td>
      <td class="cell-title">${esc(item.title_zh || "")}</td>
      <td class="cell-feed">${esc(feedLabel(item))}</td>
      <td><span class="badge ${hasHotAdhd(item) ? "ok" : "no"}">${adhdStatusLabel(item)}</span></td>
      <td class="row-actions">
        <button class="btn" data-hot-edit='${esc(item.url)}'>编辑</button>
        ${needsTitleZh(item) ? `<button class="btn" data-hot-translate='${esc(item.url)}'>译</button>` : ""}
        ${needsHotAdhdZh(item) ? `<button class="btn" data-hot-adhd-zh='${esc(item.url)}'>摘要</button>` : ""}
        ${needsHotAdhdEn(item) ? `<button class="btn" data-hot-adhd-en='${esc(item.url)}'>EN</button>` : ""}
        <button class="btn danger" data-hot-del='${esc(item.url)}'>删</button>
      </td>
    </tr>`
    )
    .join("");

  tbody.querySelectorAll("[data-hot-edit]").forEach((btn) => {
    btn.addEventListener("click", () => openHotEdit(btn.dataset.hotEdit));
  });
  tbody.querySelectorAll("[data-hot-translate]").forEach((btn) => {
    btn.addEventListener("click", () => runHotTranslateTitles([btn.dataset.hotTranslate]));
  });
  tbody.querySelectorAll("[data-hot-adhd-zh]").forEach((btn) => {
    btn.addEventListener("click", () => runHotAdhd(btn.dataset.hotAdhdZh, "zh"));
  });
  tbody.querySelectorAll("[data-hot-adhd-en]").forEach((btn) => {
    btn.addEventListener("click", () => runHotAdhd(btn.dataset.hotAdhdEn, "en"));
  });
  tbody.querySelectorAll("[data-hot-del]").forEach((btn) => {
    btn.addEventListener("click", () => deleteHot(btn.dataset.hotDel));
  });
}

async function loadDigestDays() {
  const days = await api("/api/digests/days");
  const select = $("#digest-day");
  select.innerHTML = days.map((d) => `<option value="${esc(d)}">${esc(d)}</option>`).join("");
  if (!state.digestDay && days.length) state.digestDay = days[0];
  if (state.digestDay) select.value = state.digestDay;
}

async function loadDigest() {
  if (!state.digestDay) {
    $("#digest-tbody").innerHTML = "";
    return;
  }
  const data = await api(`/api/digests/${state.digestDay}`);
  state.digestItems = data.items || [];
  renderDigest();
}

function renderDigest() {
  const tbody = $("#digest-tbody");
  tbody.innerHTML = state.digestItems
    .map(
      (item) => `
    <tr>
      <td>${item.index}</td>
      <td>${esc(item.tag || "—")}</td>
      <td class="cell-feed">${esc(item.source || "—")}</td>
      <td class="cell-title">${esc(item.title_en)}</td>
      <td class="cell-title">${esc(item.title_zh)}</td>
      <td class="cell-url">${esc(item.url)}</td>
      <td>${audioCell(item.audio_en, item.audio_zh)}</td>
      <td><span class="badge ${item.has_adhd ? "ok" : "no"}">${item.has_adhd ? "yes" : "no"}</span></td>
      <td class="row-actions">
        <button class="btn" data-digest-edit="${item.index}">编辑</button>
        <button class="btn" data-digest-adhd="${item.index}">ADHD</button>
        <button class="btn danger" data-digest-del="${item.index}">删</button>
      </td>
    </tr>`
    )
    .join("");

  tbody.querySelectorAll("[data-digest-edit]").forEach((btn) => {
    btn.addEventListener("click", () => openDigestEdit(Number(btn.dataset.digestEdit)));
  });
  tbody.querySelectorAll("[data-digest-adhd]").forEach((btn) => {
    btn.addEventListener("click", () => runDigestAdhd(Number(btn.dataset.digestAdhd)));
  });
  tbody.querySelectorAll("[data-digest-del]").forEach((btn) => {
    btn.addEventListener("click", () => deleteDigest(Number(btn.dataset.digestDel)));
  });
}

function openDialog(title, fields, onSave) {
  state.editContext = { onSave };
  $("#edit-title").textContent = title;
  const container = $("#edit-fields");
  container.innerHTML = fields
    .map(
      (f) => `
    <label>
      ${esc(f.label)}
      ${f.type === "textarea" ? `<textarea name="${f.name}">${esc(f.value || "")}</textarea>` : `<input name="${f.name}" value="${esc(f.value || "")}" ${f.required ? "required" : ""} />`}
    </label>`
    )
    .join("");
  $("#edit-dialog").showModal();
}

function readForm() {
  const data = {};
  $("#edit-fields").querySelectorAll("input, textarea").forEach((el) => {
    data[el.name] = el.value;
  });
  return data;
}

function openHotEdit(url) {
  if (state.hotTopicsLlmBusy) return;
  const item = state.hotItems.find((it) => it.url === url);
  if (!item) return;
  openDialog(
    "编辑热搜",
    [
      { name: "url", label: "url", value: item.url, required: true },
      { name: "title", label: "title", value: item.title },
      { name: "title_zh", label: "title_zh", value: item.title_zh || "" },
      { name: "source", label: "source", value: item.source || "" },
      { name: "heat", label: "heat", value: String(item.heat ?? 0) },
      { name: "summary", label: "summary", value: item.summary || "", type: "textarea" },
      { name: "summary_en", label: "summary_en", value: item.summary_en || "", type: "textarea" },
      { name: "summary_zh", label: "summary_zh", value: item.summary_zh || "", type: "textarea" },
    ],
    async (data) => {
      await api("/api/hot-topics/items", {
        method: "PUT",
        body: JSON.stringify({
          url: data.url,
          title: data.title,
          title_zh: data.title_zh || null,
          source: data.source,
          heat: Number(data.heat),
          summary: data.summary || null,
          summary_en: data.summary_en || null,
          summary_zh: data.summary_zh || null,
        }),
      });
      await loadHotTopics();
    }
  );
}

function openHotAdd() {
  if (state.hotTopicsLlmBusy) return;
  openDialog(
    "新增热搜",
    [
      { name: "url", label: "url", value: "", required: true },
      { name: "title", label: "title", value: "", required: true },
      { name: "title_zh", label: "title_zh", value: "" },
      { name: "source", label: "source", value: "manual" },
      { name: "heat", label: "heat", value: "1" },
      { name: "summary", label: "summary", value: "", type: "textarea" },
    ],
    async (data) => {
      await api("/api/hot-topics", {
        method: "POST",
        body: JSON.stringify({
          url: data.url,
          title: data.title,
          title_zh: data.title_zh || null,
          source: data.source,
          heat: Number(data.heat),
          summary: data.summary || null,
          sources: [],
          reason: "admin manual",
        }),
      });
      await loadHotTopics();
    }
  );
}

async function deleteHot(url) {
  if (state.hotTopicsLlmBusy) return;
  if (!confirm(`删除 ${url} ?`)) return;
  await api("/api/hot-topics/items", { method: "DELETE", body: JSON.stringify({ url }) });
  await loadHotTopics();
}

async function cancelActiveHotJob() {
  if (!state.activeHotJobId) return;
  try {
    await api(`/api/jobs/${state.activeHotJobId}/cancel`, { method: "POST" });
    setJobStatus("正在停止…");
  } catch (err) {
    setJobStatus(err.message || String(err));
  }
}

async function runHotTranslateTitles(urls = null) {
  if (state.hotTopicsLlmBusy) {
    setJobStatus("热搜 LLM 任务进行中，请稍后再试");
    return;
  }
  const pending = urls || state.hotItems.filter(needsTitleZh).map((item) => item.url);
  if (!pending.length) {
    setJobStatus("无需翻译的标题");
    return;
  }
  setHotTopicsLlmBusy(true);
  try {
    const job = await api("/api/hot-topics/translate-titles", {
      method: "POST",
      body: JSON.stringify({ urls: urls || null }),
    });
    state.activeHotJobId = job.id;
    const result = await pollJob(job.id, `翻译标题 (${pending.length})`, 300);
    const changed = result?.result?.changed ?? 0;
    setJobStatus(`翻译完成：${changed} 条`);
    await loadHotTopics();
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setHotTopicsLlmBusy(false);
  }
}

async function runHotAdhd(url, lang) {
  if (state.hotTopicsLlmBusy) {
    setJobStatus("热搜 LLM 任务进行中，请稍后再试");
    return;
  }
  const label = lang === "zh" ? "热搜 ADHD 摘要" : "热搜 ADHD Summary";
  setHotTopicsLlmBusy(true, `${label} 生成中…`);
  try {
    const job = await api("/api/hot-topics/items/adhd", {
      method: "POST",
      body: JSON.stringify({ url, force: false, lang }),
    });
    state.activeHotJobId = job.id;
    await pollJob(job.id, label, 180);
    await loadHotTopics();
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setHotTopicsLlmBusy(false);
  }
}

async function runHotAdhdAll(lang) {
  if (state.hotTopicsLlmBusy) {
    setJobStatus("热搜 LLM 任务进行中，请稍后再试");
    return;
  }
  const pending = state.hotItems.filter(
    lang === "zh" ? needsHotAdhdZh : needsHotAdhdEn,
  );
  if (!pending.length) {
    setJobStatus(lang === "zh" ? "无需中文 ADHD 摘要" : "无需英文 ADHD summary");
    return;
  }
  const label = lang === "zh" ? `ADHD 摘要 (${pending.length})` : `ADHD Summary (${pending.length})`;
  setHotTopicsLlmBusy(true, `${label} 生成中…`);
  try {
    const job = await api("/api/hot-topics/items/adhd-all", {
      method: "POST",
      body: JSON.stringify({ force: false, lang }),
    });
    state.activeHotJobId = job.id;
    const result = await pollJob(job.id, label, 600);
    const changed = result?.result?.changed ?? 0;
    if (result.status !== "cancelled") {
      setJobStatus(`${label} 完成：${changed} 条`);
    }
    await loadHotTopics();
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setHotTopicsLlmBusy(false);
  }
}

function openDigestEdit(index) {
  if (state.digestLlmBusy) return;
  const item = state.digestItems.find((it) => it.index === index);
  if (!item) return;
  openDialog(
    `编辑 Digest #${index}`,
    [
      { name: "title_en", label: "title_en", value: item.title_en },
      { name: "title_zh", label: "title_zh", value: item.title_zh },
      { name: "url", label: "url", value: item.url },
      { name: "tag", label: "tag", value: item.tag || "" },
      { name: "source", label: "feed (source)", value: item.source },
      { name: "published", label: "published", value: item.published },
      { name: "score_line", label: "score_line", value: item.score_line },
      { name: "summary_en", label: "summary_en", value: item.summary_en, type: "textarea" },
      { name: "summary_zh", label: "summary_zh", value: item.summary_zh, type: "textarea" },
    ],
    async (data) => {
      await api(`/api/digests/${state.digestDay}/items/${index}`, {
        method: "PUT",
        body: JSON.stringify(data),
      });
      await loadDigest();
    }
  );
}

function openDigestAdd() {
  if (state.digestLlmBusy) return;
  openDialog(
    "新增 Digest 条目",
    [
      { name: "title_en", label: "title_en", value: "", required: true },
      { name: "title_zh", label: "title_zh", value: "" },
      { name: "url", label: "url", value: "", required: true },
      { name: "tag", label: "tag", value: "" },
      { name: "source", label: "feed (source)", value: "manual" },
      { name: "summary_en", label: "summary_en", value: "", type: "textarea" },
      { name: "summary_zh", label: "summary_zh", value: "", type: "textarea" },
    ],
    async (data) => {
      await api(`/api/digests/${state.digestDay}/items`, {
        method: "POST",
        body: JSON.stringify(data),
      });
      await loadDigest();
    }
  );
}

async function deleteDigest(index) {
  if (state.digestLlmBusy) return;
  if (!confirm(`删除 #${index} ?`)) return;
  await api(`/api/digests/${state.digestDay}/items/${index}`, { method: "DELETE" });
  await loadDigest();
}

async function runDigestAdhd(index) {
  if (state.digestLlmBusy) {
    setJobStatus("Digest LLM 任务进行中，请稍后再试");
    return;
  }
  setDigestLlmBusy(true, `Digest #${index} ADHD 生成中…`);
  try {
    const job = await api(`/api/digests/${state.digestDay}/items/${index}/adhd`, {
      method: "POST",
      body: JSON.stringify({ force: true }),
    });
    await pollJob(job.id, "Digest ADHD", 180);
    await loadDigest();
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setDigestLlmBusy(false);
  }
}

async function runBuild() {
  if (state.globalJobBusy) return;
  setGlobalJobBusy(true, "重建站点…");
  try {
    const job = await api("/api/build", { method: "POST" });
    await pollJob(job.id, "重建站点");
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setGlobalJobBusy(false);
  }
}

async function runPublish() {
  if (state.globalJobBusy) return;
  setGlobalJobBusy(true);
  try {
    const status = await api("/api/publish/status");
    if (!status.has_changes) {
      setJobStatus("无 content 变更，无需推送");
      return;
    }
    const preview = (status.pending || []).slice(0, 8).join("\n");
    const more = (status.pending || []).length > 8 ? `\n…共 ${status.pending.length} 项` : "";
    const ok = confirm(`将提交并 push 以下 content 变更：\n\n${preview}${more}`);
    if (!ok) return;

    const job = await api("/api/publish", { method: "POST", body: JSON.stringify({}) });
    const result = await pollJob(job.id, "发布推送", 180);
    const commit = result?.result?.commit;
    if (result?.result?.committed) {
      setJobStatus(`已推送 commit ${commit || ""}`.trim());
    } else {
      setJobStatus(result?.result?.message || "无需推送");
    }
  } finally {
    setGlobalJobBusy(false);
  }
}

function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === tab);
  });
  document.querySelectorAll(".panel").forEach((el) => {
    el.classList.toggle("active", el.id === `panel-${tab}`);
  });
}

$("#edit-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ctx = state.editContext;
  if (!ctx) return;
  const data = readForm();
  try {
    await ctx.onSave(data);
    $("#edit-dialog").close();
  } catch (err) {
    alert(err.message || String(err));
  }
});

$("#btn-cancel").addEventListener("click", () => $("#edit-dialog").close());

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

$("#btn-hot-refresh").addEventListener("click", loadHotTopics);
$("#btn-hot-add").addEventListener("click", openHotAdd);
$("#btn-hot-translate-all").addEventListener("click", () => runHotTranslateTitles());
$("#btn-hot-adhd-zh-all").addEventListener("click", () => runHotAdhdAll("zh"));
$("#btn-hot-adhd-en-all").addEventListener("click", () => runHotAdhdAll("en"));
$("#btn-hot-stop").addEventListener("click", () => cancelActiveHotJob());
$("#btn-digest-refresh").addEventListener("click", loadDigest);
$("#btn-digest-add").addEventListener("click", openDigestAdd);
$("#btn-build").addEventListener("click", runBuild);
$("#btn-publish").addEventListener("click", runPublish);

$("#digest-day").addEventListener("change", async (e) => {
  state.digestDay = e.target.value;
  await loadDigest();
});

async function boot() {
  try {
    await loadMeta();
    await loadHotTopics();
    await loadDigestDays();
    await loadDigest();
  } catch (err) {
    setJobStatus(`加载失败: ${err.message || err}`);
  }
}

boot();
