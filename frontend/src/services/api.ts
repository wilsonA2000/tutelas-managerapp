import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
});

// Adjunta el JWT a NIVEL DE MÓDULO (no en un useEffect de React), leyendo
// localStorage en cada request. Elimina la carrera de arranque: los pollers
// hijos (Dashboard, alertas) se montan y disparan ANTES de que corra el
// useEffect de AuthContext → sin esto, el primer burst de requests salía sin
// Authorization → 401 en cada carga de página. AuthContext mantiene su propio
// interceptor para el refresh-on-401 (la redundancia es inofensiva).
api.interceptors.request.use((config) => {
  try {
    const stored = localStorage.getItem('tutelas_auth'); // STORAGE_KEY en AuthContext
    if (stored) {
      const { token } = JSON.parse(stored);
      if (token && !config.url?.includes('/auth/login')) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
  } catch { /* localStorage no disponible / JSON inválido → sin header */ }
  return config;
});

// Cases
export const getCases = (params: Record<string, string | number>) =>
  api.get('/cases', { params }).then(r => r.data);

export const getCase = (id: number) =>
  api.get(`/cases/${id}`).then(r => r.data);

export type AuditEvent = {
  id: number
  ts: string | null
  action: string
  actor: string | null
  entity_type: string | null
  entity_id: number | null
  field_name: string | null
  old_value: string | null
  new_value: string | null
  description: string | null
  meta: Record<string, unknown> | null
}

export const getCaseAudit = (
  caseId: number,
  params: { entity_type?: string; action_prefix?: string; limit?: number } = {},
) =>
  api.get(`/cases/${caseId}/audit`, { params }).then(r => r.data as { items: AuditEvent[]; total: number });

export type CreateCasePayload =
  | {
      tipo?: 'TUTELA'
      radicado_23_digitos: string
      accionante: string
      juzgado?: string
      ciudad?: string
      observaciones?: string
    }
  | {
      tipo: 'COMUNICACION'
      folder_name: string
      observaciones: string
      accionante?: string
    }

export const createCase = (payload: CreateCasePayload) =>
  api.post('/cases', payload).then(r => r.data);

export const updateCase = (id: number, fields: Record<string, string>) =>
  api.put(`/cases/${id}`, fields).then(r => r.data);

export const renameCaseFolder = (id: number, folderName: string) =>
  api.put(`/cases/${id}/folder-name`, { folder_name: folderName }).then(r => r.data);

export const syncSingleCase = (id: number) =>
  api.post(`/cases/${id}/sync`).then(r => r.data);

export const deleteCase = (id: number) =>
  api.delete(`/cases/${id}`).then(r => r.data);

export const deleteDocument = (caseId: number, docId: number) =>
  api.delete(`/cases/${caseId}/docs/${docId}`).then(r => r.data);

export const getFilterOptions = () =>
  api.get('/cases/filters').then(r => r.data);

export const getCasesTable = () =>
  api.get('/cases/table').then(r => r.data);

// Reconciliación tras traslado: comparar dos cases y, opcionalmente, fusionar.
export interface CaseCompareField { field: string; label: string; value: string; suggested_action?: 'copy' | 'merge_text'; target_existing?: string }
export interface CaseCompareDiffer { field: string; label: string; source_value: string; target_value: string }
export interface CaseCompareResult {
  source: { id: number; folder_name: string; n_docs: number; n_emails: number }
  target: { id: number; folder_name: string; n_docs: number }
  similarity_signals: Array<{ kind: string; value: string; label: string }>
  exclusive_in_source: CaseCompareField[]
  differs: CaseCompareDiffer[]
  identical: Array<{ field: string; label: string; value: string }>
  source_can_be_deleted: boolean
}

export const compareCases = (sourceId: number, targetId: number): Promise<CaseCompareResult> =>
  api.get(`/cases/${sourceId}/compare/${targetId}`).then(r => r.data);

export const mergeCases = (sourceId: number, targetId: number, payload: { fields: string[]; merge_observations: boolean; delete_source: boolean }) =>
  api.post(`/cases/${sourceId}/merge-into/${targetId}`, payload).then(r => r.data);

// Dashboard
export const getKPIs = () =>
  api.get('/dashboard/kpis').then(r => r.data);

export const getCharts = () =>
  api.get('/dashboard/charts').then(r => r.data);

export const getActivity = () =>
  api.get('/dashboard/activity').then(r => r.data);

export const chatWithAI = (question: string) =>
  api.post('/chat/', { message: question }, { timeout: 30000 }).then(r => ({
    response: r.data.answer,
    intent: r.data.intent,
    data: r.data.data,
    confidence: r.data.confidence,
    llm_used: r.data.llm_used,
    template_used: r.data.template_used,
  }));

export const getChatIntents = () => api.get('/chat/intents').then(r => r.data);
export const getChatHealth = () => api.get('/chat/health').then(r => r.data);

export const runReverifySospechosos = (dryRun = true, includeRevisar = false, limit = 0) =>
  api.post('/cleanup/reverify-sospechosos', { dry_run: dryRun, include_revisar: includeRevisar, limit }, { timeout: 600000 }).then(r => r.data);

// Anexa el JWT como query param para URLs que el navegador abre por URL directa
// (iframe / <a target=_blank> / window.open) — esos NO pasan por el interceptor
// de axios y por tanto no llevan el header Authorization. El middleware backend
// acepta ?token= como fallback solo en GET. Lee el mismo localStorage que el
// interceptor (STORAGE_KEY 'tutelas_auth').
export const withAuthToken = (url: string): string => {
  try {
    const stored = localStorage.getItem('tutelas_auth');
    if (stored) {
      const { token } = JSON.parse(stored);
      if (token) return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
    }
  } catch { /* sin token disponible → URL sin anexar */ }
  return url;
};

// Documents
export const getDocumentPreviewUrl = (id: number) =>
  withAuthToken(`/api/documents/${id}/preview`);

// Extraction — useLlm: true=Qwen local (default individual), false=determinista (default batch)
export const extractSingle = (caseId: number, force: boolean = false, useLlm: boolean = true) =>
  api.post(`/extraction/single/${caseId}?force=${force}&use_llm=${useLlm}`, {}, { timeout: 180000 }).then(r => r.data);

export const getFolderConsistency = (caseId: number) =>
  api.get(`/extraction/folder-consistency/${caseId}`).then(r => r.data);

export const extractBatch = (caseIds?: number[], classifyDocs: boolean = false, force: boolean = false, useLlm: boolean = false) =>
  api.post('/extraction/batch', { case_ids: caseIds, classify_docs: classifyDocs, force, use_llm: useLlm }, { timeout: 10000 }).then(r => r.data);

export const getReviewQueue = () =>
  api.get('/extraction/review').then(r => r.data);

export const getMismatchedDocs = () =>
  api.get('/extraction/mismatched-docs').then(r => r.data);

export const dismissMismatchedDoc = (logId: number) =>
  api.delete(`/extraction/mismatched-docs/${logId}`).then(r => r.data);

export const dismissAllMismatchedDocs = () =>
  api.delete('/extraction/mismatched-docs').then(r => r.data);

export const verifyAllDocs = () =>
  api.post('/extraction/verify-all', {}, { timeout: 120000 }).then(r => r.data);

export const runFullAudit = () =>
  api.post('/extraction/audit', {}, { timeout: 180000 }).then(r => r.data);

export const getSuspiciousDocs = () =>
  api.get('/extraction/suspicious-docs').then(r => r.data);

export const markDocOk = (docId: number) =>
  api.post(`/extraction/docs/${docId}/mark-ok`).then(r => r.data);

// Reports
export const generateExcel = () =>
  api.post('/reports/excel').then(r => r.data);

export const getExcelList = () =>
  api.get('/reports/excel/list').then(r => r.data);

export const getMetrics = () =>
  api.get('/reports/metrics').then(r => r.data);

// Emails
export const getEmails = (params: Record<string, string | number>) =>
  api.get('/emails', { params }).then(r => r.data);

export const getEmail = (id: number) =>
  api.get(`/emails/detail/${id}`).then(r => r.data);

// v4.8 Provenance: paquete email inmutable (email + documents hijos)
export const getEmailPackage = (id: number) =>
  api.get(`/emails/${id}/package`).then(r => r.data);

export const getCaseEmailPackages = (caseId: number) =>
  api.get(`/cases/${caseId}/email-packages`).then(r => r.data);

// v9.2: Acumulación procesal de tutelas (Dec 2591/91 art. 13 + Dec 1834/2015)
export interface CaseAcumulacion {
  case_id: number;
  tipo: 'RECTOR' | 'ACUMULADO' | null;
  fecha: string | null;
  rector: { id: number; folder_name: string; radicado_23_digitos: string; juzgado?: string; accionante?: string } | null;
  acumulados: Array<{ id: number; folder_name: string; radicado_23_digitos: string; juzgado?: string; accionante?: string }>;
  auto_doc: { id: number; filename: string; case_id: number; doc_type: string } | null;
}
export const getCaseAcumulacion = (caseId: number): Promise<CaseAcumulacion> =>
  api.get(`/cases/${caseId}/acumulacion`).then(r => r.data);

export const checkInbox = () =>
  api.post('/emails/check', {}, { timeout: 10000 }).then(r => r.data);

export const getGmailStats = () =>
  api.get('/emails/gmail-stats').then(r => r.data);

export const getCheckInboxStatus = () =>
  api.get('/emails/check-status').then(r => r.data);

export const cancelCheckInbox = () =>
  api.post('/emails/check-cancel').then(r => r.data);

// Settings
export const getSettingsStatus = () =>
  api.get('/settings/status').then(r => r.data);

// Extraction control
export const runExtractionAll = () =>
  api.post('/extraction/run-all', {}, { timeout: 10000 }).then(r => r.data);

export const stopExtraction = () =>
  api.post('/extraction/stop').then(r => r.data);

export const getExtractionProgress = () =>
  api.get('/extraction/progress').then(r => r.data);

// Monitor
export const getMonitorStatus = () =>
  api.get('/monitor/status').then(r => r.data);

// Sync
export const syncFolders = () =>
  api.post('/sync', {}, { timeout: 10000 }).then(r => r.data);

export const getSyncStatus = () =>
  api.get('/sync/status').then(r => r.data);

export const cancelSync = () =>
  api.post('/sync/cancel').then(r => r.data);

// Seguimiento
export const getSeguimiento = (params?: Record<string, string>) =>
  api.get('/seguimiento', { params }).then(r => r.data);

export const updateSeguimiento = (id: number, body: Record<string, string | number>) =>
  api.put(`/seguimiento/${id}`, body).then(r => r.data);

export const scanFallos = () =>
  api.post('/seguimiento/scan').then(r => r.data);

export const extractOrder = (id: number) =>
  api.post(`/seguimiento/${id}/extract-order`, {}, { timeout: 60000 }).then(r => r.data);

// Alerts
export const getAlerts = (status?: string, severity?: string) =>
  api.get('/alerts', { params: { status, severity } }).then(r => r.data);

export const getAlertCounts = () =>
  api.get('/alerts/counts').then(r => r.data);

export const scanAlerts = () =>
  api.post('/alerts/scan').then(r => r.data);

export const markAlertsSeen = () =>
  api.post('/alerts/mark-seen').then(r => r.data);

export const dismissAlert = (id: number) =>
  api.post(`/alerts/${id}/dismiss`).then(r => r.data);

// Agent Extraction v3
export const agentExtract = (caseId: number, classify: boolean = false, force: boolean = false) =>
  api.post(`/extraction/agent/${caseId}?classify=${classify}&force=${force}`, {}, { timeout: 300000 }).then(r => r.data);

// Intelligence
export const getIntelFavorability = () =>
  api.get('/intelligence/favorability').then(r => r.data);

export const getIntelAppeals = () =>
  api.get('/intelligence/appeals').then(r => r.data);

export const getIntelLawyers = () =>
  api.get('/intelligence/lawyers').then(r => r.data);

export const getIntelTrends = () =>
  api.get('/intelligence/trends').then(r => r.data);

export const getIntelRights = () =>
  api.get('/intelligence/rights').then(r => r.data);

export const getIntelPredict = (params: Record<string, string>) =>
  api.get('/intelligence/predict', { params }).then(r => r.data);

export const getCalendarEvents = () =>
  api.get('/intelligence/calendar').then(r => r.data);

export const getDeadlineSummary = () =>
  api.get('/intelligence/deadlines').then(r => r.data);

// Agent
export const runAgent = (instruction: string) =>
  api.post('/agent/run', { instruction }, { timeout: 180000 }).then(r => r.data);

export const getAgentTools = () =>
  api.get('/agent/tools').then(r => r.data);

// Document management
export const suggestDocTarget = (docId: number) =>
  api.get(`/extraction/docs/${docId}/suggest-target`).then(r => r.data);

export const moveDocument = (docId: number, targetCaseId: number) =>
  api.post(`/extraction/docs/${docId}/move/${targetCaseId}`).then(r => r.data);

// Cleanup
export const getCleanupDiagnosis = () =>
  api.get('/cleanup/diagnosis').then(r => r.data);

export const runHashBackfill = (dryRun = true) =>
  api.post('/cleanup/hash-backfill', { dry_run: dryRun }).then(r => r.data);

export const runEmailsMdBackfill = (dryRun = true) =>
  api.post('/cleanup/emails-md-backfill', { dry_run: dryRun }).then(r => r.data);

export const runMoveNoPertenece = (dryRun = true, minConfidence = 'ALTA') =>
  api.post('/cleanup/move-no-pertenece', { dry_run: dryRun, min_confidence: minConfidence }).then(r => r.data);

export const runMergeIdentity = (dryRun = true, onlyAutoMergeable = true) =>
  api.post('/cleanup/merge-identity', { dry_run: dryRun, only_auto_mergeable: onlyAutoMergeable }).then(r => r.data);


// v5.0 Salud de Datos (post-audit KPIs)
export const getHealthV50 = () =>
  api.get('/cleanup/health-v50').then(r => r.data);

export const runPurgeDuplicates = (dryRun = true, scope = 'intra') =>
  api.post('/cleanup/purge-duplicates', { dry_run: dryRun, scope }).then(r => r.data);

export const runMergeForestFragments = (dryRun = true, minConfidence = 'ALTA') =>
  api.post('/cleanup/merge-forest-fragments', { dry_run: dryRun, min_confidence: minConfidence }).then(r => r.data);

export const runBackfillRadicados = (dryRun = true) =>
  api.post('/cleanup/backfill-radicados', { dry_run: dryRun }).then(r => r.data);

// ============================================================
// v9 — pipeline simplificado (39 campos del cuadro Excel)
// ============================================================

export interface V9CanonicalInfo {
  abogado: string | null;
  abogado_confidence: number;
  dependencia: string | null;
  dependencia_confidence: number;
  direccion_l1: string | null;
  grupo_l2: string | null;
  equipo_l3: string | null;
}

export interface V9ExtractionResult {
  case_id: number;
  folder_name: string;
  completitud: number;
  docs: { processed: number; failed: number };
  llm_calls: number;
  timing_ms: Record<string, number>;
  warnings: string[];
  values: Record<string, string>;
  sources: Record<string, string>;
  missing_fields: string[];
  canonical: V9CanonicalInfo;
  dry_run: boolean;
  applied?: boolean;
}

export interface V9BatchResponse {
  dry_run: boolean;
  applied: boolean;
  count: number;
  errors_count: number;
  summary: {
    avg_completitud: number;
    total_llm_calls: number;
    total_ms: number;
    ms_per_case: number;
  };
  results: V9ExtractionResult[];
  errors: Array<{ case_id: number; error: string }>;
}

export const v9Health = () =>
  api.get<{ status: string; version: string; fields_count: number; fields: string[] }>('/v9/health').then(r => r.data);

export const v9Preview = (caseId: number) =>
  api.get<V9ExtractionResult>(`/v9/preview/${caseId}`).then(r => r.data);

export const v9Extract = (caseId: number, apply = false) =>
  api.post<V9ExtractionResult>(`/v9/extract/${caseId}`, null, { params: { apply } }).then(r => r.data);

export const v9ExtractBatch = (params: { case_ids?: number[]; limit?: number; apply?: boolean }) =>
  api.post<V9BatchResponse>('/v9/extract-batch', params).then(r => r.data);

export default api;
