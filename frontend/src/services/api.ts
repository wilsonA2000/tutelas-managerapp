import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
});

// Cases
export const getCases = (params: Record<string, string | number>) =>
  api.get('/cases', { params }).then(r => r.data);

export const getCase = (id: number) =>
  api.get(`/cases/${id}`).then(r => r.data);

export const updateCase = (id: number, fields: Record<string, string>) =>
  api.put(`/cases/${id}`, fields).then(r => r.data);

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

// Dashboard
export const getKPIs = () =>
  api.get('/dashboard/kpis').then(r => r.data);

export const getCharts = () =>
  api.get('/dashboard/charts').then(r => r.data);

export const getActivity = () =>
  api.get('/dashboard/activity').then(r => r.data);

export const chatWithAI = (question: string) =>
  api.post('/dashboard/chat', { question }, { timeout: 60000 }).then(r => r.data);

// Documents
export const getDocumentPreviewUrl = (id: number) =>
  `/api/documents/${id}/preview`;

// Extraction
export const extractSingle = (caseId: number) =>
  api.post(`/extraction/single/${caseId}`, {}, { timeout: 180000 }).then(r => r.data);

export const extractBatch = (caseIds?: number[]) =>
  api.post('/extraction/batch', { case_ids: caseIds }, { timeout: 10000 }).then(r => r.data);

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

export const checkInbox = () =>
  api.post('/emails/check', {}, { timeout: 10000 }).then(r => r.data);

export const syncAllEmails = () =>
  api.post('/emails/sync', {}, { timeout: 10000 }).then(r => r.data);

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

// AI Provider
export const getAIProviders = () =>
  api.get('/ai/providers').then(r => r.data);

export const setAIProvider = (provider: string, model: string) =>
  api.put('/ai/provider', { provider, model }).then(r => r.data);

// Token Metrics
export const getTokenMetrics = () =>
  api.get('/tokens/metrics').then(r => r.data);

// Sync
export const syncFolders = () =>
  api.post('/sync', {}, { timeout: 10000 }).then(r => r.data);

export const getSyncStatus = () =>
  api.get('/sync/status').then(r => r.data);

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

export const dismissAlert = (id: number) =>
  api.post(`/alerts/${id}/dismiss`).then(r => r.data);

// Agent Extraction v3
export const agentExtract = (caseId: number, classify: boolean = false) =>
  api.post(`/extraction/agent/${caseId}?classify=${classify}`, {}, { timeout: 300000 }).then(r => r.data);

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

export const getAgentTokenStats = () =>
  api.get('/agent/tokens').then(r => r.data);

// DB Management
export const createBackup = () =>
  api.post('/db/backup').then(r => r.data);

export const listBackups = () =>
  api.get('/db/backups').then(r => r.data);

export const restoreBackup = (filename: string) =>
  api.post('/db/restore', null, { params: { filename } }).then(r => r.data);

export const startRebuild = (extractText = true, importCsv = true) =>
  api.post('/db/rebuild', null, { params: { extract_text: extractText, import_csv: importCsv } }).then(r => r.data);

export const getRebuildStatus = () =>
  api.get('/db/rebuild/status').then(r => r.data);

export const getSandboxCompare = () =>
  api.get('/db/sandbox/compare').then(r => r.data);

// Document management
export const suggestDocTarget = (docId: number) =>
  api.get(`/extraction/docs/${docId}/suggest-target`).then(r => r.data);

export const moveDocument = (docId: number, targetCaseId: number) =>
  api.post(`/extraction/docs/${docId}/move/${targetCaseId}`).then(r => r.data);

export default api;
