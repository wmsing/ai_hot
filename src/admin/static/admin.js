const state = {
  tab: "hot",
  hotItems: [],
  digestDay: "",
  digestItems: [],
  editContext: null,
  hotTopicsLlmBusy: false,
  digestLlmBusy: false,
  digestSpeakBusy: false,
  globalJobBusy: false,
  activeHotJobId: null,
  hotSelectedUrls: new Set(),
  digestSelectedKeys: new Set(),
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

function summaryCell(text) {
  const raw = String(text ?? "").trim();
  if (!raw) return "—";
  const titleAttr = raw.length > 120 ? ` title="${esc(raw)}"` : "";
  const preview = raw.length > 120 ? `${raw.slice(0, 120)}…` : raw;
  return `<span class="cell-summary"${titleAttr}>${esc(preview)}</span>`;
}

function feedLabel(item) {
  const bits = [];
  if (item.source) bits.push(item.source);
  if (Array.isArray(item.sources) && item.sources.length) {
    bits.push(item.sources.join(", "));
  }
  return bits.join(" · ") || "—";
}

function audioStatusBadge(lang, audio) {
  const status = audio?.sync_status || (audio?.exists ? "ok" : "missing");
  const label = status === "ok" ? lang : status === "stale" ? `${lang} stale` : "—";
  const cls = status === "ok" ? "ok" : status === "stale" ? "stale" : "no";
  const title = status === "stale" ? "口播过期，需重新生成" : "";
  return `<span class="badge ${cls}"${title ? ` title="${esc(title)}"` : ""}>${esc(label)}</span>`;
}

function audioCell(audioEn, audioZh) {
  const badges = [
    audioStatusBadge("EN", audioEn),
    audioStatusBadge("ZH", audioZh),
  ].join("");
  const parts = [`<div class="audio-badges">${badges}</div>`];
  if (audioEn?.exists) {
    parts.push(`<a class="audio-link" href="${esc(audioEn.play_url)}" target="_blank" rel="noopener">EN</a>`);
    parts.push(`<audio controls preload="none" src="${esc(audioEn.play_url)}"></audio>`);
  }
  if (audioZh?.exists) {
    parts.push(`<a class="audio-link" href="${esc(audioZh.play_url)}" target="_blank" rel="noopener">ZH</a>`);
    parts.push(`<audio controls preload="none" src="${esc(audioZh.play_url)}"></audio>`);
  }
  const hasAudio = audioEn?.exists || audioZh?.exists;
  const allMissing = (audioEn?.sync_status || "missing") === "missing" && (audioZh?.sync_status || "missing") === "missing";
  if (!hasAudio && allMissing) {
    return `<div class="audio-cell">${badges}</div>`;
  }
  return `<div class="audio-cell">${parts.join("")}</div>`;
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
  updateHotSelectionUi();
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
  updateDigestSelectionUi();
}

function setDigestSpeakBusy(busy, label = "口播 mp3 生成中…") {
  state.digestSpeakBusy = busy;
  setPanelBusy("panel-digest", "digest-speak-busy-overlay", "digest-speak-busy-label", busy, label);
  updateDigestSelectionUi();
}

function setGlobalJobBusy(busy, label = "") {
  state.globalJobBusy = busy;
  ["btn-pull", "btn-build", "btn-publish"].forEach((id) => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = busy;
  });
  if (label) setJobStatus(label);
}

function needsTitleZh(item) {
  const zh = (item.title_zh || "").trim();
  return !zh;
}

function needsDigestTitleZh(item) {
  const zh = (item.title_zh || "").trim();
  const en = (item.title_en || "").trim();
  if (!en) return false;
  if (!zh) return true;
  return !/[\u4e00-\u9fff]/.test(zh);
}

function needsDigestSummaryZh(item) {
  const zh = (item.summary_zh || "").trim();
  const en = (item.summary_en || "").trim();
  if (!en) return false;
  if (!zh) return true;
  return !/[\u4e00-\u9fff]/.test(zh);
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

function pruneHotSelection() {
  const urls = new Set(state.hotItems.map((item) => item.url));
  state.hotSelectedUrls = new Set(
    [...state.hotSelectedUrls].filter((url) => urls.has(url)),
  );
}

function digestRowKey(item) {
  const archiveDay = item.archive_day || state.digestDay;
  return `${archiveDay}:${item.index}`;
}

function parseDigestRowKey(key) {
  const splitAt = key.lastIndexOf(":");
  return {
    archiveDay: key.slice(0, splitAt),
    index: Number(key.slice(splitAt + 1)),
  };
}

function findDigestItem(key) {
  const { archiveDay, index } = parseDigestRowKey(key);
  return state.digestItems.find(
    (item) => (item.archive_day || state.digestDay) === archiveDay && item.index === index,
  );
}

function selectedDigestItems() {
  return [...state.digestSelectedKeys]
    .map((key) => findDigestItem(key))
    .filter(Boolean);
}

function groupDigestItemsByArchive(items) {
  const groups = new Map();
  items.forEach((item) => {
    const archiveDay = item.archive_day || state.digestDay;
    if (!groups.has(archiveDay)) groups.set(archiveDay, []);
    groups.get(archiveDay).push(item.index);
  });
  return groups;
}

async function latestArchiveDay() {
  const days = await api("/api/digests/days");
  return days[0] || state.digestDay;
}

function pruneDigestSelection() {
  const keys = new Set(state.digestItems.map((item) => digestRowKey(item)));
  state.digestSelectedKeys = new Set(
    [...state.digestSelectedKeys].filter((key) => keys.has(key)),
  );
}

function updateHotSelectionUi() {
  const n = state.hotSelectedUrls.size;
  const busy = state.hotTopicsLlmBusy;
  const zhBtn = $("#btn-hot-adhd-zh-selected");
  const enBtn = $("#btn-hot-adhd-en-selected");
  if (zhBtn) {
    zhBtn.disabled = n === 0 || busy;
    zhBtn.textContent = n ? `ADHD 选中 (${n})` : "ADHD 选中";
  }
  if (enBtn) {
    enBtn.disabled = n === 0 || busy;
    enBtn.textContent = n ? `ADHD Selected (${n})` : "ADHD Selected";
  }
  const selectAll = $("#hot-select-all");
  if (selectAll && state.hotItems.length) {
    selectAll.checked = n > 0 && n === state.hotItems.length;
    selectAll.indeterminate = n > 0 && n < state.hotItems.length;
  }
}

function updateDigestSelectionUi() {
  const n = state.digestSelectedKeys.size;
  const busy = state.digestLlmBusy || state.digestSpeakBusy;
  const btn = $("#btn-digest-adhd-selected");
  if (btn) {
    btn.disabled = n === 0 || busy;
    btn.textContent = n ? `ADHD 选中 (${n})` : "ADHD 选中";
  }
  const speakBtn = $("#btn-digest-speak-selected");
  if (speakBtn) {
    speakBtn.disabled = n === 0 || busy;
    speakBtn.textContent = n ? `生成选中 mp3 (${n})` : "生成选中 mp3";
  }
  const staleBtn = $("#btn-digest-speak-stale");
  if (staleBtn) staleBtn.disabled = busy;
  const selectAll = $("#digest-select-all");
  if (selectAll && state.digestItems.length) {
    selectAll.checked = n > 0 && n === state.digestItems.length;
    selectAll.indeterminate = n > 0 && n < state.digestItems.length;
  }
}

async function loadHotTopics() {
  const data = await api("/api/hot-topics");
  state.hotItems = data.items || [];
  pruneHotSelection();
  renderHotTopics();
  updateHotSelectionUi();
}

function renderHotTopics() {
  const tbody = $("#hot-tbody");
  tbody.innerHTML = state.hotItems
    .map(
      (item) => `
    <tr>
      <td class="col-check">
        <input type="checkbox" class="hot-row-check" data-hot-check="${esc(item.url)}" ${
          state.hotSelectedUrls.has(item.url) ? "checked" : ""
        } aria-label="选择条目" />
      </td>
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
        ${hasHotAdhd(item) ? `<button class="btn" data-hot-copy-digest='${esc(item.url)}' title="复制到 Digest 归档">→Digest</button>` : ""}
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
  tbody.querySelectorAll("[data-hot-copy-digest]").forEach((btn) => {
    btn.addEventListener("click", () => copyHotToDigest(btn.dataset.hotCopyDigest));
  });
  tbody.querySelectorAll("[data-hot-del]").forEach((btn) => {
    btn.addEventListener("click", () => deleteHot(btn.dataset.hotDel));
  });
  tbody.querySelectorAll(".hot-row-check").forEach((box) => {
    box.addEventListener("change", () => {
      if (box.checked) state.hotSelectedUrls.add(box.dataset.hotCheck);
      else state.hotSelectedUrls.delete(box.dataset.hotCheck);
      updateHotSelectionUi();
    });
  });
  updateHotSelectionUi();
}

async function loadDigestDays() {
  const days = await api("/api/digest-timeline/days");
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
  const data = await api(`/api/digest-timeline/${state.digestDay}`);
  state.digestItems = data.items || [];
  pruneDigestSelection();
  renderDigest();
  updateDigestSelectionUi();
}

function renderDigest() {
  const tbody = $("#digest-tbody");
  tbody.innerHTML = state.digestItems
    .map(
      (item) => `
    <tr>
      <td class="col-check">
        <input type="checkbox" class="digest-row-check" data-digest-check="${esc(digestRowKey(item))}" ${
          state.digestSelectedKeys.has(digestRowKey(item)) ? "checked" : ""
        } aria-label="选择条目 #${item.index}" />
      </td>
      <td>${item.index}</td>
      <td class="cell-feed">${esc(item.source || "—")}</td>
      <td class="cell-title">${esc(item.title_en)}</td>
      <td class="cell-title">${esc(item.title_zh)}</td>
      <td>${summaryCell(item.summary_en)}</td>
      <td>${summaryCell(item.summary_zh)}</td>
      <td class="cell-url">${esc(item.url)}</td>
      <td>${audioCell(item.audio_en, item.audio_zh)}</td>
      <td><span class="badge ${item.has_adhd ? "ok" : "no"}">${item.has_adhd ? "yes" : "no"}</span>${item.hot_topic_match && !item.has_adhd ? ' <span class="badge stale" title="热搜已有 ADHD">热搜✓</span>' : ""}</td>
      <td class="row-actions">
        <button class="btn" data-digest-edit="${esc(digestRowKey(item))}">编辑</button>
        ${item.can_copy_hot_adhd ? `<button class="btn" data-digest-copy-hot-adhd="${esc(digestRowKey(item))}" title="从今日热搜复制 ADHD">复制ADHD</button>` : ""}
        <button class="btn" data-digest-adhd="${esc(digestRowKey(item))}">ADHD</button>
        <button class="btn danger" data-digest-del="${esc(digestRowKey(item))}">删</button>
      </td>
    </tr>`
    )
    .join("");

  tbody.querySelectorAll("[data-digest-edit]").forEach((btn) => {
    btn.addEventListener("click", () => openDigestEdit(btn.dataset.digestEdit));
  });
  tbody.querySelectorAll("[data-digest-copy-hot-adhd]").forEach((btn) => {
    btn.addEventListener("click", () => copyDigestHotAdhd(btn.dataset.digestCopyHotAdhd));
  });
  tbody.querySelectorAll("[data-digest-adhd]").forEach((btn) => {
    btn.addEventListener("click", () => runDigestAdhd(btn.dataset.digestAdhd));
  });
  tbody.querySelectorAll("[data-digest-del]").forEach((btn) => {
    btn.addEventListener("click", () => deleteDigest(btn.dataset.digestDel));
  });
  tbody.querySelectorAll(".digest-row-check").forEach((box) => {
    box.addEventListener("change", () => {
      const key = box.dataset.digestCheck;
      if (box.checked) state.digestSelectedKeys.add(key);
      else state.digestSelectedKeys.delete(key);
      updateDigestSelectionUi();
    });
  });
  updateDigestSelectionUi();
}

function openDialog(title, fields, onSave) {
  state.editContext = { onSave };
  $("#edit-title").textContent = title;
  const container = $("#edit-fields");
  container.replaceChildren();
  for (const f of fields) {
    const label = document.createElement("label");
    const caption = document.createElement("span");
    caption.textContent = f.label;
    label.appendChild(caption);
    let input;
    if (f.type === "textarea") {
      input = document.createElement("textarea");
      input.rows = f.rows || (String(f.name).includes("summary") ? 12 : 5);
      input.className = "textarea-multiline";
      input.value = f.value ?? "";
    } else {
      input = document.createElement("input");
      input.value = f.value ?? "";
      if (f.required) input.required = true;
    }
    input.name = f.name;
    label.appendChild(input);
    container.appendChild(label);
  }
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

async function copyHotToDigest(url) {
  if (state.hotTopicsLlmBusy) return;
  const day = await latestArchiveDay();
  try {
    const result = await api("/api/hot-topics/items/copy-to-digest", {
      method: "POST",
      body: JSON.stringify({ url, day }),
    });
    const action = result.created ? "新增" : "更新";
    setJobStatus(`${action} Digest ${result.day} #${result.index}`);
    if (state.tab === "digest" && state.digestDay === result.day) {
      await loadDigest();
    }
  } catch (err) {
    setJobStatus(err.message || String(err));
  }
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

async function runDigestTranslateTitles(indices = null) {
  if (state.digestLlmBusy) {
    setJobStatus("Digest LLM 任务进行中，请稍后再试");
    return;
  }
  if (!state.digestDay) {
    setJobStatus("请先选择日期");
    return;
  }
  const pending = indices
    || state.digestItems.filter(needsDigestTitleZh).map((item) => item.index);
  if (!pending.length) {
    setJobStatus("无需翻译的标题");
    return;
  }
  setDigestLlmBusy(true, `翻译标题 (${pending.length})…`);
  try {
    const job = await api(`/api/digest-timeline/${state.digestDay}/translate-titles`, {
      method: "POST",
      body: JSON.stringify({ indices: indices || null }),
    });
    const result = await pollJob(job.id, `翻译标题 (${pending.length})`, 300);
    const changed = result?.result?.changed ?? 0;
    if (result.status !== "cancelled") {
      setJobStatus(`翻译完成：${changed} 条`);
    }
    await loadDigest();
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setDigestLlmBusy(false);
  }
}

async function runDigestTranslateSummaries(indices = null) {
  if (state.digestLlmBusy) {
    setJobStatus("Digest LLM 任务进行中，请稍后再试");
    return;
  }
  if (!state.digestDay) {
    setJobStatus("请先选择日期");
    return;
  }
  const pending = indices
    || state.digestItems.filter(needsDigestSummaryZh).map((item) => item.index);
  if (!pending.length) {
    setJobStatus("无需翻译的摘要");
    return;
  }
  setDigestLlmBusy(true, `翻译摘要 (${pending.length})…`);
  try {
    const job = await api(`/api/digest-timeline/${state.digestDay}/translate-summaries`, {
      method: "POST",
      body: JSON.stringify({ indices: indices || null }),
    });
    const result = await pollJob(job.id, `翻译摘要 (${pending.length})`, 300);
    const changed = result?.result?.changed ?? 0;
    if (result.status !== "cancelled") {
      setJobStatus(`摘要翻译完成：${changed} 条`);
    }
    await loadDigest();
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setDigestLlmBusy(false);
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

async function runHotAdhdSelected(lang) {
  if (state.hotTopicsLlmBusy) {
    setJobStatus("热搜 LLM 任务进行中，请稍后再试");
    return;
  }
  const urls = [...state.hotSelectedUrls];
  if (!urls.length) {
    setJobStatus("请先勾选条目");
    return;
  }
  const label = lang === "zh" ? `ADHD 选中 (${urls.length})` : `ADHD Selected (${urls.length})`;
  setHotTopicsLlmBusy(true, `${label} 生成中…`);
  try {
    const job = await api("/api/hot-topics/items/adhd-all", {
      method: "POST",
      body: JSON.stringify({ urls, force: false, lang }),
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

function openDigestEdit(key) {
  if (state.digestLlmBusy) return;
  const item = findDigestItem(key);
  if (!item) return;
  const { archiveDay, index } = parseDigestRowKey(key);
  openDialog(
    `编辑 Digest #${index}`,
    [
      { name: "title_en", label: "title_en", value: item.title_en },
      { name: "title_zh", label: "title_zh", value: item.title_zh },
      { name: "url", label: "url", value: item.url },
      { name: "source", label: "feed (source)", value: item.source },
      { name: "published", label: "published", value: item.published },
      { name: "score_line", label: "score_line", value: item.score_line },
      { name: "summary_en", label: "summary_en", value: item.summary_en, type: "textarea" },
      { name: "summary_zh", label: "summary_zh", value: item.summary_zh, type: "textarea" },
    ],
    async (data) => {
      await api(`/api/digests/${archiveDay}/items/${index}`, {
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
      { name: "source", label: "feed (source)", value: "manual" },
      { name: "summary_en", label: "summary_en", value: "", type: "textarea" },
      { name: "summary_zh", label: "summary_zh", value: "", type: "textarea" },
    ],
    async (data) => {
      const archiveDay = await latestArchiveDay();
      await api(`/api/digests/${archiveDay}/items`, {
        method: "POST",
        body: JSON.stringify(data),
      });
      await loadDigest();
    }
  );
}

async function deleteDigest(key) {
  if (state.digestLlmBusy) return;
  const { archiveDay, index } = parseDigestRowKey(key);
  if (!confirm(`删除 #${index} ?`)) return;
  await api(`/api/digests/${archiveDay}/items/${index}`, { method: "DELETE" });
  await loadDigest();
}

async function confirmDigestAudioWarning(actionLabel) {
  if (state.tab !== "digest" || !state.digestDay) return true;
  const groups = groupDigestItemsByArchive(state.digestItems);
  let stale = 0;
  let missing = 0;
  for (const archiveDay of groups.keys()) {
    const status = await api(`/api/digests/${archiveDay}/audio-status`);
    stale += status.stale_count || 0;
    missing += status.missing_count || 0;
  }
  const total = stale + missing;
  if (!total) return true;
  return confirm(
    `有 ${total} 条口播 mp3 未更新（stale ${stale} / missing ${missing}），${actionLabel}将使用旧音频或无声。继续？`
  );
}

async function runDigestSpeakStale() {
  if (state.digestSpeakBusy || state.digestLlmBusy) {
    setJobStatus("Digest 任务进行中，请稍后再试");
    return;
  }
  if (!state.digestDay) return;
  const groups = groupDigestItemsByArchive(state.digestItems);
  if (!groups.size) return;
  setDigestSpeakBusy(true, "生成过期 mp3…");
  try {
    let generated = 0;
    for (const [archiveDay, indices] of groups) {
      const job = await api(`/api/digests/${archiveDay}/items/speak`, {
        method: "POST",
        body: JSON.stringify({ indices, force: false }),
      });
      const result = await pollJob(job.id, `生成过期 mp3 (${archiveDay})`, 600);
      generated += result?.result?.generated ?? 0;
    }
    setJobStatus(`生成过期 mp3 完成：${generated} 条`);
    await loadDigest();
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setDigestSpeakBusy(false);
  }
}

async function runDigestSpeakSelected() {
  if (state.digestSpeakBusy || state.digestLlmBusy) {
    setJobStatus("Digest 任务进行中，请稍后再试");
    return;
  }
  const items = selectedDigestItems();
  if (!items.length) {
    setJobStatus("请先勾选条目");
    return;
  }
  const label = `生成选中 mp3 (${items.length})`;
  setDigestSpeakBusy(true, `${label}…`);
  try {
    let generated = 0;
    for (const [archiveDay, indices] of groupDigestItemsByArchive(items)) {
      const job = await api(`/api/digests/${archiveDay}/items/speak`, {
        method: "POST",
        body: JSON.stringify({ indices, force: true }),
      });
      const result = await pollJob(job.id, `${label} (${archiveDay})`, 600);
      generated += result?.result?.generated ?? 0;
    }
    setJobStatus(`${label} 完成：${generated} 条`);
    await loadDigest();
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setDigestSpeakBusy(false);
  }
}

async function copyDigestHotAdhd(key) {
  if (state.digestLlmBusy || state.digestSpeakBusy) return;
  const { archiveDay, index } = parseDigestRowKey(key);
  try {
    const result = await api(
      `/api/digests/${archiveDay}/items/${index}/copy-hot-adhd`,
      { method: "POST" },
    );
    setJobStatus(`已从热搜复制 ADHD → #${result.index}`);
    await loadDigest();
  } catch (err) {
    setJobStatus(err.message || String(err));
  }
}

async function runDigestAdhdSelected() {
  if (state.digestLlmBusy) {
    setJobStatus("Digest LLM 任务进行中，请稍后再试");
    return;
  }
  const items = selectedDigestItems();
  if (!items.length) {
    setJobStatus("请先勾选条目");
    return;
  }
  const label = `ADHD 选中 (${items.length})`;
  setDigestLlmBusy(true, `${label} 生成中…`);
  try {
    let changed = 0;
    for (const [archiveDay, indices] of groupDigestItemsByArchive(items)) {
      const job = await api(`/api/digests/${archiveDay}/items/adhd-batch`, {
        method: "POST",
        body: JSON.stringify({ indices, force: true }),
      });
      const result = await pollJob(job.id, `${label} (${archiveDay})`, 600);
      changed += result?.result?.changed ?? 0;
    }
    setJobStatus(`${label} 完成：${changed} 条`);
    await loadDigest();
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setDigestLlmBusy(false);
  }
}

async function runDigestAdhd(key) {
  if (state.digestLlmBusy) {
    setJobStatus("Digest LLM 任务进行中，请稍后再试");
    return;
  }
  const { archiveDay, index } = parseDigestRowKey(key);
  setDigestLlmBusy(true, `Digest #${index} ADHD 生成中…`);
  try {
    const job = await api(`/api/digests/${archiveDay}/items/${index}/adhd`, {
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

async function runPull() {
  if (state.globalJobBusy) return;
  const ok = confirm(
    "将从 HN/RSS 等拉取热搜与 digest，并归档到 content/。\n\n会覆盖当日 digest 归档文件，是否继续？",
  );
  if (!ok) return;
  setGlobalJobBusy(true, "拉取数据…");
  try {
    const job = await api("/api/pull", { method: "POST", body: JSON.stringify({}) });
    const result = await pollJob(job.id, "拉取数据", 300);
    const payload = result?.result || {};
    if (result?.status !== "cancelled") {
      setJobStatus(
        `拉取完成：热搜 ${payload.hot_topics_count ?? 0} 条 · digest ${payload.digest_selected ?? 0} 条`,
      );
    }
    if (state.tab === "hot") await loadHotTopics();
    if (state.tab === "digest") {
      await loadDigestDays();
      await loadDigest();
    }
  } catch (err) {
    setJobStatus(err.message || String(err));
  } finally {
    setGlobalJobBusy(false);
  }
}

async function runBuild() {
  if (state.globalJobBusy) return;
  if (!(await confirmDigestAudioWarning("重建站点"))) return;
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
  if (!(await confirmDigestAudioWarning("发布推送"))) return;
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

function parseRoute() {
  const parts = window.location.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  if (parts[0] === "digest") {
    return { tab: "digest", day: parts[1] || "" };
  }
  return { tab: "hot", day: "" };
}

function routePath(tab, day) {
  if (tab === "digest") {
    return day ? `/digest/${encodeURIComponent(day)}` : "/digest";
  }
  return "/";
}

function syncRoute(tab, day = "", { replace = false } = {}) {
  const path = routePath(tab, day);
  const url = path + window.location.search;
  const payload = { tab, day: tab === "digest" ? day : "" };
  if (replace) {
    history.replaceState(payload, "", url);
  } else {
    history.pushState(payload, "", url);
  }
}

function switchTab(tab, { sync = true, replace = false } = {}) {
  state.tab = tab;
  document.querySelectorAll(".tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === tab);
  });
  document.querySelectorAll(".panel").forEach((el) => {
    el.classList.toggle("active", el.id === `panel-${tab}`);
  });
  if (sync) {
    syncRoute(tab, tab === "digest" ? state.digestDay : "", { replace });
  }
}

function applyRoute(route, { sync = false } = {}) {
  state.tab = route.tab;
  if (route.day) state.digestDay = route.day;
  switchTab(route.tab, { sync });
  const select = $("#digest-day");
  if (select && state.digestDay) select.value = state.digestDay;
  if (route.tab === "digest") return loadDigest();
  return Promise.resolve();
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
  btn.addEventListener("click", async () => {
    const tab = btn.dataset.tab;
    switchTab(tab);
    if (tab === "digest") {
      try {
        if (!state.digestDay) await loadDigestDays();
        await loadDigest();
      } catch (err) {
        setJobStatus(err.message || String(err));
      }
    }
  });
});

window.addEventListener("popstate", (e) => {
  const route = e.state || parseRoute();
  applyRoute(route).catch((err) => setJobStatus(err.message || String(err)));
});

$("#btn-hot-refresh").addEventListener("click", loadHotTopics);
$("#btn-hot-add").addEventListener("click", openHotAdd);
$("#btn-hot-translate-all").addEventListener("click", () => runHotTranslateTitles());
$("#btn-hot-adhd-zh-all").addEventListener("click", () => runHotAdhdAll("zh"));
$("#btn-hot-adhd-en-all").addEventListener("click", () => runHotAdhdAll("en"));
$("#btn-hot-adhd-zh-selected").addEventListener("click", () => runHotAdhdSelected("zh"));
$("#btn-hot-adhd-en-selected").addEventListener("click", () => runHotAdhdSelected("en"));
$("#btn-hot-stop").addEventListener("click", () => cancelActiveHotJob());
$("#hot-select-all").addEventListener("change", (e) => {
  if (e.target.checked) {
    state.hotItems.forEach((item) => state.hotSelectedUrls.add(item.url));
  } else {
    state.hotSelectedUrls.clear();
  }
  renderHotTopics();
});
$("#btn-digest-refresh").addEventListener("click", loadDigest);
$("#btn-digest-add").addEventListener("click", openDigestAdd);
$("#btn-digest-translate-all").addEventListener("click", () => runDigestTranslateTitles());
$("#btn-digest-translate-summaries").addEventListener("click", () => runDigestTranslateSummaries());
$("#btn-digest-adhd-selected").addEventListener("click", () => runDigestAdhdSelected());
$("#btn-digest-speak-stale").addEventListener("click", () => runDigestSpeakStale());
$("#btn-digest-speak-selected").addEventListener("click", () => runDigestSpeakSelected());
$("#digest-select-all").addEventListener("change", (e) => {
  if (e.target.checked) {
    state.digestItems.forEach((item) => state.digestSelectedKeys.add(digestRowKey(item)));
  } else {
    state.digestSelectedKeys.clear();
  }
  renderDigest();
});
$("#btn-pull").addEventListener("click", runPull);
$("#btn-build").addEventListener("click", runBuild);
$("#btn-publish").addEventListener("click", runPublish);

$("#digest-day").addEventListener("change", async (e) => {
  state.digestDay = e.target.value;
  state.digestSelectedKeys.clear();
  syncRoute("digest", state.digestDay);
  await loadDigest();
});

async function boot() {
  const route = parseRoute();
  state.tab = route.tab;
  if (route.day) state.digestDay = route.day;
  switchTab(route.tab, { sync: false });
  try {
    await loadMeta();
    await loadHotTopics();
    await loadDigestDays();
    if (state.digestDay) $("#digest-day").value = state.digestDay;
    if (route.tab === "digest") {
      await loadDigest();
    }
    syncRoute(state.tab, state.digestDay, { replace: true });
  } catch (err) {
    setJobStatus(`加载失败: ${err.message || err}`);
  }
}

boot();
