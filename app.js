const STATUS_ORDER = [
  "신규",
  "접촉중",
  "샘플 전달",
  "견적중",
  "계약 협의",
  "계약완료",
  "보류",
  "실패",
  "중복 검토",
];

const STATUS_BADGE = {
  신규: "light",
  접촉중: "mid",
  "샘플 전달": "outline",
  견적중: "outline",
  "계약 협의": "mid",
  계약완료: "dark",
  보류: "light",
  실패: "dark",
  "중복 검토": "dark",
};

const state = {
  me: null,
  users: [],
  accounts: [],
  activities: [],
  contracts: [],
  audit: [],
  today: "2026-07-05",
  selectedAccountId: null,
  currentView: "dashboard",
};

const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "요청을 처리하지 못했습니다.");
  }
  return payload;
}

function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function html(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showToast(message) {
  const toast = qs("#toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("is-visible"), 3500);
}

function currency(value) {
  return new Intl.NumberFormat("ko-KR", {
    style: "currency",
    currency: "KRW",
    maximumFractionDigits: 0,
  }).format(Number(value || 0));
}

function shortDate(value) {
  if (!value) return "-";
  const parts = value.slice(0, 10).split("-");
  if (parts.length !== 3) return value;
  return `${parts[1]}.${parts[2]}`;
}

function normalize(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[\s\-().]/g, "")
    .replace(/당구클럽|당구장|클럽|아카데미|동호회/g, "");
}

function phoneDigits(value) {
  return String(value || "").replace(/\D/g, "");
}

function daysBetween(from, to) {
  const oneDay = 24 * 60 * 60 * 1000;
  return Math.round((new Date(to) - new Date(from)) / oneDay);
}

function addDays(date, amount) {
  const next = new Date(date);
  next.setDate(next.getDate() + amount);
  return next.toISOString().slice(0, 10);
}

function user(id) {
  return state.users.find((item) => item.id === id) || { id, name: "-" };
}

function account(id) {
  return state.accounts.find((item) => item.id === id);
}

function isManager() {
  return state.me?.role === "manager";
}

function activeSalesUsers() {
  return state.users.filter((item) => item.role === "sales" && item.status === "active");
}

function salesUsersForDisplay() {
  return state.users.filter((item) => item.role === "sales");
}

function lastActivity(accountId) {
  return state.activities
    .filter((item) => item.accountId === accountId)
    .sort((a, b) => b.date.localeCompare(a.date))[0];
}

function duplicateScore(source, target) {
  if (!source || !target || source.id === target.id) return 0;
  let score = 0;
  const sourcePhone = phoneDigits(source.phone);
  const targetPhone = phoneDigits(target.phone);
  const sourceName = normalize(source.name);
  const targetName = normalize(target.name);
  const sourceAddress = normalize(source.address);
  const targetAddress = normalize(target.address);

  if (sourcePhone && sourcePhone.length >= 8 && sourcePhone === targetPhone) score += 60;
  if (sourceName && targetName && sourceName === targetName) score += 35;
  if (sourceName && targetName && (sourceName.includes(targetName) || targetName.includes(sourceName))) {
    score += 24;
  }
  if (
    sourceAddress &&
    targetAddress &&
    (sourceAddress.includes(targetAddress) || targetAddress.includes(sourceAddress))
  ) {
    score += 35;
  }
  if (source.region && source.region === target.region) score += 8;
  return Math.min(score, 100);
}

function duplicatePairs() {
  const pairs = [];
  for (let i = 0; i < state.accounts.length; i += 1) {
    for (let j = i + 1; j < state.accounts.length; j += 1) {
      const score = duplicateScore(state.accounts[i], state.accounts[j]);
      if (score >= 45) pairs.push({ left: state.accounts[i], right: state.accounts[j], score });
    }
  }
  return pairs.sort((a, b) => b.score - a.score);
}

function accountLockState(item) {
  const last = lastActivity(item.id);
  const lastDate = last?.date || item.createdAt;
  const inactiveDays = daysBetween(lastDate, state.today);
  const locked = item.lockUntil && item.lockUntil >= state.today;

  if (item.status === "중복 검토") return { label: "검토", className: "dark", detail: "관리자 확인 필요" };
  if (locked && inactiveDays <= 30) return { label: "유효", className: "dark", detail: `${shortDate(item.lockUntil)}까지` };
  if (inactiveDays > 30) return { label: "소홀", className: "outline", detail: `${inactiveDays}일 미활동` };
  return { label: "만료", className: "light", detail: "잠금 만료" };
}

function recognizedAmountForRep(repId, contracts = state.contracts) {
  return contracts.reduce((sum, contract) => {
    let amount = 0;
    if (contract.originatorId === repId) amount += contract.amount * (contract.shares.originator / 100);
    if (contract.closerId === repId) amount += contract.amount * (contract.shares.closer / 100);
    if (contract.managerId === repId) amount += contract.amount * (contract.shares.manager / 100);
    return sum + amount;
  }, 0);
}

function setSelectOptions(select, options, selectedValue) {
  const previous = selectedValue ?? select.value;
  select.innerHTML = options
    .map((option) => `<option value="${html(option.value)}">${html(option.label)}</option>`)
    .join("");
  if (options.some((option) => option.value === previous)) {
    select.value = previous;
  }
}

function setView(viewName) {
  if (!isManager() && viewName === "people") viewName = "dashboard";
  state.currentView = viewName;
  qsa(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === viewName));
  qsa(".view").forEach((view) => view.classList.toggle("is-visible", view.id === `${viewName}View`));
  qs("#viewTitle").textContent = qs(`#${viewName}View`)?.dataset.title || "대시보드";
}

function applyAuthState() {
  qs("#authScreen").classList.toggle("is-hidden", Boolean(state.me));
  qs("#appShell").classList.toggle("is-hidden", !state.me);
  if (!state.me) return;

  qs("#currentUserName").textContent = state.me.name;
  qs("#currentRole").textContent = state.me.role === "manager" ? "관리자" : "영업사원";
  qsa(".manager-only").forEach((item) => item.classList.toggle("is-hidden", !isManager()));
}

async function loadBootstrap() {
  const payload = await api("/api/bootstrap");
  Object.assign(state, payload);
  if (!state.selectedAccountId || !state.accounts.some((item) => item.id === state.selectedAccountId)) {
    state.selectedAccountId = state.accounts[0]?.id || null;
  }
  applyAuthState();
  renderAll();
}

async function checkSession() {
  try {
    await loadBootstrap();
    setView(state.currentView);
  } catch {
    state.me = null;
    applyAuthState();
  }
}

function hydrateControls() {
  const monthSet = new Set([
    state.today.slice(0, 7),
    ...state.activities.map((item) => item.date.slice(0, 7)),
    ...state.contracts.map((item) => item.date.slice(0, 7)),
  ]);
  setSelectOptions(
    qs("#dashboardMonth"),
    [...monthSet].sort().reverse().map((month) => ({ value: month, label: month })),
    qs("#dashboardMonth").value || state.today.slice(0, 7),
  );

  const ownerOptions = [
    { value: "all", label: "전체 담당자" },
    ...activeSalesUsers().map((item) => ({ value: item.id, label: item.name })),
  ];
  setSelectOptions(qs("#ownerFilter"), ownerOptions, qs("#ownerFilter").value || "all");
  setSelectOptions(
    qs("#statusFilter"),
    [{ value: "all", label: "전체 상태" }, ...STATUS_ORDER.map((status) => ({ value: status, label: status }))],
    qs("#statusFilter").value || "all",
  );

  const repOptions = activeSalesUsers().map((item) => ({ value: item.id, label: item.name }));
  const accountOptions = state.accounts.map((item) => ({
    value: item.id,
    label: `${item.name} · ${user(item.ownerId).name}`,
  }));

  qsa('select[name="repId"], select[name="ownerId"], select[name$="Id"]').forEach((select) => {
    if (select.name === "accountId") return;
    const defaultValue = isManager() ? select.value || state.me.id : state.me.id;
    setSelectOptions(select, repOptions, defaultValue);
    if (!isManager() && ["repId", "ownerId"].includes(select.name)) {
      select.value = state.me.id;
    }
  });

  qsa('select[name="accountId"]').forEach((select) => {
    setSelectOptions(select, accountOptions, select.value || state.selectedAccountId);
  });

  qs('#activityForm input[name="date"]').value ||= state.today;
  qs('#contractForm input[name="date"]').value ||= state.today;
}

function renderMetrics() {
  const month = qs("#dashboardMonth").value || state.today.slice(0, 7);
  const activities = state.activities.filter((item) => item.date.startsWith(month));
  const contracts = state.contracts.filter((item) => item.date.startsWith(month));
  const approvedAmount = contracts
    .filter((item) => item.status === "approved")
    .reduce((sum, item) => sum + Number(item.amount), 0);
  const pendingAmount = contracts
    .filter((item) => item.status === "pending")
    .reduce((sum, item) => sum + Number(item.amount), 0);
  const followups = state.activities.filter((item) => {
    return item.nextDate && item.nextDate >= state.today && item.nextDate <= addDays(state.today, 7);
  });

  const metrics = [
    { label: "이번 달 활동", value: `${activities.length}건`, sub: "서버 저장 기준" },
    { label: "관리 거래처", value: `${state.accounts.length}곳`, sub: "권한별 표시" },
    { label: "승인 계약", value: currency(approvedAmount), sub: `대기 ${currency(pendingAmount)}` },
    { label: "확인 필요", value: `${duplicatePairs().length + followups.length}건`, sub: "중복과 후속관리" },
  ];

  qs("#metricsGrid").innerHTML = metrics
    .map(
      (item) => `
        <article class="metric-card">
          <span>${html(item.label)}</span>
          <strong>${html(item.value)}</strong>
          <em>${html(item.sub)}</em>
        </article>
      `,
    )
    .join("");
}

function renderRepBoard() {
  const month = qs("#dashboardMonth").value || state.today.slice(0, 7);
  const reps = isManager() ? activeSalesUsers() : activeSalesUsers().filter((item) => item.id === state.me.id);
  qs("#repBoard").innerHTML =
    reps
      .map((rep) => {
        const repActivities = state.activities.filter((item) => item.repId === rep.id && item.date.startsWith(month));
        const repAccounts = state.accounts.filter((item) => item.ownerId === rep.id);
        const repContracts = state.contracts.filter((item) => {
          return item.date.startsWith(month) && [item.originatorId, item.closerId, item.managerId].includes(rep.id);
        });
        const recognized = recognizedAmountForRep(rep.id, repContracts);
        const percent = Math.min(100, Math.round((recognized / 6000000) * 100));
        return `
          <article class="rep-card">
            <div class="rep-head">
              <div class="row-actions">
                <div class="avatar">${html(rep.name.slice(0, 1))}</div>
                <div>
                  <strong>${html(rep.name)}</strong><br>
                  <span class="muted-text">${html(rep.region || "-")}</span>
                </div>
              </div>
              <span class="badge ${percent >= 70 ? "dark" : "light"}">${percent}%</span>
            </div>
            <div class="mini-stats">
              <div class="mini-stat"><span>활동</span><strong>${repActivities.length}</strong></div>
              <div class="mini-stat"><span>거래처</span><strong>${repAccounts.length}</strong></div>
              <div class="mini-stat"><span>계약</span><strong>${repContracts.length}</strong></div>
            </div>
            <div class="pipeline"><span style="width:${percent}%"></span></div>
            <strong>${currency(recognized)}</strong>
          </article>
        `;
      })
      .join("") || `<div class="empty-state"><strong>활동 영업사원 없음</strong><span>승인된 계정을 기다리고 있습니다.</span></div>`;
}

function renderDuplicates() {
  const pairs = duplicatePairs();
  qs("#duplicateList").innerHTML =
    pairs.length === 0
      ? `<div class="empty-state"><strong>중복 없음</strong><span>현재 확인할 항목이 없습니다.</span></div>`
      : pairs
          .slice(0, 6)
          .map(
            (pair) => `
              <div class="alert-item">
                <strong>${html(pair.left.name)} / ${html(pair.right.name)}</strong>
                <span>${pair.score}% 일치 · ${html(user(pair.left.ownerId).name)} / ${html(user(pair.right.ownerId).name)}</span>
              </div>
            `,
          )
          .join("");
}

function renderFollowups() {
  const followups = state.activities
    .filter((item) => item.nextDate && item.nextDate >= state.today && item.nextDate <= addDays(state.today, 7))
    .sort((a, b) => a.nextDate.localeCompare(b.nextDate));
  qs("#followupList").innerHTML =
    followups.length === 0
      ? `<div class="empty-state"><strong>후속 없음</strong><span>이번 주 일정이 없습니다.</span></div>`
      : followups
          .map((item) => {
            const target = account(item.accountId);
            return `
              <div class="task-item">
                <strong>${shortDate(item.nextDate)} · ${html(target?.name)}</strong>
                <span>${html(user(item.repId).name)} · ${html(item.nextAction || "후속 연락")}</span>
              </div>
            `;
          })
          .join("");
}

function renderRecentActivities() {
  qs("#recentActivityRows").innerHTML =
    state.activities
      .slice(0, 8)
      .map((item) => {
        const target = account(item.accountId);
        return `
          <tr>
            <td>${shortDate(item.date)}</td>
            <td>${html(user(item.repId).name)}</td>
            <td>${html(target?.name || "-")}</td>
            <td><span class="badge mid">${html(item.type)}</span></td>
            <td>${html(item.summary)}</td>
          </tr>
        `;
      })
      .join("") || `<tr><td colspan="5">활동 기록이 없습니다.</td></tr>`;
}

function filteredAccounts() {
  const search = normalize(qs("#accountSearch").value);
  const owner = qs("#ownerFilter").value;
  const status = qs("#statusFilter").value;
  return state.accounts.filter((item) => {
    const haystack = normalize(`${item.name} ${item.address} ${item.contactName} ${item.phone}`);
    return (!search || haystack.includes(search)) && (owner === "all" || item.ownerId === owner) && (status === "all" || item.status === status);
  });
}

function renderAccountRows() {
  qs("#accountRows").innerHTML =
    filteredAccounts()
      .sort((a, b) => a.name.localeCompare(b.name, "ko"))
      .map((item) => {
        const last = lastActivity(item.id);
        const lock = accountLockState(item);
        return `
          <tr class="selectable ${state.selectedAccountId === item.id ? "is-selected" : ""}" data-account-id="${html(item.id)}">
            <td><strong>${html(item.name)}</strong><br><span class="muted-text">${html(item.category)} · ${html(item.contactName || "-")}</span></td>
            <td>${html(item.region)}</td>
            <td>${html(user(item.ownerId).name)}</td>
            <td><span class="badge ${STATUS_BADGE[item.status] || "light"}">${html(item.status)}</span></td>
            <td>${last ? `${shortDate(last.date)} · ${html(last.type)}` : "-"}</td>
            <td><span class="badge ${lock.className}">${html(lock.label)}</span></td>
          </tr>
        `;
      })
      .join("") || `<tr><td colspan="6">표시할 거래처가 없습니다.</td></tr>`;
}

function renderAccountDetail() {
  const item = account(state.selectedAccountId);
  const panel = qs("#accountDetailPanel");
  if (!item) {
    panel.innerHTML = `<div class="empty-state"><strong>거래처 선택</strong><span>목록에서 한 곳을 선택하세요.</span></div>`;
    return;
  }
  const lock = accountLockState(item);
  const activities = state.activities.filter((activity) => activity.accountId === item.id);
  const duplicate = state.accounts
    .filter((candidate) => candidate.id !== item.id)
    .map((candidate) => ({ account: candidate, score: duplicateScore(item, candidate) }))
    .filter((candidate) => candidate.score >= 45)
    .sort((a, b) => b.score - a.score)[0];
  panel.innerHTML = `
    <div class="detail-stack">
      <div class="panel-header">
        <div>
          <h2>${html(item.name)}</h2>
          <p>${html(item.address)}</p>
        </div>
        <span class="badge ${STATUS_BADGE[item.status] || "light"}">${html(item.status)}</span>
      </div>
      <div class="info-grid">
        <div class="info-box"><span>담당</span><strong>${html(user(item.ownerId).name)}</strong></div>
        <div class="info-box"><span>최초 등록</span><strong>${html(user(item.originatorId).name)}</strong></div>
        <div class="info-box"><span>담당권</span><strong>${html(lock.label)} · ${html(lock.detail)}</strong></div>
        <div class="info-box"><span>예상 금액</span><strong>${currency(item.expectedAmount)}</strong></div>
        <div class="info-box"><span>담당자</span><strong>${html(item.contactName || "-")}</strong></div>
        <div class="info-box"><span>연락처</span><strong>${html(item.phone || "-")}</strong></div>
      </div>
      ${
        duplicate
          ? `<div class="alert-item"><strong>중복 의심 ${duplicate.score}%</strong><span>${html(duplicate.account.name)} · ${html(user(duplicate.account.ownerId).name)} 담당</span></div>`
          : ""
      }
      <div class="row-actions">
        <button class="small-button" data-account-action="advance-status" type="button">상태 변경</button>
        <button class="small-button" data-account-action="extend-lock" type="button">담당권 30일 연장</button>
      </div>
      <h3>활동 히스토리</h3>
      <div class="timeline">
        ${
          activities.length
            ? activities
                .map(
                  (activity) => `
                    <div class="timeline-item">
                      <strong>${shortDate(activity.date)} · ${html(activity.type)} · ${html(user(activity.repId).name)}</strong>
                      <span>${html(activity.summary)}</span>
                      <span>${html(activity.nextAction || "")}</span>
                    </div>
                  `,
                )
                .join("")
            : `<div class="empty-state"><strong>기록 없음</strong><span>아직 활동 기록이 없습니다.</span></div>`
        }
      </div>
    </div>
  `;
}

function renderPeople() {
  if (!isManager()) return;
  qs("#peopleRows").innerHTML =
    salesUsersForDisplay()
      .sort((a, b) => {
        const order = { pending: 0, active: 1, suspended: 2 };
        return (order[a.status] ?? 9) - (order[b.status] ?? 9) || a.name.localeCompare(b.name, "ko");
      })
      .map((person) => {
        const status =
          person.status === "pending"
            ? { label: "승인 대기", className: "outline" }
            : person.status === "suspended"
              ? { label: "중지", className: "light" }
              : { label: "활동중", className: "dark" };
        return `
          <tr>
            <td><strong>${html(person.name)}</strong><br><span class="muted-text">${html(person.workType || "-")} · 가입 ${shortDate(person.joinedAt)}</span></td>
            <td>${html(person.phone || "-")}<br><span class="muted-text">${html(person.email || "-")}</span></td>
            <td>${html(person.region || "-")}<br><span class="muted-text">${html(person.coverage || "-")}</span></td>
            <td>${html(person.bankName || "-")} · ${html(person.accountHolder || "-")}<br><span class="muted-text">${html(person.accountNumberMasked || "-")}</span></td>
            <td><span class="badge ${status.className}">${status.label}</span></td>
            <td>
              <div class="row-actions">
                ${
                  person.status !== "active"
                    ? `<button class="small-button" data-people-action="active" data-user-id="${html(person.id)}" type="button">승인</button>`
                    : `<button class="small-button" data-people-action="suspended" data-user-id="${html(person.id)}" type="button">중지</button>`
                }
              </div>
            </td>
          </tr>
        `;
      })
      .join("") || `<tr><td colspan="6">등록된 영업사원이 없습니다.</td></tr>`;
}

function renderContracts() {
  qs("#contractRows").innerHTML =
    state.contracts
      .map((contract) => {
        const target = account(contract.accountId);
        const allocation = [
          `발굴 ${user(contract.originatorId).name} ${contract.shares.originator}%`,
          `성사 ${user(contract.closerId).name} ${contract.shares.closer}%`,
          `관리 ${user(contract.managerId).name} ${contract.shares.manager}%`,
        ].join(" · ");
        return `
          <tr>
            <td>${shortDate(contract.date)}</td>
            <td>${html(target?.name || "-")}</td>
            <td>${currency(contract.amount)}</td>
            <td><span class="muted-text">${html(allocation)}</span></td>
            <td><span class="badge ${contract.status === "approved" ? "dark" : "outline"}">${contract.status === "approved" ? "승인" : "대기"}</span></td>
            <td>
              ${
                isManager() && contract.status !== "approved"
                  ? `<button class="small-button" data-contract-action="approve" data-contract-id="${html(contract.id)}" type="button">승인</button>`
                  : "-"
              }
            </td>
          </tr>
        `;
      })
      .join("") || `<tr><td colspan="6">등록된 계약이 없습니다.</td></tr>`;
}

function renderAudit() {
  qs("#auditList").innerHTML =
    state.audit
      .map(
        (item) => `
          <div class="audit-item">
            <strong>${html(item.date?.slice(0, 10) || "-")} · ${html(item.action)}</strong>
            <span>${html(user(item.actor_id).name)} · ${html(item.detail)}</span>
          </div>
        `,
      )
      .join("") || `<div class="empty-state"><strong>기록 없음</strong><span>감사 로그가 없습니다.</span></div>`;
}

function renderDuplicatePreview() {
  const form = qs("#accountForm");
  const data = formData(form);
  const candidate = {
    id: "candidate",
    name: data.name,
    address: data.address,
    phone: data.phone,
    region: data.region,
  };
  const duplicates = state.accounts
    .map((item) => ({ account: item, score: duplicateScore(candidate, item) }))
    .filter((item) => item.score >= 45)
    .sort((a, b) => b.score - a.score);
  const preview = qs("#newAccountDuplicatePreview");
  if (!duplicates.length) {
    preview.classList.remove("is-visible");
    preview.innerHTML = "";
    return;
  }
  preview.classList.add("is-visible");
  preview.innerHTML = duplicates
    .slice(0, 3)
    .map((item) => `<strong>${html(item.account.name)}</strong> ${item.score}% 일치 · ${html(user(item.account.ownerId).name)} 담당`)
    .join("<br>");
}

function renderAll() {
  hydrateControls();
  renderMetrics();
  renderRepBoard();
  renderDuplicates();
  renderFollowups();
  renderRecentActivities();
  renderAccountRows();
  renderAccountDetail();
  renderPeople();
  renderContracts();
  renderAudit();
  renderDuplicatePreview();
}

async function handleLogin(event) {
  event.preventDefault();
  const data = formData(event.currentTarget);
  try {
    const payload = await api("/api/login", { method: "POST", body: JSON.stringify(data) });
    state.me = payload.user;
    await loadBootstrap();
    setView("dashboard");
    showToast("로그인되었습니다.");
  } catch (error) {
    alert(error.message);
  }
}

async function handleSignup(event) {
  event.preventDefault();
  const data = formData(event.currentTarget);
  data.agreeOwnership = Boolean(data.agreeOwnership);
  data.agreeSettlement = Boolean(data.agreeSettlement);
  try {
    await api("/api/signup", { method: "POST", body: JSON.stringify(data) });
    event.currentTarget.reset();
    alert("가입 신청이 완료되었습니다. 관리자 승인 후 로그인할 수 있습니다.");
    if (state.me && isManager()) await loadBootstrap();
  } catch (error) {
    alert(error.message);
  }
}

async function handleLogout() {
  await api("/api/logout", { method: "POST", body: "{}" }).catch(() => {});
  state.me = null;
  applyAuthState();
}

async function handleActivitySubmit(event) {
  event.preventDefault();
  const data = formData(event.currentTarget);
  try {
    await api("/api/activities", { method: "POST", body: JSON.stringify(data) });
    event.currentTarget.summary.value = "";
    event.currentTarget.nextAction.value = "";
    event.currentTarget.locationNote.value = "";
    await loadBootstrap();
    setView("accounts");
    showToast("영업 활동이 저장되었습니다.");
  } catch (error) {
    alert(error.message);
  }
}

async function handleAccountSubmit(event) {
  event.preventDefault();
  const data = formData(event.currentTarget);
  data.expectedAmount = Number(data.expectedAmount || 0);
  try {
    const payload = await api("/api/accounts", { method: "POST", body: JSON.stringify(data) });
    state.selectedAccountId = payload.account.id;
    event.currentTarget.reset();
    await loadBootstrap();
    setView("accounts");
    showToast(payload.duplicates?.length ? "거래처가 등록되었고 중복 검토가 필요합니다." : "거래처가 등록되었습니다.");
  } catch (error) {
    alert(error.message);
  }
}

async function handleContractSubmit(event) {
  event.preventDefault();
  const data = formData(event.currentTarget);
  const shares = {
    originator: Number(data.originatorShare),
    closer: Number(data.closerShare),
    manager: Number(data.managerShare),
  };
  if (shares.originator + shares.closer + shares.manager !== 100) {
    alert("성과 배분 합계는 100%여야 합니다.");
    return;
  }
  const payload = {
    accountId: data.accountId,
    date: data.date,
    amount: Number(data.amount),
    originatorId: data.originatorId,
    closerId: data.closerId,
    managerId: data.managerId,
    shares,
    memo: data.memo,
  };
  try {
    await api("/api/contracts", { method: "POST", body: JSON.stringify(payload) });
    event.currentTarget.reset();
    await loadBootstrap();
    showToast("정산 대기 계약이 등록되었습니다.");
  } catch (error) {
    alert(error.message);
  }
}

async function handleAccountAction(action) {
  const item = account(state.selectedAccountId);
  if (!item) return;
  const body = {};
  if (action === "advance-status") {
    const index = STATUS_ORDER.indexOf(item.status);
    body.status = STATUS_ORDER[Math.min(index + 1, STATUS_ORDER.length - 1)] || "접촉중";
  }
  if (action === "extend-lock") {
    body.lockUntil = addDays(state.today, 30);
  }
  try {
    await api(`/api/accounts/${item.id}`, { method: "PATCH", body: JSON.stringify(body) });
    await loadBootstrap();
    showToast("거래처가 수정되었습니다.");
  } catch (error) {
    alert(error.message);
  }
}

async function handlePeopleAction(button) {
  try {
    await api(`/api/users/${button.dataset.userId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status: button.dataset.peopleAction }),
    });
    await loadBootstrap();
    showToast("직원 상태가 변경되었습니다.");
  } catch (error) {
    alert(error.message);
  }
}

async function handleContractAction(button) {
  if (button.dataset.contractAction !== "approve") return;
  try {
    await api(`/api/contracts/${button.dataset.contractId}/approve`, { method: "PATCH", body: "{}" });
    await loadBootstrap();
    showToast("정산이 승인되었습니다.");
  } catch (error) {
    alert(error.message);
  }
}

async function openSettlementExport() {
  try {
    const month = qs("#dashboardMonth").value || state.today.slice(0, 7);
    const payload = await api(`/api/settlements?month=${encodeURIComponent(month)}`);
    qs("#exportContent").innerHTML = `
      <div class="settlement-list">
        ${payload.rows
          .map(
            (row) => `
              <div class="settlement-row">
                <div>
                  <span class="muted-text">${html(row.user.region || "-")} · 계약 참여 ${row.count}건</span>
                  <strong>${html(row.user.name)}</strong>
                </div>
                <strong>${currency(row.amount)}</strong>
              </div>
            `,
          )
          .join("")}
      </div>
    `;
    qs("#exportDialog").showModal();
  } catch (error) {
    alert(error.message);
  }
}

function bindEvents() {
  qs("#loginForm").addEventListener("submit", handleLogin);
  qs("#signupForm").addEventListener("submit", handleSignup);
  qs("#logoutBtn").addEventListener("click", handleLogout);
  qs("#refreshBtn").addEventListener("click", () => loadBootstrap().then(() => showToast("새로고침되었습니다.")));
  qs("#exportBtn").addEventListener("click", openSettlementExport);
  qs("#closeExportBtn").addEventListener("click", () => qs("#exportDialog").close());

  qsa(".nav-item").forEach((item) => item.addEventListener("click", () => setView(item.dataset.view)));
  qs("#dashboardMonth").addEventListener("change", renderAll);
  qs("#accountSearch").addEventListener("input", renderAccountRows);
  qs("#ownerFilter").addEventListener("change", renderAccountRows);
  qs("#statusFilter").addEventListener("change", renderAccountRows);
  qs("#accountForm").addEventListener("input", renderDuplicatePreview);
  qs("#activityForm").addEventListener("submit", handleActivitySubmit);
  qs("#accountForm").addEventListener("submit", handleAccountSubmit);
  qs("#contractForm").addEventListener("submit", handleContractSubmit);

  qs("#accountRows").addEventListener("click", (event) => {
    const row = event.target.closest("[data-account-id]");
    if (!row) return;
    state.selectedAccountId = row.dataset.accountId;
    renderAccountRows();
    renderAccountDetail();
  });

  qs("#accountDetailPanel").addEventListener("click", (event) => {
    const button = event.target.closest("[data-account-action]");
    if (!button) return;
    handleAccountAction(button.dataset.accountAction);
  });

  qs("#peopleRows").addEventListener("click", (event) => {
    const button = event.target.closest("[data-people-action]");
    if (!button) return;
    handlePeopleAction(button);
  });

  qs("#contractRows").addEventListener("click", (event) => {
    const button = event.target.closest("[data-contract-action]");
    if (!button) return;
    handleContractAction(button);
  });
}

bindEvents();
checkSession();
