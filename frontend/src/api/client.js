import axios from 'axios';

const client = axios.create({ baseURL: '/api' });

export const listExceptions = (params) =>
  client.get('/ov-exceptions', { params }).then((r) => r.data);

export const getException = (id) => client.get(`/ov-exceptions/${id}`).then((r) => r.data);

export const clearException = (id, body) =>
  client.post(`/ov-exceptions/${id}/clear`, body).then((r) => r.data);

export const getClearingCodes = () => client.get('/clearing-codes').then((r) => r.data);

export const getCommodities = () => client.get('/commodities').then((r) => r.data);

export const getTerminals = () => client.get('/terminals').then((r) => r.data);

export const classifyException = (id) => client.post(`/classify/${id}`).then((r) => r.data);

export const classifyBatch = (params = {}) =>
  client
    .post('/classify/batch', null, { params: { force: false, with_notes: true, limit: 25, ...params } })
    .then((r) => r.data);

export const getHistory = (id) => client.get(`/classify/${id}/history`).then((r) => r.data);

export const overrideCategory = (id, body) =>
  client.post(`/classify/${id}/override`, body).then((r) => r.data);

export const getTaxonomy = () => client.get('/classify/taxonomy').then((r) => r.data);

export const getDistribution = (params) =>
  client.get('/insights/distribution', { params }).then((r) => r.data);

export const getCacheStats = () => client.get('/insights/cache-stats').then((r) => r.data);

export const getAccuracy = () => client.get('/insights/accuracy').then((r) => r.data);

export const getFilterOptions = () => client.get('/insights/filters').then((r) => r.data);

export const getRecommendations = () => client.get('/insights/recommendations').then((r) => r.data);

export const generateRecommendations = (body) =>
  client.post('/insights/recommendations/generate', body).then((r) => r.data);

export const getRecommendationEvidence = (id) =>
  client.get(`/insights/recommendations/${id}/evidence`).then((r) => r.data);

export const getInvestigationQuestions = () =>
  client.get('/investigation-questions').then((r) => r.data);

export const suggestProNumber = () => client.get('/pro-number/suggest').then((r) => r.data);

export const createException = (body) => client.post('/ov-exceptions', body).then((r) => r.data);

export const submitInvestigation = (id, body) =>
  client.post(`/ov-exceptions/${id}/investigation`, body).then((r) => r.data);

export const watchCheck = (body, config) =>
  client.post('/prevention/watch', body, config).then((r) => r.data);

export const notesAssist = (body, config) =>
  client.post('/prevention/notes-assist', body, config).then((r) => r.data);

export const getAttentionFlags = (params) =>
  client.get('/prevention/attention', { params }).then((r) => r.data);

export const scanAttention = (body) =>
  client.post('/prevention/attention/scan', body).then((r) => r.data);

export const acknowledgeFlag = (id, body) =>
  client.post(`/prevention/attention/${id}/acknowledge`, body).then((r) => r.data);

export const resolveFlag = (id, body) =>
  client.post(`/prevention/attention/${id}/resolve`, body).then((r) => r.data);

export const getFlagEvidence = (id) =>
  client.get(`/prevention/attention/${id}/evidence`).then((r) => r.data);

export const quantityVerify = (body) =>
  client.post('/prevention/staging-check/quantity-verify', body).then((r) => r.data);

export const correctQuantityCheck = (id, body) =>
  client
    .post(`/prevention/staging-check/quantity-verify/${id}/correct`, body)
    .then((r) => r.data);

export const confirmQuantityCheck = (id, body) =>
  client
    .post(`/prevention/staging-check/quantity-verify/${id}/confirm`, body)
    .then((r) => r.data);

export const evaluateRecommendations = (body) =>
  client.post('/prevention/recommendations/evaluate', body).then((r) => r.data);

export const getRecommendationLineage = (id) =>
  client.get(`/prevention/recommendations/${id}/lineage`).then((r) => r.data);

export const errorMessage = (err) =>
  err?.response?.data?.detail || err?.message || 'Unexpected error';

export default client;
