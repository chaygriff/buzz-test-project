const DATASETS = {
  reviewBundle: "data/review_bundle.json",
};

const state = {
  people: [],
  relationships: [],
  organizations: [],
  evidence: [],
  decisions: [],
  profileEnrichments: [],
  profileReconciliationDecisions: [],
  backfillCandidates: [],
  metadata: null,
  filters: {
    search: "",
    status: "",
    professor: "",
    type: "",
    review: "",
    confidence: "",
  },
  selectedPersonId: null,
};

const el = {
  datasetLabel: document.querySelector("#datasetLabel"),
  lastLoaded: document.querySelector("#lastLoaded"),
  peopleCount: document.querySelector("#peopleCount"),
  relationshipCount: document.querySelector("#relationshipCount"),
  organizationCount: document.querySelector("#organizationCount"),
  decisionCount: document.querySelector("#decisionCount"),
  enrichmentCount: document.querySelector("#enrichmentCount"),
  profileUrlCount: document.querySelector("#profileUrlCount"),
  backfillCount: document.querySelector("#backfillCount"),
  resultCount: document.querySelector("#resultCount"),
  rows: document.querySelector("#relationshipRows"),
  search: document.querySelector("#searchInput"),
  status: document.querySelector("#statusFilter"),
  professor: document.querySelector("#professorFilter"),
  type: document.querySelector("#typeFilter"),
  review: document.querySelector("#reviewFilter"),
  confidence: document.querySelector("#confidenceFilter"),
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
  reconciliationByPerson: new Map(),
  reviewDecisionByPerson: new Map(),
  backfillByPerson: new Map(),
};

async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  return response.json();
}

async function init() {
  try {
    const bundle = await loadJson(DATASETS.reviewBundle);
    Object.assign(state, {
      people: bundle.people || [],
      relationships: bundle.relationships || [],
      organizations: bundle.organizations || [],
      evidence: bundle.evidence_sources || [],
      decisions: bundle.resolution_decisions || [],
      profileEnrichments: bundle.profile_enrichments || [],
      profileReconciliationDecisions: bundle.profile_reconciliation_decisions || [],
      backfillCandidates: bundle.backfill_candidates || [],
      metadata: bundle.metadata || null,
    });
    buildIndexes();
    populateFilters();
    bindEvents();
    render();
    el.lastLoaded.textContent = `Loaded ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  } catch (error) {
    el.rows.innerHTML = `<tr><td colspan="8">${escapeHtml(error.message)}</td></tr>`;
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
  index.reconciliationByPerson = new Map();
  for (const decision of state.profileReconciliationDecisions) {
    if (!decision.person_id) continue;
    index.reconciliationByPerson.set(decision.person_id, decision);
  }
  index.reviewDecisionByPerson = new Map();
  for (const decision of state.decisions) {
    if (decision.review_status !== "needs_review") continue;
    for (const personId of personIdsForDecision(decision)) {
      if (!index.reviewDecisionByPerson.has(personId)) {
        index.reviewDecisionByPerson.set(personId, decision);
      }
    }
  }
  index.backfillByPerson = new Map();
  for (const candidate of state.backfillCandidates) {
    if (!candidate.person_id) continue;
    index.backfillByPerson.set(candidate.person_id, candidate);
  }
}

function populateFilters() {
  fillSelect(el.status, unique(state.relationships.map((item) => item.status)));
  fillSelect(el.professor, unique(state.relationships.map((item) => professorName(item))), (value) => value);
  fillSelect(el.type, unique(state.relationships.map((item) => item.relationship_type)), relationshipLabel);
}

function fillSelect(select, values, formatter = titleize) {
  for (const value of values) {
    if (!value) continue;
    const option = document.createElement("option");
    option.value = value;
    option.textContent = formatter(value);
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
  el.professor.addEventListener("change", (event) => {
    state.filters.professor = event.target.value;
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
  el.confidence.addEventListener("change", (event) => {
    state.filters.confidence = event.target.value;
    renderRelationships();
  });
  el.clear.addEventListener("click", () => {
    state.filters = { search: "", status: "", professor: "", type: "", review: "", confidence: "" };
    el.search.value = "";
    el.status.value = "";
    el.professor.value = "";
    el.type.value = "";
    el.review.value = "";
    el.confidence.value = "";
    renderRelationships();
  });
}

function render() {
  if (state.metadata?.dataset_label) {
    el.datasetLabel.textContent = state.metadata.dataset_label;
  }
  renderRelationships();
  renderDecisions();
}

function renderRelationships() {
  const records = filteredRelationships();
  if (state.selectedPersonId && !records.some((record) => record.person_id === state.selectedPersonId)) {
    state.selectedPersonId = null;
    renderEmptyPersonDetail();
  }
  renderMetrics(records);
  el.resultCount.textContent = `${records.length.toLocaleString()} ${records.length === 1 ? "record" : "records"}`;
  el.rows.innerHTML = records.map(renderRelationshipRow).join("");
  for (const row of el.rows.querySelectorAll("tr[data-person-id]")) {
    row.addEventListener("click", () => selectPerson(row.dataset.personId));
  }
}

function renderMetrics(records) {
  if (!hasActiveFilters()) {
    renderBundleMetrics();
    return;
  }

  const personIds = new Set(records.map((record) => record.person_id));
  const organizationIds = new Set();
  for (const record of records) {
    if (record.source_affiliation_org_id) organizationIds.add(record.source_affiliation_org_id);
    if (record.current_destination_org_id) organizationIds.add(record.current_destination_org_id);
  }

  el.peopleCount.textContent = personIds.size.toLocaleString();
  el.relationshipCount.textContent = records.length.toLocaleString();
  el.organizationCount.textContent = organizationIds.size.toLocaleString();
  el.decisionCount.textContent = filteredDecisionCount(personIds).toLocaleString();
  el.enrichmentCount.textContent = filteredProfileEnrichmentCount(personIds).toLocaleString();
  el.profileUrlCount.textContent = filteredPeopleWithProfileUrls(personIds).toLocaleString();
  el.backfillCount.textContent = filteredBackfillCount(personIds).toLocaleString();
}

function renderBundleMetrics() {
  el.peopleCount.textContent = state.people.length.toLocaleString();
  el.relationshipCount.textContent = state.relationships.length.toLocaleString();
  el.organizationCount.textContent = state.organizations.length.toLocaleString();
  el.decisionCount.textContent = state.decisions.length.toLocaleString();
  el.enrichmentCount.textContent = state.profileEnrichments.length.toLocaleString();
  el.profileUrlCount.textContent = state.people.filter((person) => person.profile_urls?.length).length.toLocaleString();
  el.backfillCount.textContent = state.backfillCandidates.length.toLocaleString();
}

function hasActiveFilters() {
  return Object.values(state.filters).some(Boolean);
}

function filteredRelationships() {
  return state.relationships.filter((record) => {
    if (state.filters.status && record.status !== state.filters.status) return false;
    if (state.filters.professor && professorName(record) !== state.filters.professor) return false;
    if (state.filters.type && record.relationship_type !== state.filters.type) return false;
    if (state.filters.confidence && record.confidence_bucket !== state.filters.confidence) return false;
    if (state.filters.review === "has_enrichment" && !index.enrichmentByPerson.has(record.person_id)) return false;
    if (state.filters.review === "missing_enrichment" && index.enrichmentByPerson.has(record.person_id)) return false;
    if (state.filters.review === "has_profile_url" && !getPerson(record.person_id).profile_urls.length) return false;
    if (state.filters.review === "needs_backfill" && !index.backfillByPerson.has(record.person_id)) return false;
    if (state.filters.review === "reconciliation" && !index.reconciliationByPerson.has(record.person_id)) return false;
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
    professorName(record),
    record.dataset_label,
    record.relationship_type,
    record.status,
    record.confidence_bucket,
    ...(record.confidence_reasons || []),
    ...(record.confidence_penalties || []),
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
  const reconciliation = index.reconciliationByPerson.get(record.person_id);
  const reviewDecision = index.reviewDecisionByPerson.get(record.person_id);
  const backfill = index.backfillByPerson.get(record.person_id);
  const active = state.selectedPersonId === record.person_id ? " class=\"active\"" : "";
  return `
    <tr data-person-id="${escapeAttr(record.person_id)}"${active}>
      <td class="person-cell">${escapeHtml(person.display_name)}<br><span class="muted">${escapeHtml(formatResolutionStatus(person.resolution_status))}</span>${reconciliation ? `<br>${tag("Review join", "needs_review")}` : ""}${reviewDecision ? `<br>${tag("Review relationship", "needs_review")}` : ""}${backfill ? `<br>${tag("Backfill queued", backfill.priority_bucket)}` : ""}${renderEvidenceSnippet(evidence)}</td>
      <td>${escapeHtml(professorName(record))}</td>
      <td>${tag(relationshipLabel(record.relationship_type))}</td>
      <td>${tag(titleize(record.status), record.status)}</td>
      <td>${renderConfidenceBadge(record)}</td>
      <td>${escapeHtml(formatYears(record))}</td>
      <td>${escapeHtml(valueOrNA(record.source_affiliation_raw))}</td>
      <td>${escapeHtml(valueOrNA(destination))}</td>
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
  const reconciliation = index.reconciliationByPerson.get(personId);
  const reviewDecision = index.reviewDecisionByPerson.get(personId);
  const backfillCandidate = index.backfillByPerson.get(personId);
  el.detailName.textContent = person.display_name;
  const professorNames = unique(records.map((record) => professorName(record)));
  el.detailMeta.textContent = `${records.length} relationship${records.length === 1 ? "" : "s"} · ${professorNames.join(", ")} · ${formatResolutionStatus(person.resolution_status)}${enrichment ? " · manual enrichment" : ""}${backfillCandidate ? " · backfill queued" : ""}`;
  el.personDetail.className = "detail-body";
  el.personDetail.innerHTML = `
    <dl class="detail-grid">
      <dt>Person ID</dt><dd>${escapeHtml(person.person_id)}</dd>
      <dt>Name key</dt><dd>${escapeHtml(person.name_key)}</dd>
      <dt>Profiles</dt><dd>${formatProfileLinks(person.profile_urls)}</dd>
      <dt>Role</dt><dd>${escapeHtml(valueOrNA(person.primary_role))}</dd>
      <dt>Professor context</dt><dd>${escapeHtml(professorNames.join(", "))}</dd>
    </dl>
    ${renderReconciliationCard(reconciliation)}
    ${renderRelationshipReviewCard(reviewDecision)}
    ${renderEnrichmentCard(enrichment)}
    ${renderBackfillCard(backfillCandidate)}
    ${records.map(renderRelationshipCard).join("")}
  `;
}

function renderRelationshipReviewCard(decision) {
  if (!decision) return "";
  return `
    <article class="profile-card warning-card">
      <h3>Relationship review ${tag(titleize(decision.review_status), decision.review_status)}</h3>
      <p>${escapeHtml(decision.evidence_summary)}</p>
      <p><strong>Rule:</strong> ${escapeHtml(decision.rule_name)}</p>
    </article>
  `;
}

function renderEmptyPersonDetail() {
  el.detailName.textContent = "Select a person";
  el.detailMeta.textContent = "Relationship details will appear here.";
  el.personDetail.className = "detail-empty";
  el.personDetail.textContent = "Choose any relationship row to inspect the person, linked records, and source evidence.";
}

function renderReconciliationCard(decision) {
  if (!decision) return "";
  return `
    <article class="profile-card warning-card">
      <h3>Profile reconciliation ${tag(titleize(decision.review_status), decision.review_status)}</h3>
      <p>${escapeHtml(decision.evidence_summary)}</p>
      <p><strong>Rule:</strong> ${escapeHtml(decision.rule_name)}</p>
    </article>
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

function renderBackfillCard(candidate) {
  if (!candidate) return "";
  return `
    <article class="profile-card backfill-card">
      <h3>People-search backfill ${tag(titleize(candidate.priority_bucket), candidate.priority_bucket)}</h3>
      <p><strong>Status:</strong> ${escapeHtml(titleize(candidate.verification_status))}</p>
      <p><strong>Search query:</strong> ${escapeHtml(candidate.search_query)}</p>
      <p><strong>Reasons:</strong> ${escapeHtml(candidate.priority_reasons.join(", "))}</p>
      <p><strong>Evidence:</strong> ${escapeHtml(valueOrNA(candidate.evidence_text))}</p>
    </article>
  `;
}

function renderRelationshipCard(record) {
  const evidence = index.evidenceByRelationship.get(record.relationship_id);
  return `
    <article class="relationship-card">
      <h3>${escapeHtml(relationshipLabel(record.relationship_type))} ${tag(titleize(record.status), record.status)}</h3>
      <p><strong>Professor:</strong> ${escapeHtml(professorName(record))}</p>
      <p><strong>Confidence:</strong> ${renderConfidenceBadge(record)}</p>
      ${renderConfidenceReasons(record)}
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

function filteredDecisionCount(personIds) {
  return state.decisions.filter((decision) => {
    const candidatePersonIds = (decision.candidate_person_ids || []).filter(Boolean);
    if (decision.person_id && personIds.has(decision.person_id)) return true;
    if (decision.chosen_entity_id && personIds.has(decision.chosen_entity_id)) return true;
    return candidatePersonIds.some((personId) => personIds.has(personId));
  }).length;
}

function personIdsForDecision(decision) {
  return unique([
    decision.person_id,
    decision.chosen_entity_id,
    ...(decision.candidate_person_ids || []),
  ].filter(Boolean));
}

function filteredProfileEnrichmentCount(personIds) {
  return state.profileEnrichments.filter((enrichment) => personIds.has(enrichment.person_id)).length;
}

function filteredPeopleWithProfileUrls(personIds) {
  return state.people.filter((person) => personIds.has(person.person_id) && person.profile_urls?.length).length;
}

function filteredBackfillCount(personIds) {
  return state.backfillCandidates.filter((candidate) => personIds.has(candidate.person_id)).length;
}

function renderEvidenceSnippet(evidence) {
  if (!evidence?.evidence_text) return "";
  return `<div class="evidence-snippet">${escapeHtml(evidence.evidence_text)}</div>`;
}

function renderConfidenceBadge(record) {
  const bucket = record.confidence_bucket || "low";
  const score = Number.isFinite(record.confidence_score) ? record.confidence_score : 0;
  return `<span class="confidence-badge ${escapeAttr(bucket)}"><strong>${escapeHtml(String(score))}</strong><span>${escapeHtml(confidenceLabel(bucket))}</span></span>`;
}

function renderConfidenceReasons(record) {
  const reasons = record.confidence_reasons || [];
  const penalties = record.confidence_penalties || [];
  if (!reasons.length && !penalties.length) return "";
  return `
    <div class="confidence-reasons">
      ${reasons.map((reason) => `<span>${escapeHtml(confidenceReasonLabel(reason))}</span>`).join("")}
      ${penalties.map((penalty) => `<span class="penalty">${escapeHtml(confidenceReasonLabel(penalty))}</span>`).join("")}
    </div>
  `;
}

function confidenceLabel(bucket) {
  const labels = {
    high: "High",
    medium: "Medium",
    low: "Low",
    needs_review: "Review",
  };
  return labels[bucket] || titleize(bucket);
}

function confidenceReasonLabel(value) {
  return titleize(value).replace(/\bUrl\b/g, "URL");
}

function professorName(record) {
  return record.professor_name || record.dataset_label || "Unknown professor";
}

function formatYears(record) {
  if (record.start_year && record.end_year) return `${record.start_year}-${record.end_year}`;
  if (record.start_year) return `${record.start_year}-`;
  if (record.graduation_year) return String(record.graduation_year);
  return "N/A";
}

function formatProfileLinks(urls) {
  if (!urls || !urls.length) return "N/A";
  return urls.map((url) => formatNamedLink(profileLinkLabel(url), url)).join("<br>");
}

function formatSourceLink(evidence) {
  if (!evidence?.source_url) return "N/A";
  const section = evidence.source_section ? ` · ${escapeHtml(evidence.source_section)}` : "";
  return `<a href="${escapeAttr(evidence.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(evidence.source_url)}</a>${section}`;
}

function formatNamedLink(label, url) {
  if (!url) return `<span class="muted">${escapeHtml(label)}: N/A</span>`;
  const profileKind = profileLinkKind(url, label);
  return `<a class="profile-link ${escapeAttr(profileKind)}" href="${escapeAttr(url)}" target="_blank" rel="noreferrer">${profileLinkIcon(profileKind)}<span>${escapeHtml(label)}</span></a>`;
}

function profileLinkLabel(url) {
  const kind = profileLinkKind(url);
  const labels = {
    github: "GitHub",
    linkedin: "LinkedIn",
    scholar: "Google Scholar",
    website: "Website",
  };
  return labels[kind];
}

function profileLinkKind(url, label = "") {
  const text = `${url || ""} ${label}`.toLowerCase();
  if (text.includes("github.com")) return "github";
  if (text.includes("linkedin.com")) return "linkedin";
  if (text.includes("scholar.google.") || text.includes("google scholar")) return "scholar";
  return "website";
}

function profileLinkIcon(kind) {
  const icons = {
    github: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.4a6.7 6.7 0 0 0-2.1 13.1c.3.1.4-.1.4-.3v-1.1c-1.7.4-2.1-.7-2.1-.7-.3-.7-.7-.9-.7-.9-.6-.4 0-.4 0-.4.6 0 1 .7 1 .7.6 1 1.5.7 1.8.5.1-.4.2-.7.4-.9-1.4-.2-2.8-.7-2.8-3a2.3 2.3 0 0 1 .6-1.6c-.1-.2-.3-.8.1-1.6 0 0 .5-.2 1.7.6A5.8 5.8 0 0 1 8 5.6c.6 0 1.1.1 1.6.2 1.2-.8 1.7-.6 1.7-.6.4.8.2 1.4.1 1.6.4.4.6 1 .6 1.6 0 2.3-1.4 2.8-2.8 3 .2.2.4.6.4 1.2v1.7c0 .2.1.4.4.3A6.7 6.7 0 0 0 8 1.4Z"/></svg>`,
    linkedin: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.6 14H1.4V5.8h2.2V14ZM2.5 4.7c-.7 0-1.2-.5-1.2-1.2s.5-1.2 1.2-1.2 1.2.5 1.2 1.2-.5 1.2-1.2 1.2ZM14.6 14h-2.2V9.7c0-1-.4-1.7-1.3-1.7-.7 0-1.1.5-1.3.9-.1.2-.1.4-.1.6V14H7.5V5.8h2.2v1.1c.3-.5.9-1.3 2.1-1.3 1.6 0 2.8 1.1 2.8 3.4V14Z"/></svg>`,
    scholar: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8 1.3 5.4 8 9l6.7-3.6L8 1.8Zm-4.3 6v2.8c0 1.3 1.9 2.4 4.3 2.4s4.3-1.1 4.3-2.4V7.8L8 10.1 3.7 7.8Zm10.1 3.5V6.8h-1.1v4.5l.5 1 .6-1Z"/></svg>`,
    website: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5A6.5 6.5 0 1 0 8 14.5 6.5 6.5 0 0 0 8 1.5Zm4.9 5.8h-2.4a10 10 0 0 0-.8-3.4 5.1 5.1 0 0 1 3.2 3.4ZM8 2.8c.5.7 1.1 2.1 1.2 4.5H6.8C6.9 4.9 7.5 3.5 8 2.8ZM2.8 8.7h2.7c.1 1.4.3 2.6.8 3.5a5.2 5.2 0 0 1-3.5-3.5Zm2.7-1.4H3.1a5.1 5.1 0 0 1 3.2-3.4 10 10 0 0 0-.8 3.4ZM8 13.2c-.5-.7-1.1-2.1-1.2-4.5h2.4c-.1 2.4-.7 3.8-1.2 4.5Zm1.7-1c.5-.9.7-2.1.8-3.5h2.7a5.2 5.2 0 0 1-3.5 3.5Z"/></svg>`,
  };
  return `<span class="profile-link-icon" aria-hidden="true">${icons[kind] || icons.website}</span>`;
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

function relationshipLabel(value) {
  const labels = {
    alum: "Alumni - Role Unknown",
    phd_student: "PhD Student",
    masters_student: "Masters Student",
    undergraduate_student: "Undergraduate Student",
    postdoc: "Postdoc",
    staff: "Staff",
    visitor: "Visitor",
    high_school_student: "High School Student",
  };
  return labels[value] || titleize(value);
}

function formatResolutionStatus(value) {
  const labels = {
    single_source: "Single source",
    seed_faculty: "Seed faculty",
  };
  return labels[value] || titleize(value);
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
