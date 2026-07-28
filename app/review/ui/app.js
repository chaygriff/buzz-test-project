const DATASETS = {
  people: "data/people.jsonl",
  relationships: "data/relationships.jsonl",
  organizations: "data/organizations.jsonl",
  evidence: "data/evidence_sources.jsonl",
  decisions: "data/resolution_decisions.jsonl",
  profileEnrichments: "data/profile_enrichments.jsonl",
};

const state = {
  people: [],
  relationships: [],
  organizations: [],
  evidence: [],
  decisions: [],
  profileEnrichments: [],
  filters: {
    search: "",
    status: "",
    type: "",
    review: "",
  },
  selectedPersonId: null,
};

const el = {
  lastLoaded: document.querySelector("#lastLoaded"),
  peopleCount: document.querySelector("#peopleCount"),
  relationshipCount: document.querySelector("#relationshipCount"),
  organizationCount: document.querySelector("#organizationCount"),
  decisionCount: document.querySelector("#decisionCount"),
  enrichmentCount: document.querySelector("#enrichmentCount"),
  resultCount: document.querySelector("#resultCount"),
  rows: document.querySelector("#relationshipRows"),
  search: document.querySelector("#searchInput"),
  status: document.querySelector("#statusFilter"),
  type: document.querySelector("#typeFilter"),
  review: document.querySelector("#reviewFilter"),
  clear: document.querySelector("#clearFilters"),
  detailName: document.querySelector("#detailName"),
  detailMeta: document.querySelector("#detailMeta"),
  personDetail: document.querySelector("#personDetail"),
  decisionList: document.querySelector("#decisionList"),
};

const index = {
  people: new Map(),
  organizations: new Map(),
  evidenceByRelationship: new Map(),
  enrichmentByPerson: new Map(),
};

async function loadJsonl(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  const text = await response.text();
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

async function init() {
  try {
    const [people, relationships, organizations, evidence, decisions, profileEnrichments] = await Promise.all([
      loadJsonl(DATASETS.people),
      loadJsonl(DATASETS.relationships),
      loadJsonl(DATASETS.organizations),
      loadJsonl(DATASETS.evidence),
      loadJsonl(DATASETS.decisions),
      loadJsonl(DATASETS.profileEnrichments),
    ]);
    Object.assign(state, { people, relationships, organizations, evidence, decisions, profileEnrichments });
    buildIndexes();
    populateFilters();
    bindEvents();
    render();
    el.lastLoaded.textContent = `Loaded ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  } catch (error) {
    el.rows.innerHTML = `<tr><td colspan="7">${escapeHtml(error.message)}</td></tr>`;
    el.lastLoaded.textContent = "Load failed";
  }
}

function buildIndexes() {
  index.people = new Map(state.people.map((person) => [person.person_id, person]));
  index.organizations = new Map(state.organizations.map((org) => [org.organization_id, org]));
  index.evidenceByRelationship = new Map();
  for (const evidence of state.evidence) {
    index.evidenceByRelationship.set(evidence.relationship_id, evidence);
  }
  index.enrichmentByPerson = new Map();
  for (const enrichment of state.profileEnrichments) {
    if (!enrichment.person_id || index.enrichmentByPerson.has(enrichment.person_id)) continue;
    index.enrichmentByPerson.set(enrichment.person_id, enrichment);
  }
}

function populateFilters() {
  fillSelect(el.status, unique(state.relationships.map((item) => item.status)));
  fillSelect(el.type, unique(state.relationships.map((item) => item.relationship_type)));
}

function fillSelect(select, values) {
  for (const value of values) {
    if (!value) continue;
    const option = document.createElement("option");
    option.value = value;
    option.textContent = titleize(value);
    select.appendChild(option);
  }
}

function bindEvents() {
  el.search.addEventListener("input", (event) => {
    state.filters.search = event.target.value.toLowerCase().trim();
    renderRelationships();
  });
  el.status.addEventListener("change", (event) => {
    state.filters.status = event.target.value;
    renderRelationships();
  });
  el.type.addEventListener("change", (event) => {
    state.filters.type = event.target.value;
    renderRelationships();
  });
  el.review.addEventListener("change", (event) => {
    state.filters.review = event.target.value;
    renderRelationships();
  });
  el.clear.addEventListener("click", () => {
    state.filters = { search: "", status: "", type: "", review: "" };
    el.search.value = "";
    el.status.value = "";
    el.type.value = "";
    el.review.value = "";
    renderRelationships();
  });
}

function render() {
  el.peopleCount.textContent = state.people.length.toLocaleString();
  el.relationshipCount.textContent = state.relationships.length.toLocaleString();
  el.organizationCount.textContent = state.organizations.length.toLocaleString();
  el.decisionCount.textContent = state.decisions.length.toLocaleString();
  el.enrichmentCount.textContent = state.profileEnrichments.length.toLocaleString();
  renderRelationships();
  renderDecisions();
}

function renderRelationships() {
  const records = filteredRelationships();
  el.resultCount.textContent = `${records.length.toLocaleString()} ${records.length === 1 ? "record" : "records"}`;
  el.rows.innerHTML = records.map(renderRelationshipRow).join("");
  for (const row of el.rows.querySelectorAll("tr[data-person-id]")) {
    row.addEventListener("click", () => selectPerson(row.dataset.personId));
  }
}

function filteredRelationships() {
  return state.relationships.filter((record) => {
    if (state.filters.status && record.status !== state.filters.status) return false;
    if (state.filters.type && record.relationship_type !== state.filters.type) return false;
    if (state.filters.review === "has_enrichment" && !index.enrichmentByPerson.has(record.person_id)) return false;
    if (state.filters.review === "missing_profile" && getPerson(record.person_id).profile_urls.length > 0) return false;
    if (state.filters.review === "co_advisor" && !record.co_advisor_name_raw) return false;
    if (state.filters.review === "destination" && !record.current_destination_raw) return false;
    if (!state.filters.search) return true;
    return searchableText(record).includes(state.filters.search);
  });
}

function searchableText(record) {
  const person = getPerson(record.person_id);
  const sourceOrg = getOrganization(record.source_affiliation_org_id);
  const destinationOrg = getOrganization(record.current_destination_org_id);
  const evidence = index.evidenceByRelationship.get(record.relationship_id);
  return [
    person.display_name,
    record.relationship_type,
    record.status,
    record.source_affiliation_raw,
    sourceOrg.name,
    record.current_destination_raw,
    destinationOrg.name,
    record.fellowship,
    record.co_advisor_name_raw,
    evidence?.evidence_text,
    index.enrichmentByPerson.get(record.person_id)?.short_biography,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function renderRelationshipRow(record) {
  const person = getPerson(record.person_id);
  const evidence = index.evidenceByRelationship.get(record.relationship_id);
  const destination = record.current_destination_raw || getOrganization(record.current_destination_org_id).name;
  const active = state.selectedPersonId === record.person_id ? " class=\"active\"" : "";
  return `
    <tr data-person-id="${escapeAttr(record.person_id)}"${active}>
      <td class="person-cell">${escapeHtml(person.display_name)}<br><span class="muted">${escapeHtml(person.resolution_status)}</span></td>
      <td>${tag(titleize(record.relationship_type))}</td>
      <td>${tag(titleize(record.status), record.status)}</td>
      <td>${escapeHtml(formatYears(record))}</td>
      <td>${escapeHtml(valueOrNA(record.source_affiliation_raw))}</td>
      <td>${escapeHtml(valueOrNA(destination))}</td>
      <td class="evidence">${escapeHtml(valueOrNA(evidence?.evidence_text))}</td>
    </tr>
  `;
}

function selectPerson(personId) {
  state.selectedPersonId = personId;
  renderRelationships();
  renderPersonDetail(personId);
}

function renderPersonDetail(personId) {
  const person = getPerson(personId);
  const records = state.relationships.filter((record) => record.person_id === personId);
  const enrichment = index.enrichmentByPerson.get(personId);
  el.detailName.textContent = person.display_name;
  el.detailMeta.textContent = `${records.length} relationship${records.length === 1 ? "" : "s"} · ${person.resolution_status}${enrichment ? " · profile enriched" : ""}`;
  el.personDetail.className = "detail-body";
  el.personDetail.innerHTML = `
    <dl class="detail-grid">
      <dt>Person ID</dt><dd>${escapeHtml(person.person_id)}</dd>
      <dt>Name key</dt><dd>${escapeHtml(person.name_key)}</dd>
      <dt>Profiles</dt><dd>${formatProfileLinks(person.profile_urls)}</dd>
      <dt>Role</dt><dd>${escapeHtml(valueOrNA(person.primary_role))}</dd>
    </dl>
    ${renderEnrichmentCard(enrichment)}
    ${records.map(renderRelationshipCard).join("")}
  `;
}

function renderEnrichmentCard(enrichment) {
  if (!enrichment) {
    return `
      <article class="profile-card muted-card">
        <h3>Profile enrichment ${tag("N/A")}</h3>
        <p>No manual profile enrichment has been imported for this person yet.</p>
      </article>
    `;
  }
  return `
    <article class="profile-card">
      <h3>Profile enrichment ${tag(titleize(enrichment.verification_status), enrichment.verification_status)}</h3>
      <p>${escapeHtml(valueOrNA(enrichment.short_biography))}</p>
      <div class="link-grid">
        ${formatNamedLink("Website", enrichment.personal_website_url)}
        ${formatNamedLink("Google Scholar", enrichment.google_scholar_url)}
        ${formatNamedLink("LinkedIn", enrichment.linkedin_url)}
        ${formatNamedLink("GitHub", enrichment.github_url)}
      </div>
      <p><strong>Evidence:</strong> ${escapeHtml(valueOrNA(enrichment.evidence_text))}</p>
      <p><strong>Source:</strong> ${formatNamedLink(valueOrNA(enrichment.source_url), enrichment.source_url)}</p>
    </article>
  `;
}

function renderRelationshipCard(record) {
  const evidence = index.evidenceByRelationship.get(record.relationship_id);
  return `
    <article class="relationship-card">
      <h3>${escapeHtml(titleize(record.relationship_type))} ${tag(titleize(record.status), record.status)}</h3>
      <p><strong>Years:</strong> ${escapeHtml(formatYears(record))}</p>
      <p><strong>Source affiliation:</strong> ${escapeHtml(valueOrNA(record.source_affiliation_raw))}</p>
      <p><strong>Destination:</strong> ${escapeHtml(valueOrNA(record.current_destination_raw))}</p>
      <p><strong>Co-advisor:</strong> ${escapeHtml(valueOrNA(record.co_advisor_name_raw))}</p>
      <p><strong>Fellowship:</strong> ${escapeHtml(valueOrNA(record.fellowship))}</p>
      <p><strong>Evidence:</strong> ${escapeHtml(valueOrNA(evidence?.evidence_text))}</p>
      <p><strong>Source:</strong> ${formatSourceLink(evidence)}</p>
    </article>
  `;
}

function renderDecisions() {
  if (!state.decisions.length) {
    el.decisionList.innerHTML = "<p class=\"muted\">No resolution decisions emitted.</p>";
    return;
  }
  el.decisionList.innerHTML = state.decisions
    .map((decision) => `
      <article class="decision-card">
        <h3>${escapeHtml(titleize(decision.decision))} ${tag(escapeHtml(decision.review_status))}</h3>
        <p><strong>Rule:</strong> ${escapeHtml(decision.rule_name)}</p>
        <p><strong>Score:</strong> ${escapeHtml(String(decision.score))}</p>
        <p><strong>Candidate keys:</strong> ${escapeHtml(decision.candidate_keys.join(", "))}</p>
        <p>${escapeHtml(decision.evidence_summary)}</p>
      </article>
    `)
    .join("");
}

function getPerson(personId) {
  return index.people.get(personId) || {
    display_name: "Unknown person",
    name_key: "unknown",
    profile_urls: [],
    resolution_status: "unknown",
  };
}

function getOrganization(organizationId) {
  if (!organizationId) return { name: null };
  return index.organizations.get(organizationId) || { name: null };
}

function formatYears(record) {
  if (record.start_year && record.end_year) return `${record.start_year}-${record.end_year}`;
  if (record.start_year) return `${record.start_year}-`;
  if (record.graduation_year) return String(record.graduation_year);
  return "N/A";
}

function formatProfileLinks(urls) {
  if (!urls || !urls.length) return "N/A";
  return urls.map((url) => `<a href="${escapeAttr(url)}" target="_blank" rel="noreferrer">${escapeHtml(url)}</a>`).join("<br>");
}

function formatSourceLink(evidence) {
  if (!evidence?.source_url) return "N/A";
  const section = evidence.source_section ? ` · ${escapeHtml(evidence.source_section)}` : "";
  return `<a href="${escapeAttr(evidence.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(evidence.source_url)}</a>${section}`;
}

function formatNamedLink(label, url) {
  if (!url) return `<span class="muted">${escapeHtml(label)}: N/A</span>`;
  return `<a href="${escapeAttr(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
}

function tag(label, variant = "") {
  const cleanVariant = variant ? ` ${escapeAttr(variant)}` : "";
  return `<span class="tag${cleanVariant}">${escapeHtml(label || "N/A")}</span>`;
}

function valueOrNA(value) {
  return value === null || value === undefined || value === "" ? "N/A" : String(value);
}

function titleize(value) {
  return valueOrNA(value)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function unique(values) {
  return [...new Set(values.filter(Boolean))].sort();
}

function escapeHtml(value) {
  return valueOrNA(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

init();
